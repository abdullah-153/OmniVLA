import time
import logging
import hashlib
import math
import re
from cogniagent.execution import win32_input

logger = logging.getLogger(__name__)

# Basic safety setup (replaces pyautogui configuration)
win32_input.enable_dpi_awareness()

class ActionRouter:
    """Routes VLM tool calls to Windows native system inputs using ctypes.
    
    Clean, simple execution — no retry hacks. The agent loop handles
    self-correction: if a click misses, the next screenshot shows it,
    and the model reasons about what to do differently.
    """
    
    def __init__(self, config):
        self.config = config

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
        if tool_name in {"click", "double_click", "right_click", "move"}:
            label = action_data.get("element", "")
            if not isinstance(label, str):
                label = ""
            def coordinate_bucket(value):
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    return value
                return int(round(float(value) / 50.0) * 50)

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
    def assess_action_risk(action_data: dict) -> dict | None:
        """Identify visible controls that can create an external or destructive effect."""
        if not isinstance(action_data, dict):
            return None
        tool_name = action_data.get("tool_name")
        if tool_name not in {"click", "double_click", "right_click", "drag"}:
            return None
        label = " ".join(
            str(action_data.get(key) or "")
            for key in ("element", "source_element", "target_element")
        )
        rules = (
            ("destructive change", r"\b(delete|remove|erase|trash|discard|overwrite|format|factory reset)\b"),
            ("external communication", r"\b(send|publish|post|share|upload|submit message)\b"),
            ("financial commitment", r"\b(pay|payment|purchase|buy|checkout|place order|transfer|confirm payment)\b"),
            ("access or security change", r"\b(allow|grant|permission|install|uninstall|reset password|disable security)\b"),
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
                        win32_input.mouse_double_click(x, y)
                        results.append(f"Double-clicked [{x}, {y}]")
                    elif action_type == "right_click":
                        win32_input.mouse_click(x, y, button="right")
                        results.append(f"Right-clicked [{x}, {y}]")
                    elif action_type == "move":
                        win32_input.smooth_move_to(x, y, duration=0.25)
                        results.append(f"Moved pointer to [{x}, {y}]")
                    else:
                        win32_input.mouse_click(x, y)
                        results.append(f"Clicked [{x}, {y}]")
                    time.sleep(self.config.execution.click_pause)
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
                win32_input.mouse_drag(*start, *end, duration=float(duration))
                results.append(f"Dragged [{start[0]}, {start[1]}] to [{end[0]}, {end[1]}]")
                time.sleep(self.config.execution.click_pause)
                    
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
                interval = self.config.execution.typing_interval
                if not win32_input.paste_text_preserving_clipboard(text):
                    win32_input.type_text(text, interval=interval)
                results.append(f"Typed {len(text)} character(s)")
                
                if submit:
                    win32_input.key_press("enter")
                    results.append("Pressed Enter")
                time.sleep(self.config.execution.click_pause)
                
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
                        win32_input.hotkey(*parts)
                        results.append(f"Pressed hotkey '{normalized_key}'")
                    else:
                        win32_input.resolve_vk(key)
                        win32_input.key_press(key)
                        results.append(f"Pressed key '{key}'")
                    time.sleep(self.config.execution.click_pause)

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
                        win32_input.set_cursor_pos(coords[0], coords[1])
                        time.sleep(0.05)
                else:
                    origin_x, origin_y = vlm_result.get("screen_origin", (0, 0))
                    orig_w, orig_h = original_dims if isinstance(original_dims, tuple) and len(original_dims) == 2 else (1920, 1080)
                    win32_input.set_cursor_pos(origin_x + orig_w // 2, origin_y + orig_h // 2)
                    time.sleep(0.05)

                amount = 360 if direction == "up" else -360
                win32_input.mouse_scroll(amount)
                results.append(f"Scrolled {direction}")
                time.sleep(self.config.execution.click_pause)
                
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
                time.sleep(duration)
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
                focused = win32_input.focus_window(app_title)
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
                win32_input.key_press("win")
                time.sleep(0.25)
                win32_input.type_text(app_name.strip(), interval=min(self.config.execution.typing_interval, 0.03))
                time.sleep(0.1)
                win32_input.key_press("enter")
                time.sleep(0.8)
                results.append(f"Opened app search for '{app_name.strip()}'")
                    
            elif action_type == "minimize_all_apps":
                win32_input.minimize_all_windows()
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
        if action_type in {"click", "double_click", "right_click"} and success:
            response["focus_changed"] = focus_before != focus_after
        return response
