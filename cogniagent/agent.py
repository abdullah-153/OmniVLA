import logging
import re
import sys
import time
import threading
import copy
import base64
import json
import secrets
from io import BytesIO
from PIL import Image
import numpy as np

from cogniagent.config import config
from cogniagent.perception.vlm_engine import VLMEngine, checkpoint_execution_context
from cogniagent.execution.router import ActionRouter, PauseRequested
from cogniagent.memory.episodic_memory import EpisodicMemory, Episode, Trajectory
from cogniagent.perception.verification import ScreenVerifier
from cogniagent.reasoning.action_reasoner import AgentAction
from cogniagent.skills.skill_registry import SkillRegistry

logger = logging.getLogger(__name__)


class CogniAgent:

    """Holo3 Pure-VLM multimodal agent with fast Win32 execution, hybrid verification, and dynamic skills."""
    
    def __init__(self, custom_config=None):
        self.config = custom_config or config
        self.vlm = VLMEngine()
        self.executor = ActionRouter(self.config)
        self.memory = EpisodicMemory(self.config)
        self.verifier = ScreenVerifier(self.config.perception.max_visual_diff_pixels)
        self.skills_registry = SkillRegistry()

        
        # Event callbacks
        self.on_status_change = None
        self.on_timing_update = None
        self.on_step_complete = None
        self.on_critic_update = None
        self.wait_for_hitl_response = None
        self.stop_requested = False
        self.check_stop_callback = None
        self.check_pause_callback = None
        self.action_policy = {"mode": "supervised"}
        self.run_id = secrets.token_urlsafe(18)
        self.request_intervention = None
        self.expected_output = ""
        self.success_criteria = []
        self.completion_evidence = None
        self.executor.check_cancelled = self._should_stop
        self.executor.check_paused = lambda: bool(callable(self.check_pause_callback) and self.check_pause_callback())

    def stop(self):
        """Signal the agent to abort execution immediately."""
        self.stop_requested = True

    def _should_stop(self) -> bool:
        """Check if an emergency stop was requested by UI or operator."""
        if self.stop_requested:
            return True
        if callable(self.check_stop_callback) and self.check_stop_callback():
            return True
        return False

    def _wait_while_paused(self) -> bool:
        """Pause at action boundaries and report whether execution should stop."""
        notified = False
        while callable(self.check_pause_callback) and self.check_pause_callback():
            if not notified:
                self._notify("paused", "Run paused by operator.")
                notified = True
            if self._should_stop():
                return True
            time.sleep(0.1)
        return self._should_stop()

    def _ask(self, kind, question, action=None):
        if callable(self.request_intervention):
            return self.request_intervention(kind, question, action)
        self._notify("hitl", question)
        return self.wait_for_hitl_response() if callable(self.wait_for_hitl_response) else "deny"

    def _observation_matches(self, result):
        """Re-check the screen immediately before dispatch, including after approval."""
        if not result.get("captured_at"):
            return True  # Non-runtime callers must supply their own observation contract.
        if self._should_stop():
            return False
        from cogniagent.execution import win32_input
        if result.get("focus_context") != win32_input.get_focus_context():
            return False
        fresh, dims = self.vlm.capture_screen(for_vlm=False)
        if dims != result.get("orig_dims"):
            return False
        fresh = fresh.resize(result["screenshot"].size)
        diff = self.verifier.compute_screen_diff(np.array(result["screenshot"]), np.array(fresh))
        return diff.get("diff_ratio", 1) < 0.01 and time.monotonic() - result["captured_at"] <= 120

    def _dispatch(self, result, dimensions):
        if self._wait_while_paused() or not self._observation_matches(result):
            return {"success": False, "is_done": False, "detail": "Input withheld: execution stopped or the observed screen changed. Re-observe and re-ground the next action."}
        try:
            return self.executor.execute_vlm_action(result, dimensions)
        except PauseRequested:
            return {"success": False, "is_done": False, "detail": "Paused at an input boundary. Re-observe before resuming."}

    def _verify_completion(self, task, result):
        if self._should_stop():
            return False
        try:
            outcome = self.vlm.verify_completion(task, self.expected_output, self.success_criteria)
        except Exception:
            outcome = {"verified": False, "evidence": "Independent verification was unavailable."}
        if isinstance(outcome, dict) and outcome.get("verified") is True and outcome.get("evidence"):
            self.completion_evidence = {"source": "visual", "evidence": str(outcome["evidence"])[:1500],
                                        "criteria": outcome.get("criteria", [])[:5]}
            return True
        reason = outcome.get("evidence", "The outcome could not be independently established.") if isinstance(outcome, dict) else "Verification unavailable."
        requirements = "; ".join(self.success_criteria) or self.expected_output or task[:400]
        answer = self._ask("completion", f"Confirm the requested outcome was achieved: {requirements}\n{reason}", result.get("parsed_action"))
        accepted = answer == "approve" and not self._should_stop()
        self.completion_evidence = {"source": "operator" if accepted else "inconclusive",
                                    "evidence": str(reason)[:1500], "criteria": outcome.get("criteria", [])[:5] if isinstance(outcome, dict) else []}
        return accepted

    @staticmethod
    def _memory_action(parsed_action: dict) -> str:
        """Serialize an action without persisting typed or intervention text."""
        safe_action = dict(parsed_action)
        if safe_action.get("tool_name") == "type":
            typed = safe_action.pop("text", "")
            safe_action["characters"] = len(typed) if isinstance(typed, str) else 0
        elif safe_action.get("tool_name") == "click_and_type":
            typed = safe_action.pop("text", "")
            safe_action["characters"] = len(typed) if isinstance(typed, str) else 0
        elif safe_action.get("tool_name") == "compound_action":
            safe_subs = []
            for sub in safe_action.get("actions", []):
                if isinstance(sub, dict):
                    s_sub = dict(sub)
                    if "text" in s_sub:
                        t = s_sub.pop("text", "")
                        s_sub["characters"] = len(t) if isinstance(t, str) else 0
                    safe_subs.append(s_sub)
            safe_action["actions"] = safe_subs
        if safe_action.get("tool_name") == "hitl_intervention":
            safe_action.pop("question", None)
        return json.dumps(safe_action, ensure_ascii=False)

    @staticmethod
    def _display_action(parsed_action: dict) -> str:
        """Describe an action without exposing typed or intervention content."""
        tool_name = str(parsed_action.get("tool_name") or "action")
        if tool_name == "type":
            text = parsed_action.get("text")
            length = len(text) if isinstance(text, str) else 0
            return f"Enter {length} character{'s' if length != 1 else ''}"
        if tool_name == "click_and_type":
            target = str(parsed_action.get("element") or "input")[:80]
            text = parsed_action.get("text")
            length = len(text) if isinstance(text, str) else 0
            submit_str = " (+Enter)" if parsed_action.get("submit") else ""
            return f"Type {length} chars into '{target}'{submit_str}"
        if tool_name == "compound_action":
            actions = parsed_action.get("actions", [])
            count = len(actions) if isinstance(actions, list) else 0
            sub_desps = []
            for act in (actions or [])[:3]:
                if isinstance(act, dict):
                    tn = act.get("tool_name", "")
                    if tn in {"click", "double_click", "right_click"}:
                        sub_desps.append(f"Click '{str(act.get('element', 'target'))[:20]}'")
                    elif tn == "type":
                        sub_desps.append(f"Type ({len(str(act.get('text', '')))}c)")
                    elif tn == "key_press":
                        sub_desps.append(f"Key '{act.get('key', '')}'")
                    else:
                        sub_desps.append(tn)
            summary = " -> ".join(sub_desps)
            return f"Compound ({count}): {summary}" if summary else f"Compound ({count} actions)"
        if tool_name == "hitl_intervention":
            return "Wait for operator input"
        if tool_name in {"click", "double_click", "right_click", "move"}:
            target = str(parsed_action.get("element") or "visible control")[:160]
            search_result = re.fullmatch(
                r"open button for (.+?) app in (?:the )?search results?",
                target,
                flags=re.IGNORECASE,
            )
            if search_result and tool_name in {"click", "double_click"}:
                return f"Open {search_result.group(1).strip()} from search results"
            verbs = {"click": "Use", "double_click": "Open", "right_click": "Options for", "move": "Point to"}
            return f"{verbs[tool_name]} · {target}"
        if tool_name == "drag":
            source = str(parsed_action.get("source_element") or "source")[:80]
            target = str(parsed_action.get("target_element") or "target")[:80]
            return f"Drag · {source} to {target}"
        if tool_name == "key_press":
            return f"Use key · {str(parsed_action.get('key') or 'key')[:64]}"
        if tool_name == "switch_to_app":
            return f"Bring forward · {str(parsed_action.get('app_title') or 'window')[:120]}"
        if tool_name == "open_app":
            return f"Open · {str(parsed_action.get('app_name') or 'application')[:80]}"
        if tool_name == "wait":
            return f"Wait · {int(parsed_action.get('duration') or 1)}s"
        if tool_name == "terminate":
            return "Finish task"
        return tool_name.replace("_", " ").title()


    def _notify(self, status: str, detail: str = ""):
        """Notify listeners of status changes."""
        if self.on_status_change:
            try:
                self.on_status_change(status, detail)
            except Exception as e:
                logger.debug("on_status_change callback failed: %s", e)

    def _record_timing(self, phase: str, duration_ms: int):
        """Record per-phase execution timing."""
        if self.on_timing_update:
            try:
                self.on_timing_update(phase, max(0, int(duration_ms)))
            except Exception as e:
                logger.debug("on_timing_update callback failed: %s", e)

    def _notify_critic(self, step_num: int, eval_state: str, reason: str, improved_prompt: str = ""):
        """Notify listeners of critic evaluation results without direct GUI coupling."""
        if self.on_critic_update:
            try:
                self.on_critic_update({
                    "step": step_num,
                    "status": eval_state,
                    "reason": reason,
                    "improved_prompt": improved_prompt
                })
            except Exception as e:
                logger.debug("on_critic_update callback failed: %s", e)

    @staticmethod
    def _is_test_environment() -> bool:
        """Keep automated tests hermetic: never inspect the operator's desktop."""
        return "unittest" in sys.modules or "pytest" in sys.modules

    @staticmethod
    def _required_action_evidence(task: str) -> set[str]:
        """Infer only action requirements that can be checked without a model."""
        normalized = " ".join(str(task or "").lower().split())
        required = set()
        if re.search(r"\b(type|write|compose|fill in|enter text|reply with)\b", normalized):
            required.add("type")
        return required

    def _dynamic_step_budget(self, task: str, ceiling: int | None = None) -> int:
        """Scale the action budget to the reviewed plan's observable work.

        Holo deliberately takes small screen-grounded actions. A fixed 15-step
        cutoff penalizes that safer behaviour, while an unbounded loop hides
        stagnation. Each explicit plan item receives six actions plus a small
        recovery reserve, capped by the configured hard safety ceiling.
        """
        configured_ceiling = max(1, int(getattr(self.config.safety, "max_steps_per_task", 60))) if getattr(self, "config", None) and getattr(self.config, "safety", None) else 60
        hard_ceiling = configured_ceiling if ceiling is None else min(configured_ceiling, max(1, int(ceiling)))
        numbered = re.findall(r"(?m)^\s*(?:\d+[.)]|[-*])\s+\S", str(task or ""))
        plan_items = max(1, len(numbered))
        derived = plan_items * 6 + 6
        return min(hard_ceiling, derived)

    def resolve_step_budget(self, task: str, requested_steps: int | None = None) -> int:
        """Resolve the active step limit for a task execution.

        If an explicit step limit is requested (from the user UI or planner),
        respect it directly up to the safety ceiling. Otherwise, scale dynamically based
        on the reviewed plan items.
        """
        configured_ceiling = max(1, int(getattr(self.config.safety, "max_steps_per_task", 60))) if getattr(self, "config", None) and getattr(self.config, "safety", None) else 60
        if requested_steps is not None:
            try:
                user_requested = max(1, int(requested_steps))
                return min(configured_ceiling, user_requested)
            except (TypeError, ValueError):
                pass
        return self._dynamic_step_budget(task, configured_ceiling)

    @staticmethod
    def _tool_observation(vlm_result: dict, tool_name: str, detail: str, success: bool) -> dict:
        """Return a provider-native tool response for the next reasoning turn."""
        call_id = str(vlm_result.get("tool_call_id") or "desktop-action")
        content = json.dumps(
            {"success": bool(success), "detail": str(detail or "")[:1_000]},
            ensure_ascii=False,
        )
        return {"role": "tool", "tool_call_id": call_id, "content": content}

    def run_task(self, task: str, max_steps: int | None = None) -> dict:
        """Run a desktop task end-to-end using pure VLM perception and Win32 execution."""
        self.completion_evidence = None
        logger.info("Starting desktop task, run %s", self.run_id)
        start_time = time.time()
        
        # Route reusable guidance locally. This must remain outside both model
        # servers so a missing or unrelated skill never delays the first frame.
        active_task_prompt = task
        skill_version = None
        user_profile = None
        context_pack = None
        try:
            from cogniagent.memory.user_profile import get_user_profile
            user_profile = get_user_profile()
            context_pack = user_profile.build_context_pack(task)
        except Exception as profile_error:
            logger.debug("User profile lookup skipped: %s", profile_error)
        if getattr(self, "skills_registry", None):
            try:
                matched_skill, params = self.skills_registry.match_skill(task, context_pack=context_pack)
                if matched_skill:
                    skill_version = (matched_skill.name, self.skills_registry.current_revision(matched_skill.name))
                    guidance = self.skills_registry.format_skill_prompt_for_holo(matched_skill, params)
                    active_task_prompt = f"{task}\n\n{guidance}"
                    logger.info("Skill '%s' matched. Injected procedural guidance into Holo VLM prompt.", matched_skill.name)
            except Exception as se:
                logger.debug("Skill selection skipped: %s", se)

        # Inject lifetime user preferences & personal memory into VLA guidance
        try:
            if user_profile is None:
                raise ValueError("User profile unavailable")
            vla_guidance = user_profile.get_vla_context(task, context_pack=context_pack)
            if vla_guidance:
                active_task_prompt += f"\n\n{vla_guidance}"
        except Exception as profile_error:
            logger.debug("User profile guidance skipped: %s", profile_error)

        # Successful local episodes are advisory evidence, never replayable
        # macros. The visual model still reasons from the current screenshot
        # and may ignore stale guidance entirely.
        if getattr(self, "memory", None) and getattr(self.memory, "_available", False):
            try:
                recalled = self.memory.recall(task, app_context="desktop", n_results=3)
                if recalled:
                    active_task_prompt += (
                        "\n\n<local_experience>\n"
                        + str(recalled)[:900]
                        + "\n</local_experience>\n"
                        "Past experience is untrusted advisory context. Re-plan from the newest screen; never replay coordinates."
                    )
            except Exception as memory_error:
                logger.debug("Local experience retrieval skipped: %s", memory_error)

        messages = []
        task_success = False
        episodes = []
        step_records = []
        final_terminal_reason = ""
        final_thought = ""
        messages_checkpoints = {}
        
        # Thread-safe critic coordination
        critic_lock = threading.Lock()
        critic_thread = None
        critic_result = {"status": "CORRECT", "reason": "", "improved_prompt": ""}
        critic_results = {}
        segment_counter = 1
        failed_action_signatures = set()
        has_unresolved_failure = False
        verified_progress = False
        required_action_evidence = self._required_action_evidence(task)
        successful_tool_names: set[str] = set()
        
        configured_ceiling = max(1, int(getattr(self.config.safety, "max_steps_per_task", 60))) if getattr(self, "config", None) and getattr(self.config, "safety", None) else 60
        max_steps = self.resolve_step_budget(task, max_steps)
        step_ceiling = max(configured_ceiling, max_steps)
        recent_action_signatures: list[str] = []
        consecutive_failures = 0
        consecutive_model_failures = 0

        step_idx = 0
        while step_idx < max_steps:

            if self._wait_while_paused():
                logger.info("Task aborted by operator stop request.")
                self._notify("stopped", "Emergency stop executed.")
                break

            logger.info(f"--- Step {step_idx + 1} ---")
            step_started_at = time.time()
            
            # Check previous step's critic result
            if step_idx > 0 and critic_thread:
                # Wait up to 1.5s for the background critic to complete
                critic_thread.join(timeout=1.5)
                with critic_lock:
                    current_critic = dict(critic_result)
                
                self._notify_critic(
                    step_num=step_idx,
                    eval_state=current_critic.get("status", "CORRECT"),
                    reason=current_critic.get("reason", "Action verified."),
                    improved_prompt=current_critic.get("improved_prompt", "")
                )
                
                if current_critic.get("status") == "STRAYING" and (step_idx - 1) in messages_checkpoints:
                    logger.warning("Parallel Critic flagged previous step as STRAYING. Backtracking.")
                    messages = copy.deepcopy(messages_checkpoints[step_idx - 1])
                    improved_prompt = current_critic.get("improved_prompt", "Please correct your action.")
                    segment_counter += 1
                    messages.append({
                        "role": "user",
                        "content": (
                            f"Warning: The critic detected that the previous step failed or went off-track.\n"
                            f"Original plan target: {task}\n"
                            f"Feedback / Error details: {improved_prompt}\n"
                            f"Please adapt your plan, correct this action, and proceed."
                        )
                    })
            
            # Store lightweight text context checkpoint for single-step backtrack
            messages_checkpoints[step_idx] = checkpoint_execution_context(messages)
            for stale_step in list(messages_checkpoints):
                if stale_step < step_idx - 2:
                    del messages_checkpoints[stale_step]
            
            if self._should_stop():
                logger.info("Task aborted before VLM call.")
                self._notify("stopped", "Emergency stop executed.")
                break

            self._notify("thinking", "Reading the screen")
            
            # Perceive and Reason with VLM using guided prompt
            vlm_start = time.time()
            vlm_result = self.vlm.reason(active_task_prompt, messages)
            vlm_duration = time.time() - vlm_start
            self._record_timing("model", int(vlm_duration * 1000))

            if self._should_stop():
                logger.info("Task aborted after VLM call.")
                self._notify("stopped", "Emergency stop executed.")
                break


            
            if not vlm_result:
                consecutive_model_failures += 1
                logger.error("VLM failed to return a response.")
                if consecutive_model_failures >= 2:
                    self._notify("error", "The local model ran out of inference memory. Execution stopped safely.")
                    break
                if step_idx > 0:
                    critic_result = self.verify_action_with_critic(task, {}, error_msg="VLM failed to return response or returned invalid JSON.")
                    self._notify_critic(
                        step_num=step_idx + 1,
                        eval_state="STRAYING",
                        reason="VLM failed to generate a valid response.",
                        improved_prompt=critic_result.get("improved_prompt", "")
                    )
                    messages = copy.deepcopy(messages_checkpoints[step_idx])
                    messages.append({
                        "role": "user",
                        "content": f"Warning: The previous reasoning failed or returned invalid JSON format. Feedback: {critic_result.get('improved_prompt')}"
                    })
                    time.sleep(0.5)
                    step_idx += 1
                    continue
                else:
                    self._notify("error", "VLM returned no response")
                    break
            consecutive_model_failures = 0

            action_desp = vlm_result.get("action_desp", "")
            action_call = vlm_result.get("action_call", "")
            parsed_action = vlm_result.get("parsed_action", {})
            if not isinstance(parsed_action, dict):
                parsed_action = {}
            
            # Structural review is deterministic and effectively immediate;
            # running it in a thread created needless state races between steps.
            review = self.verify_action_with_critic(task, vlm_result)
            with critic_lock:
                critic_result = review
                critic_results[step_idx + 1] = review
            critic_thread = None
            self._notify_critic(
                step_idx + 1,
                review.get("status", "CORRECT"),
                review.get("reason", "Action verified."),
                review.get("improved_prompt", ""),
            )
 
            # UI surfaces receive a short, privacy-safe action label. Model
            # scratch text remains in the execution loop and is never exposed
            # as product copy.
            self._notify("acting", self._display_action(parsed_action))
            logger.info(f"[Timing] VLM Inference Step {step_idx + 1} took {vlm_duration:.2f} seconds")

            # Execute via Native Win32 Router
            orig_dims = vlm_result.get("orig_dims")
            exec_start = time.time()
            action_signature = self.executor.action_signature(vlm_result)
            completion_status = parsed_action.get("status") if action_desp == "terminate" else None

            if self._wait_while_paused():
                logger.info("Task aborted before action execution.")
                self._notify("stopped", "Emergency stop executed.")
                break

            action_risk = None
            if parsed_action.get("tool_name") in {"click", "double_click", "right_click", "drag", "type", "click_and_type", "compound_action", "key_press"}:
                action_risk = self.executor.assess_action_risk(parsed_action)
            if action_risk and self.action_policy.get("mode", "supervised") == "supervised":
                reasons = ", ".join(action_risk["reasons"])
                is_auth_risk = "authentication or verification code" in action_risk.get("reasons", []) and parsed_action.get("tool_name") in {"type", "click_and_type"}
                if is_auth_risk:
                    question = (
                        f"Verification code required for ‘{action_risk['target']}’. "
                        "Please enter the OTP / verification code (or reply Deny):"
                    )
                else:
                    question = (
                        f"Approve this just-in-time action? {action_desp} on "
                        f"‘{action_risk['target']}’ ({reasons}). Reply Approve to continue or Deny to block it."
                    )
                logger.info("High-impact action paused for just-in-time approval: %s", reasons)
                response = self._ask("secret" if is_auth_risk else "approval", question, parsed_action)
                clean_response = str(response or "").strip()
                denied_words = {"deny", "denied", "stop", "cancel", "no"}
                if (not clean_response or clean_response.casefold() in denied_words or (not is_auth_risk and clean_response != "approve") or (is_auth_risk and (clean_response.casefold() in {"approve", "approved", "yes", "continue"} or not re.fullmatch(r"[A-Za-z0-9 -]{4,32}", clean_response)))):
                    result = {
                        "success": False,
                        "detail": "High-impact action denied or not explicitly approved by the operator.",
                        "is_done": False,
                    }
                    exec_time = int((time.time() - exec_start) * 1000)
                else:
                    if is_auth_risk and clean_response.casefold() not in {"approve", "approved", "yes", "continue"}:
                        if parsed_action.get("tool_name") in {"type", "click_and_type"}:
                            parsed_action["text"] = clean_response
                            if isinstance(vlm_result.get("parsed_action"), dict):
                                vlm_result["parsed_action"]["text"] = clean_response
                    if vlm_result.get("captured_at") and vlm_result.get("focus_context") and not self._should_stop():
                        from cogniagent.execution import win32_input
                        # Operator controls can take focus. Restore only the exact observed process/window,
                        # then compare a new frame before dispatching any approved input.
                        with win32_input.cancellation_scope(self._should_stop):
                            win32_input.restore_observed_focus(vlm_result["focus_context"], vlm_result.get("foreground_pid", 0))
                    result = self._dispatch(vlm_result, orig_dims)
                    exec_time = int((time.time() - exec_start) * 1000)

            elif (
                action_desp == "terminate"
                and completion_status == "success"
                and required_action_evidence - successful_tool_names
            ):
                missing = ", ".join(sorted(required_action_evidence - successful_tool_names))
                result = {
                    "success": False,
                    "detail": f"Completion blocked: the approved plan still requires a verified {missing} action.",
                    "is_done": False,
                }
                exec_time = int((time.time() - exec_start) * 1000)
            elif action_desp == "terminate" and completion_status == "success" and has_unresolved_failure:
                result = {"success": False, "is_done": True, "detail": "Completion blocked: an action is still failed or unverified."}
                exec_time = int((time.time() - exec_start) * 1000)
            elif action_desp == "terminate" and completion_status == "success":
                verified = self._verify_completion(task, vlm_result)
                result = {"success": verified, "is_done": True, "detail": "Outcome independently verified." if verified else "The requested outcome was not verified."}
                exec_time = int((time.time() - exec_start) * 1000)
            elif (
                self.config.safety.block_repeated_failed_actions
                and action_signature
                and action_signature in recent_action_signatures[-1:]
            ):
                result = {
                    "success": False,
                    "detail": "Repeated action blocked. The screen state must be re-evaluated and a different recovery action chosen.",
                    "is_done": False,
                }
                exec_time = int((time.time() - exec_start) * 1000)
            elif (
                self.config.safety.block_repeated_failed_actions
                and action_signature
                and action_signature in failed_action_signatures
            ):
                result = {
                    "success": False,
                    "detail": "Repeated action blocked after failed verification. Choose a different action or request human help.",
                    "is_done": False,
                }
                exec_time = int((time.time() - exec_start) * 1000)
            elif (
                action_signature
                and action_desp in {"click", "double_click", "right_click", "type", "click_and_type"}
                and recent_action_signatures.count(action_signature) >= 2
                and action_signature in recent_action_signatures[-8:]
            ):
                # Detect cycling loops: clicking or typing repeatedly across recent turns
                result = {
                    "success": False,
                    "detail": f"Cycle detected: you already performed this action ({action_desp} on target '{parsed_action.get('element', 'input')}') recently. Do NOT repeat it. Request human help via hitl_intervention or choose a different action.",
                    "is_done": False,
                }
                exec_time = int((time.time() - exec_start) * 1000)
            elif action_desp == "hitl_intervention":
                question = parsed_action.get("question", "Verification or input required.")
                logger.info(f"VLM requested Human Intervention: {question}")
                user_msg = self._ask("clarification", question, parsed_action)
                
                exec_time = int((time.time() - exec_start) * 1000)
                result = {
                    "success": True,
                    "detail": "Operator supplied a response.",
                    "is_done": False
                }
                user_msg_clean = str(user_msg or "").strip()
                if user_msg_clean and user_msg_clean.lower() not in {"no response", "stop", "exit", "quit"}:
                    messages.append({
                        "role": "user",
                        "content": f"Operator response to your question: {user_msg_clean}"
                    })
                    consecutive_failures = 0
                    has_unresolved_failure = False
            else:
                result = self._dispatch(vlm_result, orig_dims)
                exec_time = int((time.time() - exec_start) * 1000)

            self._record_timing("action", exec_time)
            if action_signature:
                recent_action_signatures.append(action_signature)
                del recent_action_signatures[:-10]

            if action_desp == "terminate" and not result.get("success", False):
                critic_results[step_idx + 1] = {
                    "status": "HITL",
                    "reason": result.get("detail", "Completion requires verification."),
                    "improved_prompt": "Verify the task outcome on screen or ask the operator for confirmation.",
                }
                self._notify_critic(step_idx + 1, "HITL", result.get("detail", "Completion requires verification."))
            
            logger.info(f"[Timing] Action Execution took {exec_time} ms")
            
            # Visual Outcome Verification
            verification_started_at = time.time()
            self._notify("verifying", "Checking screen outcome")
            if self.config.perception.visual_verification_enabled:
                time.sleep(0.5)
                after_img, _ = self.vlm.capture_screen(for_vlm=False)
                before_frame = np.array(vlm_result["screenshot"])
                after_frame = np.array(after_img)
                diff_result = self.verifier.compute_screen_diff(before_frame, after_frame)
            else:
                diff_result = {
                    "changed": True,
                    "diff_ratio": 1.0,
                    "description": "Visual verification disabled by configuration",
                }
            
            args_list = []
            if "text" in parsed_action:
                args_list = [parsed_action["text"]]
            elif "key" in parsed_action:
                args_list = [parsed_action["key"]]
            elif parsed_action.get("tool_name") == "click_and_type":
                args_list = [parsed_action.get("text", "")]
                
            curr_action = AgentAction(
                action_type=action_desp,
                thought=vlm_result.get("think", ""),
                args=args_list
            )
            
            self._record_timing("verification", int((time.time() - verification_started_at) * 1000))
            self._record_timing("step", int((time.time() - step_started_at) * 1000))
            
            if not result.get("success", False):
                failure_reason = result.get("detail", "Action execution was blocked or failed.")
            else:
                failure_reason = self.verifier.detect_failure(
                    diff_result,
                    action=curr_action,
                    execution_result=result,
                )
            stagnation_msg = "Warning: Action failed! Warning: The previous action had no effect. Please try a different action."
            
            if failure_reason:
                if failure_reason == "No visible screen change after action":
                    failure_msg = stagnation_msg
                else:
                    failure_msg = f"Warning: Action failed. {failure_reason}. Please try a different approach."
                logger.error(f"Action failed verification: {failure_reason}")
                messages.append(self._tool_observation(vlm_result, action_desp, failure_msg, False))
                if action_signature:
                    failed_action_signatures.add(action_signature)
                has_unresolved_failure = True
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    messages.append({
                        "role": "user",
                        "content": (
                            "Recovery required: several recent actions produced no verified progress. "
                            "Do not open or switch to the same application again. Inspect the visible application content, "
                            "then use a different interaction that advances the unfinished objective."
                        ),
                    })
            else:
                if action_desp not in {"wait", "get_open_apps", "terminate", "scroll", "hitl_intervention"}:
                    has_unresolved_failure = False
                    verified_progress = True
                    successful_tool_names.add(action_desp)
                    if action_desp == "click_and_type":
                        successful_tool_names.add("click")
                        successful_tool_names.add("type")
                    elif action_desp == "compound_action":
                        for sub in parsed_action.get("actions", [])[:1]:
                            if isinstance(sub, dict) and sub.get("tool_name"):
                                successful_tool_names.add(sub["tool_name"])
                tool_name = action_desp or "unknown"
                detail = result.get("detail", "") if result else ""
                messages.append(self._tool_observation(vlm_result, tool_name, detail, True))
                consecutive_failures = 0
            
            # Store in Episodic Memory
            ep = Episode(
                task=task,
                app_context="desktop",
                goal=action_desp,
                action_type=action_desp,
                action_args=[self._memory_action(parsed_action)],
                action_method="vlm_router",
                success=bool(result.get("success") and not failure_reason),
                state_summary="VLM screenshot captured",
                outcome=result["detail"] if result else "",
                timestamp=time.time(),
                execution_time_ms=exec_time,
                retry_count=0
            )
            self.memory.store(ep)
            episodes.append(ep)
            
            # Step complete callback
            if self.on_step_complete:
                c_res = critic_results.get(step_idx + 1)
                eval_state = "STRAYING" if failure_reason else (c_res.get("status", "CORRECT") if c_res else "EVALUATING")
                critic_reason = failure_reason or (c_res.get("reason", "") if c_res else "")
                
                step_screenshot_b64 = ""
                if vlm_result and vlm_result.get("screenshot"):
                    try:
                        s_img = (after_img if self.config.perception.visual_verification_enabled else vlm_result["screenshot"]).copy()
                        if s_img.width > 360 or s_img.height > 220:
                            s_img.thumbnail((360, 220), Image.Resampling.BILINEAR)
                        buf = BytesIO()
                        s_img.save(buf, format="JPEG", quality=60)
                        step_screenshot_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                    except Exception:
                        pass

                display_action = self._display_action(parsed_action)
                try:
                    self.on_step_complete({
                        "step": step_idx + 1,
                        "thought": vlm_result.get("think", "") if vlm_result else "",
                        "action": action_desp,
                        "action_text": display_action,
                        "output": result.get("detail", "") if result else "",
                        "success": bool(result and result.get("success", False) and not failure_reason),
                        "segment_id": segment_counter,
                        "eval_state": eval_state,
                        "critic_reason": critic_reason,
                        "screenshot_b64": step_screenshot_b64
                    })
                except Exception as e:
                    logger.debug("on_step_complete callback failed: %s", e)

            step_records.append({
                "step": step_idx + 1,
                "thought": vlm_result.get("think", "") if vlm_result else "",
                "action": action_desp,
                "action_text": self._display_action(parsed_action),
                "note": vlm_result.get("note", "") if vlm_result else "",
                "reason": parsed_action.get("reason", "") if parsed_action.get("tool_name") == "terminate" else ""
            })
            if vlm_result and vlm_result.get("think"):
                final_thought = vlm_result.get("think")
            if parsed_action.get("tool_name") == "terminate":
                final_terminal_reason = parsed_action.get("reason", "")
            
            if result.get("is_done"):
                task_success = bool(result.get("success") and not failure_reason)
                logger.info(f"Task concluded: {result['detail']}")
                self._notify("done" if task_success else "failed", result["detail"])
                break
            
            # The planner owns the budget. A new reviewed plan is required to extend it.
            if step_idx + 1 >= max_steps and not result.get("is_done"):
                self._notify("failed", "The planner's budget was exhausted. Review a revised plan to continue.")
                final_terminal_reason = "Planner budget exhausted; no further input dispatched."
                break

            time.sleep(0.05)
            step_idx += 1
            
        total_time = int((time.time() - start_time) * 1000)
        if skill_version:
            try:
                self.skills_registry.record_outcome(*skill_version, self.run_id, task_success, total_time,
                                                    len(step_records), (self.completion_evidence or {}).get("source", "inconclusive"))
            except Exception as error:
                logger.warning("Skill outcome could not be recorded: %s", error)
        
        if task_success and len(episodes) > 0:
            traj = Trajectory(
                task=task,
                episodes=episodes,
                total_time_ms=total_time,
                success=True,
                app_sequence=[]
            )
            self.memory.store_trajectory(traj)
            
        return {
            "status": "success" if task_success else "failed",
            "episodes": len(episodes),
            "total_time_ms": total_time,
            "steps": step_records,
            "terminal_reason": final_terminal_reason,
            "final_thought": final_thought,
            "completion_evidence": self.completion_evidence,
            "skill_version": {"name": skill_version[0], "revision": skill_version[1]} if skill_version else None,
        }


    def verify_action_with_critic(self, task: str, vlm_result: dict, error_msg: str = None) -> dict:
        """Perform a bounded structural review without launching another model request.

        The CPU model is reserved for planning. Running a 4B critic after every
        screenshot saturated memory bandwidth, regularly outlived its HTTP
        timeout, and slowed the next visual step. Screen-difference verification,
        action-schema validation, repeat blocking, and risk gates remain the
        authoritative execution checks.
        """
        if error_msg:
            return {
                "status": "STRAYING",
                "reason": str(error_msg)[:1_000],
                "improved_prompt": "Inspect a fresh screenshot and choose a different visible, schema-valid action.",
            }
        parsed_action = vlm_result.get("parsed_action") if isinstance(vlm_result, dict) else None
        if not isinstance(parsed_action, dict) or not parsed_action.get("tool_name"):
            return {
                "status": "STRAYING",
                "reason": "The proposed action is missing a validated tool call.",
                "improved_prompt": "Return one complete action that matches the JSON contract.",
            }
        if parsed_action.get("tool_name") == "hitl_intervention":
            return {"status": "HITL", "reason": "Operator input is required.", "improved_prompt": ""}
        return {"status": "CORRECT", "reason": "Action passed structural and policy checks.", "improved_prompt": ""}
