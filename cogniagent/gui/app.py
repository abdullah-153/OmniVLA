import sys
import os
os.environ["ANON_TELEMETRY"] = "False"
os.environ["CHROMA_TELEMETRY_STATUS"] = "False"
import time
import math
import ctypes
import subprocess
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

import cv2
import numpy as np
import mss

from cogniagent.agent import CogniAgent
from cogniagent.config import config
from cogniagent.gui.html_assets import HTML_CONTENT

# Keep diagnostics out of the project root and bounded in size.  The previous
# append-only root log was tracked by Git and could grow indefinitely.
log_file_path = Path(__file__).resolve().parents[2] / "logs" / "gui_server.log"
is_test_process = (
    "pytest" in sys.modules
    or "unittest" in sys.modules
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

def get_safe_status():
    with status_lock:
        import copy
        safe_status = copy.deepcopy(agent_status)
        safe_settings = safe_status.get("settings", {})
        safe_settings.pop("api_key", None)
        safe_settings["api_key_configured"] = bool(agent_status.get("settings", {}).get("api_key"))
        safe_status["settings"] = safe_settings
        return safe_status

agent_status = {
    "status": "idle",
    "phase": "idle",
    "phase_started_at": None,
    "step": 0,
    "total_time_ms": 0,
    "current_action": "None",
    "latest_screenshot_b64": "",
    "steps": [],
    "paused": False,
    "chat_history": [{"role": "assistant", "content": "Hello! I am your Planner and Orchestrator. What would you like me to accomplish on your desktop today?"}],
    "planner_synthesis": "",
    "ui_mode": "chat",
    "settings": {
        "model_path": "models/Holo-3.1-4B-abliterated-rdo.Q4_K_M.gguf",
        "temperature": 0.2,
        "max_steps": 15,
        "enable_recording": False,
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
electron_process = None
running_thread = None
stop_requested = False
hitl_event = threading.Event()
hitl_response = []

recording_active = False
recording_writer = None


def start_agent_task(task: str) -> bool:
    """Atomically start one desktop run and reject overlapping execution."""
    global running_thread
    with execution_lock:
        if running_thread and running_thread.is_alive():
            return False

        worker = threading.Thread(
            target=execute_agent_task,
            args=(task,),
            name="omnivla-executor",
            daemon=True,
        )
        running_thread = worker
        worker.start()
        return True

def recording_loop(output_path, monitor_idx=1, fps=10.0):
    global recording_active, recording_writer
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
            sct_img = sct.grab(monitor)
            frame = np.array(sct_img)
            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
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

def run_planner_chat(message, rag_context=""):
    import cogniagent.gui.server_manager as sm
    history = agent_status.get("chat_history", [])
    temp = agent_status["settings"].get("temperature", 0.2)
    max_tokens = min(512, max(128, int(agent_status["settings"].get("max_tokens", 512))))
    return sm.run_planner_chat(message, history, temp, max_tokens, rag_context)

def start_llama_server(max_gpu=False):
    import cogniagent.gui.server_manager as sm
    model_path = agent_status["settings"]["model_path"]
    res = sm.start_llama_server(model_path, max_gpu=max_gpu)
    global server_process, active_vla_max_gpu
    server_process = sm.server_process
    active_vla_max_gpu = sm.active_vla_max_gpu
    return res

# ─── Agent Execution Thread ───────────────────────────────────────────────
def execute_agent_task(task):
    global running_thread, stop_requested, recording_active, electron_process
    stop_requested = False
    recording_active = False
    with status_lock:
        agent_status["paused"] = False
        agent_status["status"] = "thinking"
        agent_status["phase"] = "thinking"
        agent_status["phase_started_at"] = time.time()
        agent_status["step"] = 0
        agent_status["total_time_ms"] = 0
        agent_status["current_action"] = "Agent is working..."
        agent_status["latest_screenshot_b64"] = ""
        agent_status["steps"] = []
        agent_status["current_task"] = task
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

        logging.info("Starting Electron desktop overlay app...")
        try:
            electron_process = subprocess.Popen(
                ["npm", "start", "--prefix", "overlay-app"],
                shell=True,
                creationflags=0x08000000
            )
        except Exception as oe:
            logging.error(f"Failed to start Electron overlay: {oe}")
            
        agent = CogniAgent()
        
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
                if "|" in detail:
                    action, thought = detail.split("|", 1)
                    agent_status["current_action"] = action
                    agent_status["current_thought"] = thought
                else:
                    agent_status["current_action"] = detail
                    if status == "thinking":
                        agent_status["current_thought"] = "Analyzing screen context..."
                    
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
            with status_lock:
                timings = agent_status.setdefault("timing", {})
                timings[timing_key] = int(duration_ms)
                timings["updated_at"] = time.time()

        agent.on_timing_update = on_timing_update

        def on_step_complete(step_info):
            screenshot_b64 = ""
            try:
                with mss.mss() as sct:
                    monitor = sct.monitors[1]
                    sct_img = sct.grab(monitor)
                    from PIL import Image
                    img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                    buffered = BytesIO()
                    img.save(buffered, format="JPEG", quality=60)
                    screenshot_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
            except Exception as se:
                logging.error(f"Failed to capture direct screen on step completion: {se}")

            with status_lock:
                step_info["screenshot_b64"] = screenshot_b64
                step_info["critic_review"] = agent_status.get("critic_review", None)
                if "segment_id" not in step_info:
                    step_info["segment_id"] = 1
                if "eval_state" not in step_info:
                    step_info["eval_state"] = "EVALUATING"
                step_info["timing"] = dict(agent_status.get("timing", {}))
                agent_status["steps"].append(step_info)
                agent_status["step"] = step_info["step"]

        agent.on_step_complete = on_step_complete
        
        def wait_for_hitl():
            hitl_event.clear()
            hitl_response.clear()
            while not hitl_event.is_set():
                if stop_requested:
                    raise Exception("Task stopped manually during intervention.")
                time.sleep(0.2)
            return hitl_response[0] if hitl_response else "No response"
            
        agent.wait_for_hitl_response = wait_for_hitl
        
        logging.info("Hands off the mouse in 3 seconds...")
        time.sleep(3)
        
        with status_lock:
            max_steps = agent_status["settings"]["max_steps"]
        result = agent.run_task(task, max_steps=max_steps)
        
        if stop_requested:
            raise Exception("Task stopped manually.")
            
        status = result.get("status", "failed")
        try:
            from cogniagent.gui.server import load_chats_db, save_chats_db
            db = load_chats_db()
            active_id = db.get("active_chat_id")
            for c in db.get("chats", []):
                if c["id"] == active_id:
                    c["status"] = "success" if status == "success" else "failed"
                    save_chats_db(db)
                    break
        except Exception as dbe:
            logging.error(f"Failed to update chat status in DB: {dbe}")
            
        with status_lock:
            agent_status["status"] = "done" if status == "success" else "failed"
            agent_status["phase"] = agent_status["status"]
            agent_status["phase_started_at"] = time.time()
            agent_status["current_action"] = f"Finished: {status}"
        
        steps_log = "\n".join([f"Step {s['step']}: {s.get('thought', '')}" for s in agent_status["steps"]])
        
        synthesis_prompt = (
            f"Based on the execution logs of the visual action model, synthesize a conversational final answer "
            f"for the user. Tell them clearly what was accomplished or found.\n\n"
            f"Note: The overall task execution status is: {status.upper()}.\n"
            f"If it is FAILED, you MUST clearly state that the task failed or was unable to be completed successfully, "
            f"do NOT claim it was successfully completed.\n\n"
            f"User Original Request: {task}\n"
            f"Execution Logs:\n{steps_log}"
        )
        
        synthesis_payload = {
            "messages": [
                {"role": "user", "content": synthesis_prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 512
        }
        try:
            r = requests.post("http://127.0.0.1:8090/v1/chat/completions", json=synthesis_payload, timeout=60)
            if r.status_code == 200:
                final_answer = r.json()["choices"][0]["message"]["content"]
                with status_lock:
                    agent_status["planner_synthesis"] = final_answer
                    if "chat_history" not in agent_status:
                        agent_status["chat_history"] = []
                    agent_status["chat_history"].append({"role": "assistant", "content": final_answer})
            else:
                final_answer = f"Task concluded with status: {status}. The planner failed to synthesize a report."
                with status_lock:
                    agent_status["planner_synthesis"] = final_answer
                    if "chat_history" not in agent_status:
                        agent_status["chat_history"] = []
                    agent_status["chat_history"].append({"role": "assistant", "content": final_answer})
        except Exception as e:
            logging.error(f"Error in planner synthesis: {e}")
            final_answer = f"Task concluded with status: {status}."
            if status == "success":
                final_answer += " The task was executed successfully."
            else:
                final_answer += " The executor encountered an issue or reached the step limit before completing the goal."
            with status_lock:
                agent_status["planner_synthesis"] = final_answer
                if "chat_history" not in agent_status:
                    agent_status["chat_history"] = []
                agent_status["chat_history"].append({"role": "assistant", "content": final_answer})
                
        # Persist updated chat history to database
        try:
            from cogniagent.gui.server import load_chats_db, save_chats_db
            db = load_chats_db()
            active_id = db.get("active_chat_id")
            for c in db.get("chats", []):
                if c["id"] == active_id:
                    c["chat_history"] = agent_status["chat_history"]
                    c["status"] = "success" if status == "success" else "failed"
                    save_chats_db(db)
                    break
        except Exception as dbe:
            logging.error(f"Failed to persist final chat history to DB: {dbe}")
            
        if status == "success":
            with status_lock:
                agent_status["ui_mode"] = "chat"
        
    except Exception as e:
        if stop_requested:
            with status_lock:
                agent_status["status"] = "idle"
                agent_status["phase"] = "idle"
                agent_status["phase_started_at"] = time.time()
                agent_status["current_action"] = "Stopped manually"
                agent_status["current_thought"] = "Task terminated by user request."
                agent_status["ui_mode"] = "chat"
        else:
            logging.error(f"Error: {e}")
            with status_lock:
                agent_status["status"] = "error"
                agent_status["phase"] = "error"
                agent_status["phase_started_at"] = time.time()
                agent_status["current_action"] = str(e)
    finally:
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

def main():
    global server_process, planner_process, electron_process
    from gui_telemetry import kill_port_owner
    from cogniagent.gui.server import WebUIRequestHandler
    # Do not terminate every llama-server or Electron process on the machine.
    # Port cleanup is limited to OmniVLA's own fixed endpoints, while normal
    # shutdown below only terminates processes this instance launched.
    kill_port_owner(8000)
    kill_port_owner(8082)
    kill_port_owner(8089)
    kill_port_owner(8090)

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
            kill_port_owner(8000)
            time.sleep(1.0)
            
    if not httpd:
        logging.critical("CRITICAL: Failed to bind to port 8000 after 5 attempts. Exiting.")
        sys.exit(1)
    
    print("====================================================")
    print("OmniVLA Command Center Running...")
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
            time.sleep(2.0)
            logging.info("Pre-initializing Planner model on startup...")
            # Keep the critic on CPU so the Holo vision model owns the 6 GB
            # GPU. This avoids VRAM pressure and model-layer CPU spillover.
            start_planner_server(use_gpu=False)
        t = threading.Thread(target=init_models_sequential)
        t.daemon = True
        t.start()
        
    if not is_testing:
        def launch_electron_delayed():
            time.sleep(1.5)
            global electron_process
            logging.info("Starting Electron dedicated console app...")
            try:
                electron_path = os.path.join("overlay-app", "node_modules", "electron", "dist", "electron.exe")
                if os.path.exists(electron_path):
                    electron_process = subprocess.Popen(
                        [electron_path, "console-app"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        creationflags=0x08000000
                    )
                else:
                    electron_process = subprocess.Popen(
                        ["npx", "electron", "console-app"],
                        shell=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        creationflags=0x08000000
                    )
                
                def log_stream(stream, prefix):
                    try:
                        for line in iter(stream.readline, b''):
                            line_str = line.decode('utf-8', errors='ignore').strip()
                            if line_str:
                                logging.info(f"[{prefix}] {line_str}")
                    except Exception:
                        pass
                
                t_out = threading.Thread(target=log_stream, args=(electron_process.stdout, "Electron"))
                t_out.daemon = True
                t_out.start()
                
                t_err = threading.Thread(target=log_stream, args=(electron_process.stderr, "Electron-Err"))
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
        for label, process in (
            ("VLA server", server_process),
            ("planner server", planner_process),
            ("command center", electron_process),
        ):
            if not process or process.poll() is not None:
                continue
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception as error:
                logging.warning("Unable to stop owned %s cleanly: %s", label, error)
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
        if electron_process:
            try: electron_process.terminate()
            except Exception: pass
        httpd.server_close()
