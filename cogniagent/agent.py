import logging
import sys
import time
import threading
import numpy as np

from cogniagent.config import config
from cogniagent.perception.vlm_engine import VLMEngine
from cogniagent.execution.router import ActionRouter
from cogniagent.memory.episodic_memory import EpisodicMemory, Episode, Trajectory
from cogniagent.perception.verification import ScreenVerifier
from cogniagent.perception.uia_grounding import UIAutomationGrounder

logger = logging.getLogger(__name__)


class CogniAgent:
    """Holo3 VLM agent for multi-step tasks."""
    
    def __init__(self):
        self.config = config
        self.vlm = VLMEngine()
        self.executor = ActionRouter(config)
        self.memory = EpisodicMemory(config)
        self.verifier = ScreenVerifier(config.perception.max_visual_diff_pixels)
        self.grounder = UIAutomationGrounder(config.perception.max_elements)
        # Callback for UI status updates
        self.on_status_change = None
        self._last_semantic_state = None

    def _notify(self, status: str, detail: str = ""):
        """Notify the UI of status changes."""
        if self.on_status_change:
            self.on_status_change(status, detail)

    @staticmethod
    def _is_test_environment() -> bool:
        """Keep automated tests hermetic: never inspect the operator's desktop."""
        return "unittest" in sys.modules or "pytest" in sys.modules

    def _capture_semantic_state(self):
        """Read UIA state when possible, with a safe empty fallback."""
        from cogniagent.perception.state import SemanticState

        if self._is_test_environment() or not self.config.safety.enable_uia_safety_grounding:
            return SemanticState()
        return self.grounder.capture_state()

    def _preflight_click(self, vlm_result: dict, original_dims: tuple) -> str | None:
        """Block only high-confidence visual/accessibility target mismatches."""
        if self._is_test_environment() or not self.config.safety.enable_uia_safety_grounding:
            return None
        action = vlm_result.get("parsed_action")
        if not isinstance(action, dict) or action.get("tool_name") != "click":
            return None
        coords, error = self.executor.resolve_click_coordinates(
            action,
            original_dims,
            vlm_result.get("screen_origin", (0, 0)),
        )
        if error or not coords:
            # The router gives the model-facing validation error.  UIA does
            # not need to duplicate it here.
            return None
        return self.grounder.validate_click_target(*coords, action.get("element"))

    def run_task(self, task: str, max_steps: int = 15) -> dict:
        """Run a task using Holo3 end-to-end."""
        logger.info(f"=== Starting Task: {task} ===")
        start_time = time.time()
        
        messages = []
        task_success = False
        episodes = []
        
        from cogniagent.reasoning.action_reasoner import AgentAction
        
        import copy
        messages_checkpoints = {}
        critic_thread = None
        critic_result = {"status": "CORRECT", "reason": "", "improved_prompt": ""}
        critic_results = {}
        segment_counter = 1
        failed_action_signatures = set()
        has_unresolved_failure = False
        verified_progress = False
        
        step_idx = 0
        while step_idx < max_steps:
            logger.info(f"--- Step {step_idx + 1} ---")
            
            # Check previous step's parallel critic result (non-blocking, short timeout)
            if step_idx > 0 and critic_thread:
                critic_thread.join(timeout=0.1)
                try:
                    from cogniagent.gui.app import agent_status
                    agent_status["critic_review"] = {
                        "status": critic_result.get("status", "CORRECT"),
                        "reason": critic_result.get("reason", "Action verified as optimal."),
                        "improved_prompt": critic_result.get("improved_prompt", "")
                    }
                    # Update the evaluated status in steps history
                    for step_item in reversed(agent_status["steps"]):
                        if step_item["step"] == step_idx:
                            step_item["eval_state"] = critic_result.get("status", "CORRECT")
                            step_item["critic_reason"] = critic_result.get("reason", "")
                            break
                except Exception:
                    pass
                if critic_result.get("status") == "STRAYING":
                    logger.warning(f"Parallel Critic flagged previous step as STRAYING. Backtracking.")
                    messages = copy.deepcopy(messages_checkpoints[step_idx - 1])
                    improved_prompt = critic_result.get("improved_prompt", "Please correct your action.")
                    # Advance to a new prompt segments identifier
                    segment_counter += 1
                    messages.append({
                        "role": "user",
                        "content": (
                            f"Warning: The critic has detected that the previous step failed or went off-track.\n"
                            f"Original plan target: {task}\n"
                            f"Feedback / Error details: {improved_prompt}\n"
                            f"Please adapt your plan, correct this action, and proceed."
                        )
                    })
            
            messages_checkpoints[step_idx] = copy.deepcopy(messages)
            self._notify("thinking", f"Step {step_idx + 1}")
            
            # Perceive and Reason
            vlm_start = time.time()
            copy_messages = copy.deepcopy(messages)
            vlm_result = self.vlm.reason(task, copy_messages)
            messages.clear()
            messages.extend(copy_messages)
            vlm_duration = time.time() - vlm_start
            
            if not vlm_result:
                logger.error("VLM failed to return a response.")
                if step_idx > 0:
                    critic_result = self.verify_action_with_critic(task, {}, error_msg="VLM failed to return response or returned invalid JSON.")
                    try:
                        from cogniagent.gui.app import agent_status
                        agent_status["critic_review"] = {
                            "status": "STRAYING",
                            "reason": "VLM failed to generate a response or returned invalid JSON.",
                            "improved_prompt": critic_result.get("improved_prompt", "")
                        }
                    except Exception:
                        pass
                    messages = copy.deepcopy(messages_checkpoints[step_idx])
                    messages.append({
                        "role": "user",
                        "content": f"Warning: The previous reasoning failed or returned invalid JSON format. Feedback: {critic_result.get('improved_prompt')}"
                    })
                    time.sleep(1.0)
                    step_idx += 1
                    continue
                else:
                    self._notify("error", "VLM returned no response")
                    break
                
            action_desp = vlm_result.get("action_desp", "")
            action_call = vlm_result.get("action_call", "")
            parsed_action = vlm_result.get("parsed_action", {})
            if not isinstance(parsed_action, dict):
                parsed_action = {}
            
            # Reset critic result container and launch async thread
            critic_result = {"status": "EVALUATING", "reason": "Verification Critic is analyzing...", "improved_prompt": ""}
            try:
                from cogniagent.gui.app import agent_status
                agent_status["critic_review"] = {
                    "status": "EVALUATING",
                    "reason": "Verification Critic is analyzing action and reasoning...",
                    "improved_prompt": ""
                }
            except Exception:
                pass
            
            def run_critic_async(t_goal, v_res, current_step_num):
                nonlocal critic_result, critic_results
                critic_result = self.verify_action_with_critic(t_goal, v_res)
                critic_results[current_step_num] = critic_result
                try:
                    from cogniagent.gui.app import agent_status
                    agent_status["critic_review"] = {
                        "status": critic_result.get("status", "CORRECT"),
                        "reason": critic_result.get("reason", "Action verified as optimal."),
                        "improved_prompt": critic_result.get("improved_prompt", "")
                    }
                    for step_item in reversed(agent_status["steps"]):
                        if step_item["step"] == current_step_num:
                            step_item["eval_state"] = critic_result.get("status", "CORRECT")
                            step_item["critic_reason"] = critic_result.get("reason", "")
                            break
                except Exception:
                    pass
                
            critic_thread = None
            if action_desp != "hitl_intervention" and action_desp != "terminate":
                critic_thread = threading.Thread(target=run_critic_async, args=(task, vlm_result, step_idx + 1))
                critic_thread.daemon = True
                critic_thread.start()
            else:
                if action_desp == "terminate":
                    critic_results[step_idx + 1] = {"status": "CORRECT", "reason": "Task concluded successfully.", "improved_prompt": ""}
                    try:
                        from cogniagent.gui.app import agent_status
                        agent_status["critic_review"] = {
                            "status": "CORRECT",
                            "reason": "Task concluded successfully.",
                            "improved_prompt": ""
                        }
                    except Exception:
                        pass
                elif action_desp == "hitl_intervention":
                    critic_results[step_idx + 1] = {"status": "HITL", "reason": "Human intervention required.", "improved_prompt": ""}
                    try:
                        from cogniagent.gui.app import agent_status
                        agent_status["critic_review"] = {
                            "status": "HITL",
                            "reason": "Human intervention required.",
                            "improved_prompt": ""
                        }
                    except Exception:
                        pass
 
            self._notify("acting", f"{action_desp}|{vlm_result.get('think', '')}")
            logger.info(f"[Timing] VLM Inference Step {step_idx + 1} took {vlm_duration:.2f} seconds")
            
            # Capture semantic state before the input is issued.  If UIA is
            # unavailable, the verifier simply falls back to screenshot-based
            # evidence rather than inventing a state change.
            old_state = self._last_semantic_state or self._capture_semantic_state()

            # Execute
            orig_dims = vlm_result.get("orig_dims")
            exec_start = time.time()
            action_signature = self.executor.action_signature(vlm_result)
            completion_status = parsed_action.get("status") if action_desp == "terminate" else None
            preflight_reason = self._preflight_click(vlm_result, orig_dims)

            if (
                action_desp == "terminate"
                and completion_status == "success"
                and self.config.safety.require_verified_progress_for_success
                and (has_unresolved_failure or not verified_progress)
            ):
                reason = (
                    "Completion blocked: a prior action is still unverified or failed."
                    if has_unresolved_failure
                    else "Completion blocked: no verified task progress was observed."
                )
                result = {"success": False, "detail": reason, "is_done": True}
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
            elif preflight_reason:
                result = {
                    "success": False,
                    "detail": f"Click blocked before execution. {preflight_reason}",
                    "is_done": False,
                }
                exec_time = int((time.time() - exec_start) * 1000)
            elif action_desp == "hitl_intervention":
                question = parsed_action.get("question", "Verification or input required.")
                logger.info(f"VLM requested Human Intervention: {question}")
                self._notify("hitl", question)
                
                # Block thread until UI submits a response
                user_msg = "No response"
                if hasattr(self, "wait_for_hitl_response") and self.wait_for_hitl_response:
                    user_msg = self.wait_for_hitl_response()
                
                exec_time = int((time.time() - exec_start) * 1000)
                result = {
                    "success": True,
                    "detail": f"Human responded: {user_msg}",
                    "is_done": False
                }
            else:
                result = self.executor.execute_vlm_action(vlm_result, orig_dims)
                exec_time = int((time.time() - exec_start) * 1000)

            if action_desp == "terminate" and not result.get("success", False):
                # Do not present a blocked completion as a successful critic
                # review in the command center.
                critic_results[step_idx + 1] = {
                    "status": "HITL",
                    "reason": result.get("detail", "Completion requires verification."),
                    "improved_prompt": "Verify the task outcome on screen or ask the operator for confirmation.",
                }
                try:
                    from cogniagent.gui.app import agent_status
                    agent_status["critic_review"] = critic_results[step_idx + 1]
                except Exception:
                    pass
            
            logger.info(f"[Timing] Action Execution took {exec_time} ms")
            
            # This verifier was part of the original action loop. Keep it
            # optional for constrained local deployments and use its bounded
            # sampler when enabled.
            if self.config.perception.visual_verification_enabled:
                time.sleep(1.0)
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
            
            # Build current agent action representation for semantic verification
            args_list = []
            if "text" in parsed_action:
                args_list = [parsed_action["text"]]
            elif "key" in parsed_action:
                args_list = [parsed_action["key"]]
                
            curr_action = AgentAction(
                action_type=action_desp,
                thought=vlm_result.get("think", ""),
                args=args_list
            )
            injected_state = getattr(self, "next_mock_state", None)
            new_state = injected_state or self._capture_semantic_state()
            self._last_semantic_state = new_state
            
            if hasattr(self, "next_mock_state"):
                self.next_mock_state = None
            
            if not result.get("success", False):
                failure_reason = result.get("detail", "Action execution was blocked or failed.")
            else:
                failure_reason = self.verifier.detect_failure(diff_result, old_state, new_state, curr_action)
            stagnation_msg = "Warning: Action failed! Warning: The previous action had no effect. Please try a different action."
            
            if failure_reason:
                failure_msg = None
                if failure_reason:
                    if failure_reason == "No visible screen change after action":
                        failure_msg = stagnation_msg
                    else:
                        failure_msg = f"Warning: Action failed. {failure_reason}. Please try a different approach."
                    logger.error(f"Action failed semantically: {failure_reason}")
                    messages.append({
                        "role": "user",
                        "content": failure_msg,
                    })
                if action_signature:
                    failed_action_signatures.add(action_signature)
                has_unresolved_failure = True
            else:
                # Passive inspection/waiting does not resolve a failed action;
                # only a different verified interaction or a human response can
                # restore the completion path.
                if action_desp not in {"wait", "get_open_apps", "terminate"}:
                    has_unresolved_failure = False
                    verified_progress = True
                # Wrap successful tool output in observation tags for the VLM's next step context
                tool_name = action_desp or "unknown"
                detail = result.get("detail", "") if result else ""
                observation_text = f'<observation>\n<tool_output tool="{tool_name}">\n{detail}\n</tool_output>\n</observation>'
                messages.append({
                    "role": "user",
                    "content": observation_text
                })
            
            # Store in episode memory
            ep = Episode(
                task=task,
                app_context="unknown",
                goal=action_desp,
                action_type=action_desp,
                action_args=[action_call],
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
            
            # Step complete callback for Web UI
            if hasattr(self, "on_step_complete") and self.on_step_complete:
                c_res = critic_results.get(step_idx + 1)
                eval_state = c_res.get("status", "CORRECT") if c_res else "EVALUATING"
                critic_reason = c_res.get("reason", "") if c_res else ""
                self.on_step_complete({
                    "step": step_idx + 1,
                    "thought": vlm_result.get("think", "") if vlm_result else "",
                    "action": action_desp,
                    "output": result.get("detail", "") if result else "",
                    "success": result.get("success", False) if result else False,
                    "segment_id": segment_counter,
                    "eval_state": eval_state,
                    "critic_reason": critic_reason
                })
            
            if result.get("is_done"):
                task_success = bool(result.get("success") and not failure_reason)
                logger.info(f"Task concluded: {result['detail']}")
                self._notify("done" if task_success else "failed", result["detail"])
                break
            
            # If step limit reached and task is not done, request human intervention
            if step_idx + 1 >= max_steps and not result.get("is_done"):
                question = f"Task reached the limit of {max_steps} steps. Resolve any screen issues or captchas, then type new instruction or click Continue to run 15 more steps."
                logger.info(f"Task limit reached. Requesting Human Intervention: {question}")
                self._notify("hitl", question)
                
                user_msg = "stop"
                if hasattr(self, "wait_for_hitl_response") and self.wait_for_hitl_response:
                    user_msg = self.wait_for_hitl_response()
                
                if user_msg.lower() not in ["stop", "exit", "quit", "no"]:
                    max_steps += 15
                    try:
                        from cogniagent.gui.app import agent_status
                        agent_status["settings"]["max_steps"] = max_steps
                    except Exception:
                        pass
                    if user_msg.lower() not in ["continue", "done", "yes"]:
                        messages.append({
                            "role": "user",
                            "content": f"User intervention/instruction: {user_msg}"
                        })
                        segment_counter += 1
                else:
                    break
            
            time.sleep(0.1)  # sleep minimized for tests
            step_idx += 1
            
        total_time = int((time.time() - start_time) * 1000)
        
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
            "total_time_ms": total_time
        }

    def verify_action_with_critic(self, task: str, vlm_result: dict, error_msg: str = None) -> dict:
        """Query Qwen 3.5 (Planner) on port 8090 to check if VLM is straying."""
        import requests
        import sys
        import json
        
        is_testing = 'unittest' in sys.modules or 'pytest' in sys.modules
        if is_testing:
            return {"status": "CORRECT", "reason": "", "improved_prompt": ""}
            
        try:
            if error_msg:
                prompt = (
                    f"You are a Plan Verification Critic for a computer-use agent.\n"
                    f"The executor agent failed to generate a valid action or returned an invalid JSON response.\n"
                    f"Error details: {error_msg}\n"
                    f"User Goal: {task}\n\n"
                    f"Respond strictly in JSON format matching the schema:\n"
                    f'{{\n  "status": "STRAYING",\n  "reason": "description",\n  "improved_prompt": "clear instruction detailing exactly how the agent should proceed from the previous screen state"\n}}'
                )
            else:
                prompt = (
                    f"You are a Plan Verification Critic for a computer-use agent.\n"
                    f"Evaluate the proposed VLM action for correctness.\n"
                    f"User Goal: {task}\n"
                    f"VLM Thought: {vlm_result.get('think', '')}\n"
                    f"Proposed Tool Action: {vlm_result.get('action_desp', '')} ({vlm_result.get('parsed_action', '')})\n\n"
                    f"CRITICAL CONSTRAINT:\n"
                    f"- If the executor has repeatedly clicked or double-clicked an element, or triggered a rename bar/right-click menu without opening the file/folder, mark the status as STRAYING and devise an improved_prompt explicitly directing it to: 'Single-click the item at its coordinates to select it, then press the enter key to open it.'\n\n"
                    f"Decide if this action is CORRECT (logical next step), STRAYING (off-track, incorrect coordinate, or wrong direction), or HITL (requires human confirmation/input).\n\n"
                    f"Respond strictly in JSON format matching the schema:\n"
                    f'{{\n  "status": "CORRECT" | "STRAYING" | "HITL",\n  "reason": "explanation of the evaluation",\n  "improved_prompt": "if STRAYING, clear instruction to guide the executor back on track; otherwise empty string"\n}}'
                )
            payload = {
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,
                "max_tokens": 256,
                "response_format": {"type": "json_object"}
            }
            r = requests.post("http://127.0.0.1:8090/v1/chat/completions", json=payload, timeout=5)
            if r.status_code == 200:
                resp_data = r.json()["choices"][0]["message"]["content"]
                data = json.loads(resp_data)
                return {
                    "status": data.get("status", "CORRECT").upper(),
                    "reason": data.get("reason", ""),
                    "improved_prompt": data.get("improved_prompt", "")
                }
            return {"status": "CORRECT", "reason": "", "improved_prompt": ""}
        except Exception:
            return {"status": "CORRECT", "reason": "", "improved_prompt": ""}

