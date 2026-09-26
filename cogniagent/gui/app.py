import sys
import os
import re
os.environ["ANON_TELEMETRY"] = "False"
os.environ["CHROMA_TELEMETRY_STATUS"] = "False"
import time
import math
import ctypes
import subprocess
import shutil
import requests
import json
import threading
import logging
import webbrowser
import base64
from io import BytesIO
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from logging.handlers import RotatingFileHandler

try:
    import cv2
except ImportError:
    cv2 = None
import numpy as np
import mss

from cogniagent.gui.interventions import InterventionBroker
interventions = InterventionBroker()

from cogniagent.agent import CogniAgent
from cogniagent.config import config
from cogniagent.gui.html_assets import HTML_CONTENT

# Keep diagnostics out of the project root and bounded in size.  The previous
# append-only root log was tracked by Git and could grow indefinitely.
log_file_path = Path(__file__).resolve().parents[2] / "logs" / "gui_server.log"
is_test_process = (
    "unittest" in sys.modules
    or "pytest" in sys.modules
    or os.environ.get("OMNIVLA_TEST_MODE") == "1"
)

if not is_test_process:
    try:
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        root_logger = logging.getLogger()
        if not any(getattr(handler, "_omnivla_gui_log", False) for handler in root_logger.handlers):
            file_handler = RotatingFileHandler(
                log_file_path,
                maxBytes=1_000_000,
                backupCount=3,
                encoding="utf-8",
            )
            file_handler._omnivla_gui_log = True
            file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s'))
            root_logger.addHandler(file_handler)
            root_logger.setLevel(logging.INFO)
            logging.info("Initialized rotating GUI diagnostic log at %s", log_file_path)
    except Exception as le:
        print(f"Warning: Failed to setup GUI diagnostics logging: {le}")

# ─── Global State for Web UI ──────────────────────────────────────────────
status_lock = threading.RLock()
execution_lock = threading.RLock()

def get_safe_status(*, include_media: bool = True):
    with status_lock:
        import copy
        safe_status = copy.deepcopy(agent_status)
        safe_settings = safe_status.get("settings", {})
        safe_settings.pop("api_key", None)
        safe_settings["api_key_configured"] = bool(agent_status.get("settings", {}).get("api_key"))
        safe_status["settings"] = safe_settings
        if not include_media:
            safe_status.pop("latest_screenshot_b64", None)
            for step in safe_status.get("steps", []):
                if isinstance(step, dict):
                    step.pop("screenshot_b64", None)
        return safe_status

agent_status = {
    "status": "idle",
    "phase": "idle",
    "phase_started_at": None,
    "step": 0,
    "total_time_ms": 0,
    "current_action": "None",
    "hitl_question": "",
    "execution_task": "",
    "execution_chat_id": None,
    "latest_screenshot_b64": "",
    "steps": [],
    "paused": False,
    "chat_history": [],
    "planner_synthesis": "",
    "planner_activity": "",
    "ui_mode": "chat",
    "settings": {
        "model_path": "models/Holo-3.1-4B-abliterated-rdo.Q4_K_M.gguf",
        "planner_model_path": "models/Spark-X2.5-4B-Q4_K_M.gguf" if os.path.exists("models/Spark-X2.5-4B-Q4_K_M.gguf") else "models/Qwen3.5-4B.Q4_K_M.gguf",
        "temperature": 0.2,
        "enable_recording": False,
        "memory_enabled": False,
        "model_type": "local",
        "api_key": ""
    },
    "critic_review": {
        "status": "CORRECT",
        "reason": "Action verified as optimal.",
        "improved_prompt": ""
    },
    "timing": {
        "last_model_ms": None,
        "last_action_ms": None,
        "last_verification_ms": None,
        "last_step_ms": None,
        "updated_at": None,
    },
}

server_process = None
planner_process = None
active_planner_gpu = None
active_vla_max_gpu = None
console_process = None
overlay_process = None
running_thread = None
active_agent = None
stop_requested = False
hitl_event = threading.Event()
hitl_response = []

def stop_agent():
    """Immediately stop active agent run."""
    global stop_requested, active_agent
    stop_requested = True
    interventions.cancel()
    if active_agent:
        try:
            active_agent.stop()
        except Exception:
            pass


recording_active = False
recording_writer = None


def start_agent_task(task: str, run_policy: dict | None = None) -> bool:
    """Atomically start one desktop run and reject overlapping execution."""
    global running_thread, stop_requested
    with execution_lock:
        if running_thread and running_thread.is_alive():
            return False

        stop_requested = False
        interventions.cancel()
        worker = threading.Thread(
            target=execute_agent_task,
            args=(task, run_policy),
            name="omnivla-executor",
            daemon=True,
        )
        running_thread = worker
        worker.start()
        return True

def recording_loop(output_path, monitor_idx=1, fps=10.0):
    global recording_active, recording_writer
    if sys.platform == "win32":
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hdesk = user32.OpenDesktopW("default", 0, False, 0x01FF)
            if hdesk:
                user32.SetThreadDesktop(hdesk)
        except Exception:
            pass
    try:
        sct = mss.mss()
        if monitor_idx >= len(sct.monitors):
            monitor_idx = 0
        monitor = sct.monitors[monitor_idx]
        w, h = monitor["width"], monitor["height"]
        
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        recording_writer = cv2.VideoWriter(output_path, fourcc, fps, (w, h))
        
        frame_delay = 1.0 / fps
        logging.info(f"Screen recording started: {output_path} ({w}x{h} @ {fps}fps)")
        
        while recording_active:
            loop_start = time.time()
            try:
                sct_img = sct.grab(monitor)
                frame = np.array(sct_img)
                frame_bgr = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            except Exception:
                from PIL import ImageGrab
                pil_img = ImageGrab.grab()
                frame_bgr = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
            recording_writer.write(frame_bgr)
            
            elapsed = time.time() - loop_start
            sleep_time = max(0.01, frame_delay - elapsed)
            time.sleep(sleep_time)

    except Exception as e:
        logging.error(f"Error in screen recording thread: {e}")
    finally:
        if recording_writer:
            recording_writer.release()
            recording_writer = None
        logging.info("Screen recording stopped and saved.")

# ─── Custom Log Handler to capture logs for API ───────────────────────────
class WebLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.logs = []

    def emit(self, record):
        msg = self.format(record)
        self.logs.append(msg)
        if len(self.logs) > 500:
            self.logs.pop(0)

web_log_handler = WebLogHandler()
web_log_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
logging.getLogger().addHandler(web_log_handler)

# ─── VRAM Telemetry Helpers ───────────────────────────────────────────────
from gui_telemetry import get_free_vram, calculate_gpu_layers

class DesktopOverlay:
    def __init__(self):
        pass
    def blend_color(self, hex_color, bg_color, factor):
        return hex_color
    def get_rotating_color(self, position_angle, rotate_phase):
        return "#ffffff"
    def get_capsule_points(self, x1, y1, x2, y2, r, num_points=60):
        return []
    def draw_rotating_capsule_shadow(self, x1, y1, x2, y2, r, phase):
        pass
    def draw_wave_text(self, text, x_start, y_center, phase, is_bold=False):
        pass
    def draw_rotating_edges(self, phase):
        pass
    def draw_rounded_rect(self, x1, y1, x2, y2, r, **kwargs):
        pass
    def update_loop(self):
        pass

# ─── Server Manager Wrappers ──────────────────────────────────────────────
def start_planner_server(use_gpu=False):
    import cogniagent.gui.server_manager as sm
    res = sm.start_planner_server(use_gpu=use_gpu)
    global planner_process, active_planner_gpu
    planner_process = sm.planner_process
    active_planner_gpu = sm.active_planner_gpu
    return res

def run_planner_chat(message, chat_history=None, rag_context="", user_profile_context="", activity_callback=None,
                     learn_personal_context=True, tool_result_callback=None):
    import cogniagent.gui.server_manager as sm
    if chat_history is None:
        history = list(agent_status.get("chat_history", []))
    else:
        history = list(chat_history)
    temp = agent_status["settings"].get("temperature", 0.2)
    max_tokens = min(640, max(160, int(agent_status["settings"].get("max_tokens", 640))))
    config.llm.planner_model = agent_status["settings"].get("planner_model_path", config.llm.planner_model)
    return sm.run_planner_chat(message, history, temp, max_tokens, rag_context,
                               user_profile_context=user_profile_context, activity_callback=activity_callback,
                               learn_personal_context_enabled=learn_personal_context,
                               tool_result_callback=tool_result_callback)

def start_llama_server(max_gpu=True):
    import cogniagent.gui.server_manager as sm
    model_path = agent_status["settings"]["model_path"]
    res = sm.start_llama_server(model_path, max_gpu=max_gpu)
    global server_process, active_vla_max_gpu
    server_process = sm.server_process
    active_vla_max_gpu = sm.active_vla_max_gpu
    return res


# ─── Agent Execution Thread ───────────────────────────────────────────────
def summarize_timing_samples(samples):
    """Return bounded, deterministic timing statistics for persisted evals."""
    values = sorted(max(0, int(value)) for value in samples if isinstance(value, (int, float)))
    if not values:
        return None
    middle = len(values) // 2
    if len(values) % 2:
        median = values[middle]
    else:
        median = int(round((values[middle - 1] + values[middle]) / 2))
    p95 = values[max(0, math.ceil(len(values) * 0.95) - 1)]
    return {"count": len(values), "median_ms": median, "p95_ms": p95}


def synthesize_task_summary(
    user_intent: str,
    status: str,
    steps_executed: list,
    terminal_reason: str = "",
    final_thought: str = "",
) -> str:
    """Synthesize a clear, helpful, user-facing summary answering the user's intent.

    Avoids leaking raw internal reasoning thoughts, token-truncated fragments,
    or internal planning monologue.
    """
    user_intent = (user_intent or "").strip()
    status_success = (status == "success")
    clean_terminal = (terminal_reason or "").strip()

    monologue_starters = (
        "i need to", "let me", "i can see", "currently viewing", "i am", "rrently viewing",
        "i will", "first i", "next i", "we need to"
    )
    is_terminal_monologue = any(clean_terminal.lower().startswith(p) for p in monologue_starters)

    # Blacklist of raw actions, control primitives, and non-semantic tokens
    ignored_action_tokens = {
        "scroll", "finish task", "terminate", "wait", "none", "null", "undefined",
        "action completed", "click", "double click", "right click", "use", "open",
        "drag", "press key", "point to", "bring forward", "type", "reading the screen",
        "wait for operator input"
    }

    findings = []
    actions_taken = []
    seen_items = set()

    for s in steps_executed:
        action = str(s.get("action", "")).strip().lower()
        raw_text = s.get("action_text")
        action_text = str(raw_text).strip() if raw_text is not None else ""
        raw_note = s.get("note")
        note = str(raw_note).strip() if raw_note is not None else ""

        if note and note.lower() not in ignored_action_tokens and len(note) >= 3 and note not in seen_items:
            seen_items.add(note)
            findings.append(note)

        if " · " in action_text:
            target = action_text.split(" · ", 1)[1].strip()
            if (
                target
                and target.lower() not in ("microsoft edge", "google chrome", "notepad", "5s", "3s", "1s", "2s")
                and target.lower() not in ignored_action_tokens
                and len(target) >= 3
            ):
                if target not in seen_items:
                    seen_items.add(target)
                    actions_taken.append(target)
        elif action_text and action not in ("wait", "get_open_apps", "terminate", "scroll", "none"):
            if (
                action_text.lower() not in ignored_action_tokens
                and not any(action_text.lower() == tok for tok in ignored_action_tokens)
                and len(action_text) >= 3
                and action_text not in seen_items
            ):
                seen_items.add(action_text)
                actions_taken.append(action_text)

    # Check if clean_terminal provides an articulate, self-contained outcome
    has_substantive_terminal = bool(
        clean_terminal
        and not is_terminal_monologue
        and len(clean_terminal) >= 40
        and clean_terminal.lower() != user_intent.lower()
    )

    # 1. Neural Planner Post-Execution Synthesis (Holo -> Planner)
    # The Planner (Spark-X) transforms Holo's raw on-screen observations, notes,
    # and terminal outcome into a warm, natural, personal-assistant debrief.
    if user_intent and (actions_taken or findings or clean_terminal):
        for port in (8090, 8089):
            try:
                summary_context_lines = []
                if clean_terminal and not is_terminal_monologue:
                    summary_context_lines.append(f"Holo Execution Summary: {clean_terminal}")
                if actions_taken:
                    summary_context_lines.append("Items & Elements Inspected:")
                    for item in actions_taken[:8]:
                        summary_context_lines.append(f"- {item}")
                if findings:
                    summary_context_lines.append("On-Screen Observations:")
                    for f in findings[:6]:
                        summary_context_lines.append(f"- {f}")

                evidence_block = "\n".join(summary_context_lines)
                system_prompt = (
                    "You are OmniVLA's personal desktop assistant. You take the raw on-screen execution summary and "
                    "verified findings from the visual computer-use agent (Holo) and synthesize them into a warm, "
                    "articulate, executive personal assistant response for the user.\n\n"
                    "DIRECTIVES:\n"
                    "- Directly address the user's objective in a polite, helpful, personal assistant tone.\n"
                    "- Present the key findings, takeaways, or messages discovered on screen clearly and conversationally.\n"
                    "- Do NOT echo the user's prompt mechanically (e.g. avoid 'I've completed the task: <prompt>').\n"
                    "- Do NOT output raw action primitives, button clicks, click coordinates, or technical tool syntax.\n"
                    "- Base your response strictly on the verified facts in Holo's summary. Do not invent unobserved facts.\n"
                    "- Keep your debrief concise, focused, and under 120 words."
                )
                user_msg = (
                    f"User Request: {user_intent}\n"
                    f"Execution Status: {'Completed' if status_success else 'Stopped / Partial Progress'}\n\n"
                    f"Holo's Verified Findings:\n{evidence_block}\n\n"
                    "Please provide a user-facing assistant response answering my request."
                )
                payload = {
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_msg}
                    ],
                    "temperature": 0.3,
                    "max_tokens": 180,
                }
                resp = requests.post(f"http://127.0.0.1:{port}/v1/chat/completions", json=payload, timeout=30.0)
                if resp.status_code == 200:
                    answer = resp.json()["choices"][0]["message"].get("content", "").strip()
                    if answer and not any(answer.lower().startswith(p) for p in monologue_starters):
                        clean_answer = re.sub(r"<think>[\s\S]*?</think>", "", answer).strip()
                        if clean_answer and len(clean_answer) >= 15:
                            return clean_answer
            except Exception:
                continue

    # Deterministic assistant response synthesizer
    parts = []
    clean_intent = re.sub(
        r"^(?:can\s+you\s+|could\s+you\s+|please\s+)",
        "",
        user_intent,
        flags=re.IGNORECASE,
    ).strip()

    if status_success:
        if has_substantive_terminal:
            # If the model already gave an articulate summary (e.g., "Successfully reviewed latest WhatsApp messages...")
            # use that directly, avoiding redundant robotic prefaces like "I've completed the task: ..."
            if any(clean_terminal.lower().startswith(p) for p in ("successfully", "completed", "reviewed", "checked", "found")):
                parts.append(clean_terminal)
            else:
                headline = f"I've completed the task: **{clean_intent or user_intent}**."
                parts.append(f"{headline}\n\n{clean_terminal}")
        else:
            headline = f"I've completed the task: **{clean_intent or user_intent}**."
            parts.append(headline)
            if clean_terminal and not is_terminal_monologue and clean_terminal.lower() != user_intent.lower():
                parts.append(f"\n{clean_terminal}")
    else:
        if actions_taken or findings:
            headline = f"Execution progressed across {len(steps_executed)} actions for **{clean_intent or user_intent}**:"
            parts.append(headline)
            if clean_terminal and not is_terminal_monologue:
                parts.append(f"\n**Outcome note:** {clean_terminal}")
        else:
            parts.append(f"I was unable to complete the task: **{clean_intent or user_intent}**. Please review the active window and try again.")

    # ONLY append Key Discovered Items & Interactions if we did NOT have a substantive terminal answer
    # or if the task stopped with partial progress and needs evidence
    if (not has_substantive_terminal or not status_success) and (actions_taken or findings):
        parts.append("\n**Key Discovered Items & Interactions:**")
        for item in actions_taken[:6]:
            parts.append(f"- {item}")
        for note in findings[:4]:
            if note not in actions_taken:
                parts.append(f"- {note}")

    return "\n".join(parts)



def execute_agent_task(task, run_policy=None):
    global running_thread, stop_requested, recording_active, overlay_process
    recording_active = False
    run_policy = dict(run_policy or {})
    run_chat_id = run_policy.get("chat_id")
    run_started_at = time.perf_counter()
    timing_samples = {"model": [], "action": [], "verification": [], "step": []}
    final_run_status = "error"
    final_step_count = 0

    if sys.platform == "win32":
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hdesk = user32.OpenDesktopW("default", 0, False, 0x01FF)
            if hdesk:
                user32.SetThreadDesktop(hdesk)
        except Exception:
            pass

    with status_lock:
        agent_status["paused"] = False
        agent_status["status"] = "thinking"
        agent_status["phase"] = "thinking"
        agent_status["phase_started_at"] = time.time()
        agent_status["step"] = 0
        agent_status["total_time_ms"] = 0
        agent_status["current_action"] = "Reading the screen"
        agent_status["hitl_question"] = ""
        agent_status["latest_screenshot_b64"] = ""
        agent_status["steps"] = []
        agent_status["current_task"] = task
        agent_status["execution_task"] = task
        agent_status["execution_chat_id"] = run_chat_id
        agent_status["timing"] = {
            "last_model_ms": None,
            "last_action_ms": None,
            "last_verification_ms": None,
            "last_step_ms": None,
            "updated_at": None,
        }
    
    if agent_status["settings"].get("enable_recording", False):
        recording_active = True
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        video_filename = os.path.join("recordings", f"task_{timestamp}.mp4")
        rec_thread = threading.Thread(target=recording_loop, args=(video_filename,))
        rec_thread.daemon = True
        rec_thread.start()
    
    try:
        model_type = agent_status["settings"].get("model_type", "local")
        config.llm.model_type = model_type
        config.llm.model = agent_status["settings"]["model_path"]
        config.llm.temperature = agent_status["settings"]["temperature"]
        config.llm.api_key = agent_status["settings"].get("api_key", "")
        config.llm.planner_model = agent_status["settings"].get("planner_model_path", config.llm.planner_model)
        config.memory.enabled = bool(agent_status["settings"].get("memory_enabled", False))
        try:
            config.llm.context_size = max(2048, min(int(config.llm.context_size), 4096))
        except (TypeError, ValueError):
            config.llm.context_size = 4096
 
        if model_type == "local":
            # Models already loaded on startup. Ensure llama-server is healthy.
            if not start_llama_server(max_gpu=True):
                with status_lock:
                    agent_status["status"] = "error"
                    agent_status["current_action"] = "Failed to start VLA llama-server"
                return
        else:
            logging.info(f"Using cloud engine model_type: {model_type}, skipping local VLA llama-server startup.")

        if overlay_process is None or overlay_process.poll() is not None:
            logging.info("Starting desktop execution overlay...")
            try:
                overlay_process = subprocess.Popen(
                    [shutil.which("npm.cmd") or shutil.which("npm") or "npm", "start", "--prefix", "overlay-app"],
                    creationflags=0x08000000,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as oe:
                logging.error("Failed to start execution overlay: %s", oe)
            
        global active_agent
        agent = CogniAgent()
        agent.check_stop_callback = lambda: stop_requested
        agent.check_pause_callback = lambda: bool(agent_status.get("paused", False))
        agent.action_policy = {"mode": run_policy.get("mode", "supervised")}
        agent.expected_output = run_policy.get("expected_output", "")
        agent.success_criteria = list(run_policy.get("success_criteria", []))[:5]
        active_agent = agent
        
        def on_status_update(status, detail):
            if stop_requested:
                raise Exception("Task stopped manually.")
            with status_lock:
                paused = agent_status.get("paused", False)
            while paused:
                if stop_requested:
                    raise Exception("Task stopped manually during pause.")
                time.sleep(0.2)
                with status_lock:
                    paused = agent_status.get("paused", False)
                
            with status_lock:
                agent_status["status"] = status
                if agent_status.get("phase") != status:
                    agent_status["phase_started_at"] = time.time()
                agent_status["phase"] = status
                if status == "hitl":
                    agent_status["hitl_question"] = detail
                elif status in {"acting", "thinking", "verifying", "done", "failed", "stopped"}:
                    agent_status["hitl_question"] = ""
                if "|" in detail:
                    action, thought = detail.split("|", 1)
                    agent_status["current_action"] = action
                    agent_status["current_thought"] = thought
                else:
                    agent_status["current_action"] = detail
                    agent_status["current_thought"] = ""
            if status == "hitl":
                try:
                    from cogniagent.gui.server import persist_chat_execution
                    persist_chat_execution(run_chat_id, get_safe_status(include_media=False))
                except Exception:
                    pass
                    
        agent.on_status_change = on_status_update

        def on_timing_update(phase, duration_ms):
            timing_key = {
                "model": "last_model_ms",
                "action": "last_action_ms",
                "verification": "last_verification_ms",
                "step": "last_step_ms",
            }.get(phase)
            if not timing_key:
                return
            timing_samples[phase].append(max(0, int(duration_ms)))
            with status_lock:
                agent_status["timing"][timing_key] = max(0, int(duration_ms))
                agent_status["timing"]["updated_at"] = time.time()

        agent.on_timing_sample = on_timing_update

        def on_critic_eval(step_num, eval_state, reason="", improved_prompt=""):
            with status_lock:
                agent_status["critic_review"] = {
                    "step": step_num,
                    "status": eval_state,
                    "reason": reason,
                    "improved_prompt": improved_prompt
                }
            
        agent.on_critic_evaluation = on_critic_eval

        def on_step_complete(step_info):
            if stop_requested:
                raise Exception("Task stopped manually.")
                
            screenshot_b64 = step_info.get("screenshot_b64", "")
            if not screenshot_b64:
                try:
                    screenshot_b64 = capture_screen_base64(max_width=360, max_height=220, quality=60)
                except Exception as se:
                    logging.error(f"Failed to capture direct screen on step completion: {se}")

            with status_lock:
                step_info["screenshot_b64"] = screenshot_b64
                if screenshot_b64:
                    agent_status["latest_screenshot_b64"] = screenshot_b64
                step_info["critic_review"] = agent_status.get("critic_review", None)
                if "segment_id" not in step_info:
                    step_info["segment_id"] = 1
                if "eval_state" not in step_info:
                    step_info["eval_state"] = "EVALUATING"
                step_info["timing"] = dict(agent_status.get("timing", {}))
                agent_status["steps"].append(step_info)
                agent_status["step"] = step_info["step"]

            try:
                from cogniagent.gui.server import persist_chat_execution
                persist_chat_execution(run_chat_id, get_safe_status(include_media=False))
            except Exception as snapshot_error:
                logging.debug("Unable to persist live execution snapshot: %s", snapshot_error)

        agent.on_step_complete = on_step_complete

        
        def request_intervention(kind, question, action=None):
            interventions.open(agent.run_id, kind, question, action)
            on_status_update("hitl", question)
            try:
                return interventions.wait(lambda: stop_requested or agent._should_stop())
            finally:
                with status_lock:
                    agent_status["hitl_question"] = ""

        agent.request_intervention = request_intervention

        # The first reasoning call is observation-only; a fixed three-second
        # countdown only made the app appear stalled.
        time.sleep(0.1)
        
        max_steps = (run_policy or {}).get("max_steps")
        result = agent.run_task(task, max_steps=max_steps)
        
        if stop_requested:
            raise Exception("Task stopped manually.")
            
        status = result.get("status", "failed")
        steps_executed = result.get("steps", [])
        final_run_status = "success" if status == "success" else "failed"
        final_step_count = len(steps_executed)
        terminal_reason = result.get("terminal_reason", "")
        final_thought = result.get("final_thought", "")

        # Resolve the run's originating chat. The operator may inspect another
        # run while execution is active, so the active sidebar selection is not
        # a stable execution identity.
        user_intent = ""
        try:
            from cogniagent.gui.server import load_chats_db, db_lock
            with db_lock:
                db_temp = load_chats_db()
                target_id = run_chat_id or db_temp.get("active_chat_id")
                active_c = next((c for c in db_temp.get("chats", []) if c["id"] == target_id), None)
                if active_c:
                    user_intent = active_c.get("intent") or ""
        except Exception:
            pass

        # Collect observations and findings discovered on screen
        observations = []
        for s in steps_executed:
            th = s.get("thought", "").strip()
            if th and th not in ("Screen inspected.", "Proceeding with next UI action.", "Analyzing screen context."):
                observations.append(f"Step {s.get('step', '?')} observation/thought: {th}")
            nt = s.get("note", "")
            if nt:
                observations.append(f"Step {s.get('step', '?')} note: {nt}")
        if terminal_reason:
            observations.append(f"Final Execution Reason/Result: {terminal_reason}")
        elif final_thought:
            observations.append(f"Final Thought: {final_thought}")

        obs_text = "\n".join(observations) if observations else "The visual agent executed all steps successfully on screen."

        # Synthesize a grounded, helpful final summary answering user_intent
        # rather than dumping raw internal reasoning fragments or truncated text.
        summary = synthesize_task_summary(
            user_intent=user_intent,
            status=status,
            steps_executed=steps_executed,
            terminal_reason=terminal_reason,
            final_thought=final_thought,
        )

        try:
            from cogniagent.gui.server import load_chats_db, save_chats_db, db_lock
            with db_lock:
                db = load_chats_db()
                target_id = run_chat_id or db.get("active_chat_id")
                for c in db.get("chats", []):
                    if c["id"] == target_id:
                        c["status"] = "success" if status == "success" else "failed"
                        terminal_prefixes = ("task completed", "completed the task", "the task could not", "task failed")
                        c["chat_history"] = [
                            message for message in c["chat_history"]
                            if not (
                                message.get("role") == "assistant"
                                and (
                                    message.get("kind") == "run_result"
                                    or str(message.get("content") or "").strip().casefold().startswith(terminal_prefixes)
                                )
                            )
                        ]
                        c["chat_history"].append({"role": "assistant", "kind": "run_result", "content": summary,
                                                  "completion_evidence": result.get("completion_evidence")})
                        save_chats_db(db)
                        try:
                            from cogniagent.memory.user_profile import get_user_profile
                            get_user_profile().learn_from_task(user_intent, steps_executed, status, summary)
                        except Exception as profile_learn_err:
                            logging.debug("User profile habit reinforcement skipped: %s", profile_learn_err)
                        break
        except Exception as dbe:
            logging.error(f"Failed to update chat status in DB: {dbe}")

        # Send native Windows desktop notification upon task completion
        try:
            from cogniagent.tools.notifications import send_notification
            notif_title = "OmniVLA Task Complete" if status == "success" else "OmniVLA Task Needs Attention"
            notif_msg = f"{user_intent[:60] if user_intent else task[:60]}\nStatus: {status.upper()}"
            send_notification(notif_title, notif_msg)
        except Exception as notif_err:
            logging.debug("Task completion notification skipped: %s", notif_err)

        with status_lock:
            agent_status["status"] = "done" if status == "success" else "failed"
            agent_status["phase"] = agent_status["status"]
            agent_status["phase_started_at"] = time.time()
            agent_status["current_action"] = "Task completed" if status == "success" else "Task needs attention"
            with status_lock:
                agent_status["ui_mode"] = "chat"
        
    except Exception as e:
        if stop_requested:
            final_run_status = "stopped"
            with status_lock:
                agent_status["status"] = "stopped"
                agent_status["phase"] = "stopped"
                agent_status["phase_started_at"] = time.time()
                agent_status["current_action"] = "Stopped manually"
                agent_status["current_thought"] = "Task terminated by user request."
                agent_status["ui_mode"] = "chat"
        else:
            final_run_status = "error"
            logging.exception(f"Execution error: {e}")
            err_msg = str(e).strip() or "The task stopped unexpectedly."
            with status_lock:
                agent_status["status"] = "error"
                agent_status["phase"] = "error"
                agent_status["phase_started_at"] = time.time()
                agent_status["current_action"] = f"Error: {err_msg}"[:120]
                agent_status["current_thought"] = err_msg
            try:
                from cogniagent.gui.server import load_chats_db, save_chats_db, db_lock
                with db_lock:
                    db = load_chats_db()
                    target_id = run_chat_id or db.get("active_chat_id")
                    for c in db.get("chats", []):
                        if c["id"] == target_id:
                            c["status"] = "failed"
                            c["chat_history"].append({"role": "assistant", "kind": "run_result", "content": f"Execution error: {err_msg}"})
                            save_chats_db(db)
                            break
            except Exception:
                pass
    finally:
        duration_ms = max(0, int((time.perf_counter() - run_started_at) * 1000))
        with status_lock:
            agent_status["total_time_ms"] = duration_ms
            final_step_count = max(final_step_count, len(agent_status.get("steps", [])))
            settings_snapshot = dict(agent_status.get("settings", {}))
        metrics = {
            "status": final_run_status,
            "finished_at": int(time.time()),
            "duration_ms": duration_ms,
            "steps": final_step_count,
            "phases": {
                phase: summary
                for phase, values in timing_samples.items()
                if (summary := summarize_timing_samples(values)) is not None
            },
            "profile": {
                "engine": str(settings_snapshot.get("model_type", "local")),
                "vla": os.path.basename(str(settings_snapshot.get("model_path", "unknown"))),
                "planner": os.path.basename(str(settings_snapshot.get("planner_model_path", "unknown"))),
            },
        }
        try:
            from cogniagent.gui.server import load_chats_db, save_chats_db, db_lock, _normalize_execution_snapshot
            with db_lock:
                database = load_chats_db()
                target_id = run_chat_id or database.get("active_chat_id")
                target_chat = next((chat for chat in database.get("chats", []) if chat["id"] == target_id), None)
                if target_chat:
                    target_chat["run_metrics"] = metrics
                    if final_run_status != "success":
                        target_chat["status"] = "stopped" if final_run_status == "stopped" else "failed"
                    target_chat["execution"] = _normalize_execution_snapshot(get_safe_status(include_media=False))
                    target_chat["updated_at"] = int(time.time())
                    save_chats_db(database)
        except Exception as metrics_error:
            logging.warning("Unable to persist run metrics: %s", metrics_error)
        recording_active = False
        with execution_lock:
            if running_thread is threading.current_thread():
                running_thread = None
        pass

# ─── Mock compatibility layers for testing ────────────────────────────────
def parse_server_log_for_optimizations(log_line: str) -> dict:
    import cogniagent.gui.server_manager as sm
    return sm.parse_server_log_for_optimizations(log_line)

def check_vram_limit(free_vram_gb: float) -> str:
    import cogniagent.gui.server_manager as sm
    return sm.check_vram_limit(free_vram_gb)

class TextHandler(logging.Handler):
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget

    def emit(self, record):
        msg = self.format(record)
        tag = "default"
        if record.levelno == logging.ERROR:
            tag = "error"
        elif record.levelno == logging.WARNING:
            tag = "warning"
        self.text_widget.after(10, lambda: self.text_widget.insert('end', msg + '\n', tag))

class OmniVLA_GUI:
    def __init__(self):
        self.server_process = None
    def _start_server(self):
        global server_process
        server_process = None
        start_llama_server()
        self.server_process = server_process
    def destroy(self):
        global server_process
        server_process = None
        import cogniagent.gui.server_manager as sm
        sm.server_process = None
        sm.planner_process = None

def sync_chats_on_startup():
    db_path = "chats_db.json"
    from cogniagent.gui.server import db_lock, load_chats_db
    with db_lock:
        try:
            db = load_chats_db()
            active_id = db.get("active_chat_id")
            for c in db.get("chats", []):
                if c["id"] == active_id:
                    agent_status["chat_history"] = c.get("chat_history", [])
                    agent_status["current_task"] = c.get("current_task", "")
                    break
            if "settings" in db:
                agent_status["settings"].update(db["settings"])
                logging.info(f"Loaded active settings from {db_path} on startup.")
        except Exception as e:
            logging.error(f"Failed to sync chats on startup: {e}")

def shutdown_runtime(*, include_console: bool = True) -> None:
    """Stop the active run and release all owned model/runtime processes."""
    global server_process, planner_process, console_process, overlay_process, recording_active
    stop_agent()
    recording_active = False
    owned = [
        ("execution overlay", overlay_process),
        ("VLA server", server_process),
        ("planner server", planner_process),
    ]
    if include_console:
        owned.append(("command center", console_process))
    for label, process in owned:
        if not process or process.poll() is not None:
            continue
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception as error:
            logging.warning("Unable to stop owned %s cleanly: %s", label, error)


def main():
    global server_process, planner_process, console_process
    from cogniagent.gui.server import WebUIRequestHandler, local_session_token
    # This credential is inherited only by our Electron child processes.
    os.environ["OMNIVLA_SESSION_TOKEN"] = local_session_token

    os.environ["CHROMA_TELEMETRY_STATUS"] = "False"
    sync_chats_on_startup()

    server_host = os.environ.get("OMNIVLA_HOST", "127.0.0.1").strip()
    if server_host not in {"127.0.0.1", "0.0.0.0", "::1"}:
        logging.warning("Unsupported OMNIVLA_HOST '%s'; falling back to loopback.", server_host)
        server_host = "127.0.0.1"
    server_address = (server_host, 8000)
    httpd = None
    for attempt in range(5):
        try:
            httpd = ThreadingHTTPServer(server_address, WebUIRequestHandler)
            break
        except OSError as e:
            logging.warning(f"Failed to bind to {server_host}:8000 (attempt {attempt+1}/5): {e}")
            logging.error("Port 8000 is occupied. Close the owning app or stop the existing OmniVLA instance.")
            break
            
    if not httpd:
        logging.critical("CRITICAL: Failed to bind to port 8000 after 5 attempts. Exiting.")
        sys.exit(1)
    
    print("====================================================")
    print("OmniVLA is running.")
    print(f"URL Endpoint: http://127.0.0.1:8000 (bound to {server_host})")
    print("====================================================")
    
    # Honour the explicit test-mode escape hatch as well as test runners.  It
    # lets the web shell be validated without booting either local model or
    # Electron, which is especially important on the 6 GB target machine.
    is_testing = is_test_process
    
    if not is_testing:
        from cogniagent.gui.server import start_telemetry_thread
        start_telemetry_thread()
        
        def init_models_sequential():
            logging.info("Pre-initializing VLA model on startup...")
            start_llama_server(max_gpu=True)
            # The CPU planner starts on demand and unloads after each plan so
            # browsers and other desktop apps retain enough system memory.

        t = threading.Thread(target=init_models_sequential)
        t.daemon = True
        t.start()
        
    if not is_testing:
        def launch_electron_delayed():
            time.sleep(1.5)
            global console_process
            logging.info("Starting Electron dedicated console app...")
            try:
                electron_path = os.path.join("overlay-app", "node_modules", "electron", "dist", "electron.exe")
                if os.path.exists(electron_path):
                    console_process = subprocess.Popen(
                        [electron_path, "console-app"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                else:
                    npx_executable = shutil.which("npx.cmd") or shutil.which("npx") or "npx"
                    console_process = subprocess.Popen(
                        [npx_executable, "electron", "console-app"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                
                def log_stream(stream, prefix):
                    try:
                        for line in iter(stream.readline, b''):
                            line_str = line.decode('utf-8', errors='ignore').strip()
                            if line_str:
                                logging.info(f"[{prefix}] {line_str}")
                    except Exception:
                        pass
                
                t_out = threading.Thread(target=log_stream, args=(console_process.stdout, "Electron"))
                t_out.daemon = True
                t_out.start()
                
                t_err = threading.Thread(target=log_stream, args=(console_process.stderr, "Electron-Err"))
                t_err.daemon = True
                t_err.start()
                
            except Exception as e:
                logging.error(f"Failed to launch Electron Console: {e}")
        
        t_el = threading.Thread(target=launch_electron_delayed)
        t_el.daemon = True
        t_el.start()
        
    import atexit
    def cleanup_processes():
        logging.info("Terminating OmniVLA-owned backend and console processes...")
        shutdown_runtime()
    atexit.register(cleanup_processes)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        cleanup_processes()
        if server_process:
            try: server_process.terminate()
            except Exception: pass
        if planner_process:
            try: planner_process.terminate()
            except Exception: pass
        httpd.server_close()
