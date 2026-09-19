"""
cogniagent/skills/teaching_recorder.py

Demonstration Recorder for Interactive Teaching Mode.
Captures user actions, coordinates, text inputs, and visual context during human demonstration.
"""

import time
import logging
import ctypes
import os
import queue
import threading
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


class NativeObservationRecorder:
    """Capture human desktop input safely using non-blocking Windows polling.

    Uses GetAsyncKeyState and GetCursorPos on a background thread instead of
    synchronous WH_MOUSE_LL / WH_KEYBOARD_LL hooks. This guarantees that human
    keyboard and mouse input is NEVER blocked, delayed, or frozen by Python.
    Printable text is deliberately represented by a redacted placeholder;
    demonstrations must not become a credential logger.
    """

    def __init__(self, observer):
        self.observer = observer
        self._active = False
        self._events: queue.Queue = queue.Queue(maxsize=256)
        self._poll_thread: Optional[threading.Thread] = None
        self._consumer_thread: Optional[threading.Thread] = None
        self._started_at = 0.0

    @property
    def is_recording(self) -> bool:
        return self._active

    def start(self) -> bool:
        if os.name != "nt":
            logger.warning("Native observation is only available on Windows.")
            return False
        if self._active:
            return True
        self._events = queue.Queue(maxsize=256)
        self._active = True
        self._started_at = time.time()
        user32 = ctypes.windll.user32
        width = int(user32.GetSystemMetrics(78)) or 1920   # SM_CXVIRTUALSCREEN
        height = int(user32.GetSystemMetrics(79)) or 1080  # SM_CYVIRTUALSCREEN
        self.observer.screen_dims = (width, height)
        self.observer.screen_origin = (
            int(user32.GetSystemMetrics(76)),  # SM_XVIRTUALSCREEN
            int(user32.GetSystemMetrics(77)),  # SM_YVIRTUALSCREEN
        )
        if getattr(self.observer, "_current_demo", None):
            self.observer._current_demo.screen_dims = (width, height)
        self._consumer_thread = threading.Thread(target=self._consume, name="omnivla-observation-events", daemon=True)
        self._poll_thread = threading.Thread(target=self._poll_loop, name="omnivla-observation-polling", daemon=True)
        self._consumer_thread.start()
        self._poll_thread.start()
        logger.info("Non-blocking desktop observation polling recorder started.")
        return True

    def stop(self) -> None:
        if not self._active:
            return
        self._active = False
        try:
            self._events.put_nowait(None)
        except queue.Full:
            pass
        if self._poll_thread and self._poll_thread is not threading.current_thread():
            self._poll_thread.join(timeout=1.0)
        if self._consumer_thread and self._consumer_thread is not threading.current_thread():
            self._consumer_thread.join(timeout=1.0)
        self._poll_thread = None
        self._consumer_thread = None
        logger.info("Non-blocking desktop observation polling recorder stopped.")

    def _enqueue(self, event: tuple) -> None:
        if not self._active or time.time() - self._started_at < 0.35:
            return
        try:
            self._events.put_nowait(event)
        except queue.Full:
            logger.warning("Observation event buffer is full; dropping an input event.")

    @staticmethod
    def _foreground_title() -> str:
        try:
            user32 = ctypes.windll.user32
            handle = user32.GetForegroundWindow()
            if not handle:
                return "Desktop"
            length = min(200, max(0, user32.GetWindowTextLengthW(handle)))
            if length <= 0:
                return "Desktop"
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(handle, buffer, len(buffer))
            return buffer.value or "Desktop"
        except Exception:
            return "Desktop"

    def _consume(self) -> None:
        while self._active or not self._events.empty():
            try:
                event = self._events.get(timeout=0.25)
            except queue.Empty:
                continue
            if event is None:
                break
            kind, payload = event
            try:
                if kind == "click":
                    self.observer.record_click(**payload)
                elif kind == "key":
                    self.observer.record_key(**payload)
                elif kind == "type":
                    self.observer.record_typing(**payload)
            except Exception as error:
                logger.warning("Unable to record observed %s event: %s", kind, error)

    def _poll_loop(self) -> None:
        from ctypes import wintypes
        user32 = ctypes.windll.user32

        prev_lbutton = False
        prev_rbutton = False
        prev_keys: set[int] = set()

        modifier_vks = {0x10: "shift", 0x11: "ctrl", 0x12: "alt", 0x5B: "win", 0x5C: "win"}
        key_names = {
            0x08: "backspace", 0x09: "tab", 0x0D: "enter", 0x1B: "esc", 0x20: "space",
            0x21: "pageup", 0x22: "pagedown", 0x23: "end", 0x24: "home", 0x25: "left",
            0x26: "up", 0x27: "right", 0x28: "down", 0x2D: "insert", 0x2E: "delete",
        }
        last_type_time = 0.0
        pt = wintypes.POINT()

        while self._active:
            try:
                # Poll mouse buttons
                lbutton_down = bool(user32.GetAsyncKeyState(0x01) & 0x8000)
                rbutton_down = bool(user32.GetAsyncKeyState(0x02) & 0x8000)
                user32.GetCursorPos(ctypes.byref(pt))

                # Button click completed (mouse up after mouse down)
                if prev_lbutton and not lbutton_down:
                    title = self._foreground_title()
                    self._enqueue(("click", {
                        "x": int(pt.x), "y": int(pt.y),
                        "button": "left",
                        "window_title": title, "visual_cue": "",
                    }))
                elif prev_rbutton and not rbutton_down:
                    title = self._foreground_title()
                    self._enqueue(("click", {
                        "x": int(pt.x), "y": int(pt.y),
                        "button": "right",
                        "window_title": title, "visual_cue": "",
                    }))

                prev_lbutton = lbutton_down
                prev_rbutton = rbutton_down

                # Poll modifiers
                active_modifiers = [name for vk, name in modifier_vks.items() if (user32.GetAsyncKeyState(vk) & 0x8000)]

                # Poll key presses
                check_vks = list(key_names.keys()) + list(range(0x30, 0x5B))
                for vk in check_vks:
                    is_down = bool(user32.GetAsyncKeyState(vk) & 0x8000)
                    was_down = vk in prev_keys

                    if is_down and not was_down:
                        prev_keys.add(vk)
                        title = self._foreground_title()
                        k_name = key_names.get(vk) or chr(vk).lower()
                        if active_modifiers:
                            combo = "+".join(active_modifiers + [k_name])
                            self._enqueue(("key", {"key": combo, "window_title": title}))
                        elif vk in key_names:
                            self._enqueue(("key", {"key": k_name, "window_title": title}))
                        else:
                            now = time.time()
                            if now - last_type_time > 1.0:
                                last_type_time = now
                                self._enqueue(("type", {"text": "{{typed_value}}", "window_title": title}))
                    elif not is_down and was_down:
                        prev_keys.discard(vk)

            except Exception as e:
                logger.debug("Observation polling error: %s", e)

            time.sleep(0.03)


@dataclass
class DemonstrationAction:
    """An action captured during human demonstration."""
    action_type: str  # "click", "double_click", "right_click", "type", "key_press", "hotkey"
    timestamp: float
    x: Optional[int] = None
    y: Optional[int] = None
    text: Optional[str] = None
    key: Optional[str] = None
    window_title: str = ""
    target_element_hint: str = ""


@dataclass
class DemonstrationEpisode:
    """A complete recording of a human teaching demonstration."""
    task_prompt: str
    actions: List[DemonstrationAction] = field(default_factory=list)
    screen_dims: tuple = (1920, 1080)
    started_at: float = 0.0
    finished_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "task_prompt": self.task_prompt,
            "actions": [
                {
                    "action_type": a.action_type,
                    "timestamp": a.timestamp,
                    "x": a.x,
                    "y": a.y,
                    "text": a.text,
                    "key": a.key,
                    "window_title": a.window_title,
                    "target_element_hint": a.target_element_hint,
                }
                for a in self.actions
            ],
            "screen_dims": list(self.screen_dims),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DemonstrationEpisode":
        actions = [
            DemonstrationAction(
                action_type=a.get("action_type", "click"),
                timestamp=a.get("timestamp", 0.0),
                x=a.get("x"),
                y=a.get("y"),
                text=a.get("text"),
                key=a.get("key"),
                window_title=a.get("window_title", ""),
                target_element_hint=a.get("target_element_hint", ""),
            )
            for a in data.get("actions", [])
        ]
        return cls(
            task_prompt=data.get("task_prompt", ""),
            actions=actions,
            screen_dims=tuple(data.get("screen_dims", (1920, 1080))),
            started_at=data.get("started_at", 0.0),
            finished_at=data.get("finished_at", 0.0),
        )


class TeachingRecorder:
    """Session manager for recording human demonstrations in Teaching Mode."""

    def __init__(self, screen_dims: tuple = (1920, 1080)):
        self.screen_dims = screen_dims
        self._is_recording = False
        self._current_episode: Optional[DemonstrationEpisode] = None

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    def start_recording(self, task_prompt: str):
        """Start a new demonstration recording session."""
        self._is_recording = True
        self._current_episode = DemonstrationEpisode(
            task_prompt=task_prompt,
            screen_dims=self.screen_dims,
            started_at=time.time(),
        )
        logger.info("TeachingRecorder started for prompt: '%s'", task_prompt)

    def record_click(self, x: int, y: int, button: str = "left", window_title: str = "", hint: str = ""):
        """Record a human click event."""
        if not self._is_recording or not self._current_episode:
            return
        action_type = "double_click" if button == "double" else ("right_click" if button == "right" else "click")
        action = DemonstrationAction(
            action_type=action_type,
            timestamp=time.time(),
            x=x,
            y=y,
            window_title=window_title,
            target_element_hint=hint,
        )
        self._current_episode.actions.append(action)

    def record_text_input(self, text: str, window_title: str = ""):
        """Record a text typing event."""
        if not self._is_recording or not self._current_episode:
            return
        # If the last action was typing and within 1 second, concatenate text
        if self._current_episode.actions:
            last = self._current_episode.actions[-1]
            if last.action_type == "type" and time.time() - last.timestamp < 1.0:
                last.text = (last.text or "") + text
                last.timestamp = time.time()
                return

        action = DemonstrationAction(
            action_type="type",
            timestamp=time.time(),
            text=text,
            window_title=window_title,
        )
        self._current_episode.actions.append(action)

    def record_key_press(self, key: str, window_title: str = ""):
        """Record a single keypress or hotkey event."""
        if not self._is_recording or not self._current_episode:
            return
        action_type = "hotkey" if "+" in key else "key_press"
        action = DemonstrationAction(
            action_type=action_type,
            timestamp=time.time(),
            key=key,
            window_title=window_title,
        )
        self._current_episode.actions.append(action)

    def stop_recording(self) -> Optional[DemonstrationEpisode]:
        """Stop recording and return the completed demonstration episode."""
        if not self._is_recording or not self._current_episode:
            return None
        
        self._is_recording = False
        self._current_episode.finished_at = time.time()
        episode = self._current_episode
        self._current_episode = None
        logger.info(
            "TeachingRecorder stopped. Captured %d actions over %.1fs",
            len(episode.actions),
            episode.finished_at - episode.started_at,
        )
        return episode
