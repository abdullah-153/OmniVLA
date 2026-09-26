import time
import logging
import hashlib
import math
import re
from cogniagent.execution import win32_input

logger = logging.getLogger(__name__)

# Basic safety setup (replaces pyautogui configuration)
win32_input.enable_dpi_awareness()

class PauseRequested(RuntimeError):
    pass


class ActionRouter:
    """Routes VLM tool calls to Windows native system inputs using ctypes.
    
    Clean, simple execution — no retry hacks. The agent loop handles
    self-correction: if a click misses, the next screenshot shows it,
    and the model reasons about what to do differently.
    """
    
    def __init__(self, config):
        self.config = config
        self.check_cancelled = lambda: False
        self.check_paused = lambda: False

    def _guard(self):
        if self.check_cancelled():
            raise RuntimeError("Execution cancelled before input dispatch.")
        if self.check_paused():
            raise PauseRequested("Execution paused; obtain a fresh observation before continuing.")

    def _input(self, name, *args, **kwargs):
        self._guard()
        with win32_input.cancellation_scope(self.check_cancelled):
            return getattr(win32_input, name)(*args, **kwargs)

    def _sleep(self, duration):
        # Short slices bound Stop latency even during a wait tool.
        remaining = max(0, float(duration))
        while remaining > 0:
            self._guard()
            interval = min(0.05, remaining)
            time.sleep(interval)
            remaining -= interval

    @staticmethod
    def resolve_click_coordinates(action_data: dict, original_dims: tuple, screen_origin: object = (0, 0)) -> tuple[tuple[int, int] | None, str | None]:
        """Translate validated model coordinates into virtual-desktop pixels.

        Coordinates outside the model contract are rejected, never clamped to
        an edge.  Edge-clamping turned a malformed coordinate into a real click
        on an unrelated control, which is exactly the behaviour this execution
        layer must avoid.
        """
        if not isinstance(original_dims, tuple) or len(original_dims) != 2:
            return None, "Invalid source dimensions for action execution."
        orig_w, orig_h = original_dims
        if (
            isinstance(orig_w, bool)
            or isinstance(orig_h, bool)
            or not isinstance(orig_w, int)
            or not isinstance(orig_h, int)
            or orig_w <= 0
            or orig_h <= 0
        ):
            return None, "Source dimensions must be positive integers."
        if not isinstance(action_data, dict):
            return None, "Failed to parse action JSON from VLM."

        x_val = action_data.get("x")
        y_val = action_data.get("y")
        valid_coordinate = lambda value: (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and 0 <= value <= 1000
        )
        if not valid_coordinate(x_val) or not valid_coordinate(y_val):
            return None, "Click coordinates must be finite numbers in the range [0, 1000]."

        if (
            not isinstance(screen_origin, tuple)
            or len(screen_origin) != 2
            or any(isinstance(value, bool) or not isinstance(value, int) for value in screen_origin)
        ):
            return None, "Invalid screenshot origin for action execution."

        origin_x, origin_y = screen_origin
        # 1000 is a valid normalized endpoint and maps to the last pixel of the
        # captured monitor, not a coordinate one pixel beyond it.
        local_x = min(orig_w - 1, int((x_val / 1000.0) * orig_w))
        local_y = min(orig_h - 1, int((y_val / 1000.0) * orig_h))
        return (origin_x + local_x, origin_y + local_y), None

    @staticmethod
    def action_signature(vlm_result: dict) -> str | None:
        """Return a privacy-preserving signature used to block failed repeats."""
        action_data = vlm_result.get("parsed_action") if isinstance(vlm_result, dict) else None
        if not isinstance(action_data, dict):
            return None
        tool_name = action_data.get("tool_name")
        def coordinate_bucket(value):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return value
            return int(round(float(value) / 50.0) * 50)

        if tool_name in {"click", "double_click", "right_click", "move"}:
            label = action_data.get("element", "")
            if not isinstance(label, str):
                label = ""

            generic_words = {"button", "control", "icon", "in", "on", "taskbar", "the", "windows"}
            label_tokens = [
                token for token in re.findall(r"[a-z0-9]+", label.casefold())
                if token not in generic_words
            ]
            semantic_label = "-".join(label_tokens[:10]) or "visible-target"
            return (
                f"{tool_name}:{coordinate_bucket(action_data.get('x'))!r}:"
                f"{coordinate_bucket(action_data.get('y'))!r}:{semantic_label}"
            )
        if tool_name == "click_and_type":
            coords = f"{coordinate_bucket(action_data.get('x'))!r}:{coordinate_bucket(action_data.get('y'))!r}"
            text = action_data.get("text", "")
            digest = hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:16]
            return f"click_and_type:{coords}:{len(text)}:{digest}:{bool(action_data.get('submit', False))}"
        if tool_name == "compound_action":
            sub_signatures = []
            for sub in action_data.get("actions", []):
                if isinstance(sub, dict):
                    sub_sig = ActionRouter.action_signature({"parsed_action": sub})
                    if sub_sig:
                        sub_signatures.append(sub_sig)
            return ("compound:" + "+".join(sub_signatures)) if sub_signatures else None
        if tool_name == "drag":
            values = ("from_x", "from_y", "to_x", "to_y")
            return "drag:" + ":".join(repr(action_data.get(key)) for key in values)
        if tool_name == "type":
            text = action_data.get("text")
            if not isinstance(text, str):
                return None
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
            return f"type:{len(text)}:{digest}:{bool(action_data.get('submit', False))}"
        if tool_name == "key_press":
            key = action_data.get("key")
            return f"key:{key.strip().casefold()}" if isinstance(key, str) else None
        if tool_name == "scroll":
            direction = action_data.get("direction")
            return f"scroll:{direction}" if isinstance(direction, str) else None
        if tool_name == "open_app":
            app_name = action_data.get("app_name")
            return f"open-app:{app_name.strip().casefold()}" if isinstance(app_name, str) else None
        return None

    @staticmethod
    def is_dummy_verification_code(text: str, element_or_context: str = "") -> bool:
        """Detect if text being entered into an OTP/verification context is a known dummy/placeholder code."""
        cleaned_text = str(text or "").strip()
        cleaned_context = str(element_or_context or "").lower()
        is_auth_context = bool(re.search(
            r"\b(otp|one[- ]time|2fa|two[- ]factor|verification|security code|passcode|auth[- ]code|pin)\b",
            cleaned_context,
            re.IGNORECASE,
        ))
        dummy_patterns = {
            "123456", "000000", "111111", "1234", "12345", "12345678",
            "999999", "654321", "012345", "test", "demo", "sample",
        }
        if is_auth_context and (cleaned_text.lower() in dummy_patterns or bool(re.fullmatch(r"(.)\1{3,}", cleaned_text))):
            return True
        return False

    @staticmethod
    def assess_action_risk(action_data: dict) -> dict | None:
        """Identify visible controls that can create an external or destructive effect."""
        if not isinstance(action_data, dict):
            return None
        tool_name = action_data.get("tool_name")
        rules = (
            ("destructive change", r"\b(delete|remove|erase|trash|discard|overwrite|format|factory reset)\b"),
            ("external communication", r"\b(send|publish|post|share|upload|submit message)\b"),
            ("financial commitment", r"\b(pay|payment|purchase|buy|checkout|place order|transfer|confirm payment)\b"),
            ("access or security change", r"\b(allow|grant|permission|install|uninstall|reset password|disable security)\b"),
            ("authentication or verification code", r"\b(otp|one[- ]time password|2fa|two[- ]factor|verification code|security code|authenticator|auth code|login code|passcode)\b"),
        )
        if tool_name == "click_and_type":
            element = str(action_data.get("element") or "")
            text = str(action_data.get("text") or "")
            label = f"{element} {text}"
            reasons = [reason for reason, pattern in rules if re.search(pattern, label, re.I)]
            if reasons:
                return {"reasons": reasons, "target": label.strip()[:300], "tool_name": tool_name}
            return None
        if tool_name == "compound_action":
            all_reasons = []
            targets = []
            for sub in action_data.get("actions", []):
                if isinstance(sub, dict):
                    sub_risk = ActionRouter.assess_action_risk(sub)
                    if sub_risk:
                        all_reasons.extend(sub_risk.get("reasons", []))
                        targets.append(sub_risk.get("target", ""))
            if all_reasons:
                return {
                    "reasons": sorted(list(set(all_reasons))),
                    "target": " -> ".join(t for t in targets if t)[:300],
                    "tool_name": tool_name,
                }
            return None
        if tool_name == "key_press" and str(action_data.get("key", "")).lower().replace(" ", "") in {"enter", "return", "ctrl+enter", "alt+s"}:
            return {"reasons": ["potential submission or confirmation"], "target": "focused control", "tool_name": tool_name}
        if tool_name not in {"click", "double_click", "right_click", "drag", "type"}:
            return None
        label = " ".join(
            str(action_data.get(key) or "")
            for key in ("element", "source_element", "target_element", "text")
        )
        reasons = [reason for reason, pattern in rules if re.search(pattern, label, re.I)]
        if not reasons:
            return None
        return {"reasons": reasons, "target": label.strip()[:300], "tool_name": tool_name}

    def execute_vlm_action(self, vlm_result: dict, original_dims: tuple) -> dict:
        """Execute a tool_call generated by the Holo3 VLM."""
        logger.info(f"Executing VLM Action: {vlm_result.get('action_desp', '')}")
        
        results = []
        is_done = False
        success = True
        
        action_data = vlm_result.get("parsed_action")
        if not action_data or not isinstance(action_data, dict):
            return {
                "success": False,
                "detail": "Failed to parse action JSON from VLM.",
                "is_done": False
            }
            
        action_type = action_data.get("tool_name")
        
        try:
            if action_type in {"click", "double_click", "right_click", "move"}:
                focus_before = win32_input.get_focus_context()
                coords, coordinate_error = self.resolve_click_coordinates(
                    action_data,
                    original_dims,
                    vlm_result.get("screen_origin", (0, 0)),
                )
                element = action_data.get("element")
                if not isinstance(element, str) or not element.strip() or len(element) > 300:
                    success = False
                    results.append("Click action requires a concise target description.")
                elif coordinate_error:
                    success = False
                    results.append(coordinate_error)
                else:
                    x, y = coords
                    if action_type == "double_click":
                        self._input("mouse_double_click", x, y)
                        results.append(f"Double-clicked [{x}, {y}]")
                    elif action_type == "right_click":
                        self._input("mouse_click", x, y, button="right")
                        results.append(f"Right-clicked [{x}, {y}]")
                    elif action_type == "move":
                        self._input("smooth_move_to", x, y, duration=0.25)
                        results.append(f"Moved pointer to [{x}, {y}]")
                    else:
                        self._input("mouse_click", x, y)
                        results.append(f"Clicked [{x}, {y}]")
                    self._sleep(self.config.execution.click_pause)
                    focus_after = win32_input.get_focus_context()

            elif action_type == "drag":
                start, start_error = self.resolve_click_coordinates(
                    {"x": action_data.get("from_x"), "y": action_data.get("from_y")},
                    original_dims,
                    vlm_result.get("screen_origin", (0, 0)),
                )
                end, end_error = self.resolve_click_coordinates(
                    {"x": action_data.get("to_x"), "y": action_data.get("to_y")},
                    original_dims,
                    vlm_result.get("screen_origin", (0, 0)),
                )
                source = action_data.get("source_element")
                target = action_data.get("target_element")
                duration = action_data.get("duration", 0.6)
                if any(not isinstance(label, str) or not label.strip() for label in (source, target)):
                    return {"success": False, "detail": "Drag requires described source and target elements.", "is_done": False}
                if start_error or end_error:
                    return {"success": False, "detail": start_error or end_error, "is_done": False}
                if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 0.2 <= duration <= 2.0:
                    return {"success": False, "detail": "Drag duration must be between 0.2 and 2 seconds.", "is_done": False}
                self._input("mouse_drag", *start, *end, duration=float(duration))
                results.append(f"Dragged [{start[0]}, {start[1]}] to [{end[0]}, {end[1]}]")
                self._sleep(self.config.execution.click_pause)
                    
            elif action_type == "click_and_type":
                focus_before = win32_input.get_focus_context()
                coords, coordinate_error = self.resolve_click_coordinates(
                    action_data,
                    original_dims,
                    vlm_result.get("screen_origin", (0, 0)),
                )
                element = action_data.get("element")
                text = action_data.get("text", "")
                submit = action_data.get("submit", False)
                clear_existing = action_data.get("clear_existing", False)
                if not isinstance(element, str) or not element.strip() or len(element) > 300:
                    return {"success": False, "detail": "click_and_type requires a concise target description.", "is_done": False}
                if coordinate_error:
                    return {"success": False, "detail": coordinate_error, "is_done": False}
                if not isinstance(text, str):
                    return {"success": False, "detail": "Text action requires a string value.", "is_done": False}
                if len(text) > self.config.safety.max_text_input_characters:
                    return {"success": False, "detail": "Text action exceeds the configured safety limit.", "is_done": False}
                if not isinstance(submit, bool) or not isinstance(clear_existing, bool):
                    return {"success": False, "detail": "Flags submit and clear_existing must be booleans.", "is_done": False}
                if self.is_dummy_verification_code(text, element):
                    return {
                        "success": False,
                        "detail": "Dummy verification code blocked. Never guess OTPs or verification codes. Request human intervention using hitl_intervention.",
                        "is_done": False,
                    }

                x, y = coords
                self._input("mouse_click", x, y)
                results.append(f"Clicked [{x}, {y}] to focus '{element[:80]}'")
                self._sleep(self.config.execution.click_pause)

                if clear_existing:
                    self._input("hotkey", "ctrl", "a")
                    self._sleep(0.05)
                    self._input("key_press", "backspace")
                    self._sleep(0.05)
                    results.append("Cleared existing text")

                if text:
                    interval = self.config.execution.typing_interval
                    if not self._input("paste_text_preserving_clipboard", text):
                        self._input("type_text", text, interval=interval)
                    results.append(f"Typed {len(text)} character(s)")

                if submit:
                    self._input("key_press", "enter")
                    results.append("Pressed Enter")

                self._sleep(self.config.execution.click_pause)
                focus_after = win32_input.get_focus_context()

            elif action_type == "compound_action":
                actions = action_data.get("actions", [])
                if not isinstance(actions, list) or not actions:
                    return {"success": False, "detail": "compound_action requires a non-empty list of actions.", "is_done": False}
                if len(actions) > 5:
                    return {"success": False, "detail": "compound_action exceeds maximum limit of 5 sub-actions.", "is_done": False}

                sub_steps = []
                for idx, sub_act in enumerate(actions[:1]):
                    self._guard()
                    if not isinstance(sub_act, dict):
                        return {"success": False, "detail": f"Sub-action {idx+1} is not a valid action dictionary.", "is_done": False}
                    sub_vlm_result = {
                        "parsed_action": sub_act,
                        "screen_origin": vlm_result.get("screen_origin", (0, 0)),
                        "action_desp": sub_act.get("tool_name", ""),
                    }
                    sub_res = self.execute_vlm_action(sub_vlm_result, original_dims)
                    sub_steps.append(f"[{idx+1}] {sub_res.get('detail', '')}")
                    if not sub_res.get("success", False):
                        return {
                            "success": False,
                            "detail": f"Compound action stopped at step {idx+1}: {sub_res.get('detail', '')}",
                            "is_done": False,
                        }
                    if sub_res.get("is_done", False):
                        is_done = True
                        break
                    self._sleep(self.config.execution.click_pause)

                results.append(" -> ".join(sub_steps) + " Remaining compound actions were withheld. Re-observe the screen and choose the next action.")

            elif action_type == "type":
                text = action_data.get("text", "")
                submit = action_data.get("submit", False)
                if not isinstance(text, str):
                    return {
                        "success": False,
                        "detail": "Text action requires a string value.",
                        "is_done": False
                    }
                if len(text) > self.config.safety.max_text_input_characters:
                    return {
                        "success": False,
                        "detail": "Text action exceeds the configured safety limit.",
                        "is_done": False
                    }
                if not isinstance(submit, bool):
                    return {
                        "success": False,
                        "detail": "Text submit flag must be a boolean.",
                        "is_done": False
                    }
                if self.is_dummy_verification_code(text, action_data.get("element", "")):
                    return {
                        "success": False,
                        "detail": "Dummy verification code blocked. Never guess OTPs or verification codes. Request human intervention using hitl_intervention.",
                        "is_done": False,
                    }
                interval = self.config.execution.typing_interval
                if not self._input("paste_text_preserving_clipboard", text):
                    self._input("type_text", text, interval=interval)
                results.append(f"Typed {len(text)} character(s)")
                
                if submit:
                    self._input("key_press", "enter")
                    results.append("Pressed Enter")
                self._sleep(self.config.execution.click_pause)
                
            elif action_type == "key_press":
                key = action_data.get("key")
                if isinstance(key, str) and key.strip():
                    normalized_key = "".join(key.lower().split())
                    # Check banned shortcuts
                    if normalized_key in self.config.safety.banned_shortcuts:
                        return {
                            "success": False,
                            "detail": "Banned shortcut blocked",
                            "is_done": False
                        }
                    
                    # Support key combinations like win+r, ctrl+c, ctrl++
                    if "+" in normalized_key:
                        if normalized_key.endswith("++"):
                            parts = [p for p in normalized_key[:-2].split("+") if p] + ["+"]
                        else:
                            parts = normalized_key.split("+")
                        if not 2 <= len(parts) <= 4 or any(not part for part in parts):
                            return {
                                "success": False,
                                "detail": "Invalid hotkey format.",
                                "is_done": False,
                            }
                        # Validate all keys before pressing any modifier. This
                        # prevents malformed model output leaving Ctrl/Alt/Win
                        # held down after a partial hotkey execution.
                        for part in parts:
                            win32_input.resolve_vk(part)
                        self._input("hotkey", *parts)
                        results.append(f"Pressed hotkey '{normalized_key}'")
                    else:
                        win32_input.resolve_vk(key)
                        self._input("key_press", key)
                        results.append(f"Pressed key '{key}'")
                    self._sleep(self.config.execution.click_pause)

                else:
                    success = False
                    results.append("Missing key for key_press action.")
                    
            elif action_type == "scroll":
                direction = action_data.get("direction", "down")
                if direction not in {"up", "down"}:
                    return {
                        "success": False,
                        "detail": "Scroll direction must be 'up' or 'down'.",
                        "is_done": False
                    }
                # If coordinates were provided, hover over the target element first.
                # Otherwise, center the cursor within the observed monitor to ensure wheel target is active.
                if action_data.get("x") is not None and action_data.get("y") is not None:
                    coords, _ = self.resolve_click_coordinates(
                        action_data,
                        original_dims,
                        vlm_result.get("screen_origin", (0, 0)),
                    )
                    if coords:
                        self._input("set_cursor_pos", coords[0], coords[1])
                        self._sleep(0.05)
                else:
                    origin_x, origin_y = vlm_result.get("screen_origin", (0, 0))
                    orig_w, orig_h = original_dims if isinstance(original_dims, tuple) and len(original_dims) == 2 else (1920, 1080)
                    self._input("set_cursor_pos", origin_x + orig_w // 2, origin_y + orig_h // 2)
                    self._sleep(0.05)

                amount = 360 if direction == "up" else -360
                self._input("mouse_scroll", amount)
                results.append(f"Scrolled {direction}")
                self._sleep(self.config.execution.click_pause)
                
            elif action_type == "wait":
                duration = action_data.get("duration", 3)
                if isinstance(duration, bool) or not isinstance(duration, (int, float)):
                    return {
                        "success": False,
                        "detail": "Wait duration must be a number.",
                        "is_done": False
                    }
                duration = max(1, min(float(duration), self.config.safety.max_wait_seconds))
                logger.info(f"Waiting for {duration} seconds...")
                self._sleep(duration)
                results.append(f"Waited for {duration} seconds")
                
            elif action_type == "get_open_apps":
                apps = win32_input.get_open_windows()
                results.append(f"Open applications: {apps}")
                
            elif action_type == "switch_to_app":
                app_title = action_data.get("app_title", "")
                if not isinstance(app_title, str) or not app_title.strip() or len(app_title) > 160:
                    return {
                        "success": False,
                        "detail": "Application title is missing or exceeds the safety limit.",
                        "is_done": False
                    }
                focused = self._input("focus_window", app_title)
                if focused:
                    results.append(f"Switched focus to application matching '{app_title}'")
                else:
                    success = False
                    results.append(f"Could not find any open application matching '{app_title}'")

            elif action_type == "open_app":
                app_name = action_data.get("app_name", "")
                if (
                    not isinstance(app_name, str)
                    or not app_name.strip()
                    or len(app_name) > 80
                    or any(character in app_name for character in "\r\n\t")
                ):
                    return {
                        "success": False,
                        "detail": "Application name is missing or invalid.",
                        "is_done": False,
                    }
                self._input("key_press", "win")
                self._sleep(0.25)
                self._input("type_text", app_name.strip(), interval=min(self.config.execution.typing_interval, 0.03))
                time.sleep(0.1)
                self._input("key_press", "enter")
                time.sleep(0.8)
                results.append(f"Opened app search for '{app_name.strip()}'")
                    
            elif action_type == "minimize_all_apps":
                self._input("minimize_all_windows")
                results.append("Minimized all windows to show desktop")
                
            elif action_type == "terminate":
                status = action_data.get("status", "success")
                reason = action_data.get("reason", "Unknown")
                is_done = True
                success = (status == "success")
                results.append(f"Terminated: {status} ({reason})")
                
            else:
                success = False
                results.append(f"Unknown tool_name: {action_type}")
                
        except RuntimeError:
            # Re-raise RuntimeError so the failsafe / corner-boundary exception
            # always aborts execution immediately (cannot be silenced).
            raise
        except Exception as e:
            logger.error(f"Execution failed on tool '{action_type}': {e}")
            success = False
            results.append(str(e))
            
        response = {
            "success": success, 
            "detail": "; ".join(results), 
            "is_done": is_done
        }
        if action_type in {"click", "double_click", "right_click", "click_and_type"} and success:
            response["focus_changed"] = focus_before != focus_after
        return response
