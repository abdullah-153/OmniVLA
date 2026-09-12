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
    """Capture human desktop input with low-level Windows hooks.

    Hook callbacks only enqueue compact events. Screenshot capture and skill
    bookkeeping run on a worker thread so Windows input is never blocked.
    Printable text is deliberately represented by a redacted placeholder;
    demonstrations must not become a credential logger.
    """

    def __init__(self, observer):
        self.observer = observer
        self._active = False
        self._events: queue.Queue = queue.Queue(maxsize=256)
        self._hook_thread: Optional[threading.Thread] = None
        self._consumer_thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._thread_id = 0
        self._mouse_hook = None
        self._keyboard_hook = None
        self._mouse_callback = None
        self._keyboard_callback = None
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
        # A previous stopped session leaves a sentinel in its queue. Each
        # recording owns a fresh bounded queue so restarting cannot silently
        # discard every event.
        self._events = queue.Queue(maxsize=256)
        self._active = True
        self._started_at = time.time()
        self._ready.clear()
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
        self._hook_thread = threading.Thread(target=self._hook_loop, name="omnivla-observation-hooks", daemon=True)
        self._consumer_thread.start()
        self._hook_thread.start()
        self._ready.wait(timeout=2.0)
        if not self._mouse_hook or not self._keyboard_hook:
            self.stop()
            return False
        logger.info("Native desktop observation hooks started.")
        return True

    def stop(self) -> None:
        if not self._active and not self._hook_thread:
            return
        self._active = False
        if self._thread_id and os.name == "nt":
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)  # WM_QUIT
        try:
            self._events.put_nowait(None)
        except queue.Full:
            pass
        if self._hook_thread and self._hook_thread is not threading.current_thread():
            self._hook_thread.join(timeout=2.0)
        if self._consumer_thread and self._consumer_thread is not threading.current_thread():
            self._consumer_thread.join(timeout=2.0)
        self._hook_thread = None
        self._consumer_thread = None
        self._thread_id = 0
        logger.info("Native desktop observation hooks stopped.")

    def _enqueue(self, event: tuple) -> None:
        if not self._active or time.time() - self._started_at < 0.35:
            return
        try:
            self._events.put_nowait(event)
        except queue.Full:
            logger.warning("Observation event buffer is full; dropping an input event.")

    @staticmethod
    def _foreground_title() -> str:
        user32 = ctypes.windll.user32
        handle = user32.GetForegroundWindow()
        length = min(200, max(0, user32.GetWindowTextLengthW(handle)))
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(handle, buffer, len(buffer))
        return buffer.value

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

    def _hook_loop(self) -> None:
        from ctypes import wintypes

        class MSLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [
                ("pt", wintypes.POINT),
                ("mouseData", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t),
            ]

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [
                ("vkCode", wintypes.DWORD),
                ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t),
            ]

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, callback_type, ctypes.c_void_p, wintypes.DWORD]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        modifiers: set[int] = set()
        modifier_names = {0x10: "shift", 0x11: "ctrl", 0x12: "alt", 0x5B: "win", 0x5C: "win"}
        key_names = {
            0x08: "backspace", 0x09: "tab", 0x0D: "enter", 0x1B: "esc", 0x20: "space",
            0x21: "pageup", 0x22: "pagedown", 0x23: "end", 0x24: "home", 0x25: "left",
            0x26: "up", 0x27: "right", 0x28: "down", 0x2D: "insert", 0x2E: "delete",
        }
        last_redacted_text = [0.0]

        def mouse_proc(code, message, data):
            if code >= 0 and message in (0x0202, 0x0205):  # button-up events
                info = ctypes.cast(data, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                if not (info.flags & 0x01):  # LLMHF_INJECTED
                    self._enqueue(("click", {
                        "x": int(info.pt.x), "y": int(info.pt.y),
                        "button": "right" if message == 0x0205 else "left",
                        "window_title": self._foreground_title(), "visual_cue": "",
                    }))
            return user32.CallNextHookEx(self._mouse_hook, code, message, data)

        def keyboard_proc(code, message, data):
            if code >= 0:
                info = ctypes.cast(data, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                vk = int(info.vkCode)
                if info.flags & 0x10:  # LLKHF_INJECTED
                    return user32.CallNextHookEx(self._keyboard_hook, code, message, data)
                if message in (0x0101, 0x0105):  # key-up
                    modifiers.discard(vk)
                elif message in (0x0100, 0x0104):  # key-down
                    if vk in modifier_names:
                        modifiers.add(vk)
                    else:
                        title = self._foreground_title()
                        names = [modifier_names[item] for item in (0x11, 0x12, 0x10, 0x5B, 0x5C) if item in modifiers]
                        key = key_names.get(vk) or (chr(vk).lower() if 0x30 <= vk <= 0x5A else f"vk_{vk}")
                        if names or key in key_names.values():
                            self._enqueue(("key", {"key": "+".join(names + [key]), "window_title": title}))
                        elif time.time() - last_redacted_text[0] > 1.0:
                            last_redacted_text[0] = time.time()
                            self._enqueue(("type", {"text": "{{typed_value}}", "window_title": title}))
            return user32.CallNextHookEx(self._keyboard_hook, code, message, data)

        self._mouse_callback = callback_type(mouse_proc)
        self._keyboard_callback = callback_type(keyboard_proc)
        self._thread_id = int(kernel32.GetCurrentThreadId())
        module = kernel32.GetModuleHandleW(None)
        self._mouse_hook = user32.SetWindowsHookExW(14, self._mouse_callback, module, 0)
        self._keyboard_hook = user32.SetWindowsHookExW(13, self._keyboard_callback, module, 0)
        self._ready.set()
        if not self._mouse_hook or not self._keyboard_hook:
            logger.error(
                "Windows rejected one or more observation hooks (error %s).",
                int(kernel32.GetLastError()),
            )
        else:
            message = wintypes.MSG()
            while self._active and user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        if self._mouse_hook:
            user32.UnhookWindowsHookEx(self._mouse_hook)
        if self._keyboard_hook:
            user32.UnhookWindowsHookEx(self._keyboard_hook)
        self._mouse_hook = None
        self._keyboard_hook = None


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
