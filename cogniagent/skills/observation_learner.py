"""
cogniagent/skills/observation_learner.py

Demonstration & Observation Session Manager for OmniVLA.
Captures human interactions, active application context, and key visual screenshot frames for collaborative Holo + Qwen skill learning.
"""

import time
import base64
import logging
from io import BytesIO
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

try:
    import mss
    from PIL import Image
except ImportError:
    mss = None
    Image = None

logger = logging.getLogger(__name__)


@dataclass
class ObservedAction:
    """An interaction observed during a human demonstration."""
    action_type: str  # "click", "double_click", "right_click", "type", "hotkey", "key_press"
    timestamp: float
    x: Optional[int] = None
    y: Optional[int] = None
    text: Optional[str] = None
    key: Optional[str] = None
    window_title: str = ""
    visual_cue: str = ""
    screenshot_b64: Optional[str] = None


@dataclass
class ObservationDemonstration:
    """A complete recording of a human observation session."""
    task_goal: str
    actions: List[ObservedAction] = field(default_factory=list)
    key_screenshots: List[str] = field(default_factory=list)  # List of JPEG base64 strings
    app_sequence: List[str] = field(default_factory=list)
    screen_dims: tuple = (1920, 1080)
    started_at: float = 0.0
    finished_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "task_goal": self.task_goal,
            "actions": [
                {
                    "action_type": a.action_type,
                    "timestamp": a.timestamp,
                    "x": a.x,
                    "y": a.y,
                    "text": a.text,
                    "key": a.key,
                    "window_title": a.window_title,
                    "visual_cue": a.visual_cue,
                    "has_screenshot": bool(a.screenshot_b64),
                }
                for a in self.actions
            ],
            "key_screenshot_count": len(self.key_screenshots),
            "app_sequence": self.app_sequence,
            "screen_dims": list(self.screen_dims),
            "duration_seconds": round(self.finished_at - self.started_at, 2) if self.finished_at else 0,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class ObservationLearner:
    """Session manager that records desktop actions and visual screenshots for skill learning."""

    def __init__(self, screen_dims: tuple = (1920, 1080)):
        self.screen_dims = screen_dims
        self.screen_origin = (0, 0)
        self._is_observing = False
        self._current_demo: Optional[ObservationDemonstration] = None
        self._last_frame_at = 0.0

    @property
    def is_observing(self) -> bool:
        return self._is_observing

    def start_observation(self, task_goal: str):
        """Start a new demonstration observation session."""
        self._is_observing = True
        self._current_demo = ObservationDemonstration(
            task_goal=task_goal,
            screen_dims=self.screen_dims,
            started_at=time.time(),
        )
        self._last_frame_at = 0.0
        # Capture initial screen frame
        initial_frame = self._capture_frame_b64()
        if initial_frame:
            self._current_demo.key_screenshots.append(initial_frame)
        logger.info("ObservationLearner started for task goal: '%s'", task_goal)

    def _capture_frame_b64(self) -> Optional[str]:
        """Capture compressed JPEG frame of the active display with fail-safe fallback."""
        if not Image:
            return None
        img = None
        if mss:
            try:
                with mss.mss() as sct:
                    monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                    sct_img = sct.grab(monitor)
                    img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
            except Exception as me:
                logger.debug("mss grab failed (%s), falling back to ImageGrab", me)

        if img is None:
            try:
                from PIL import ImageGrab
                img = ImageGrab.grab().convert("RGB")
            except Exception as ie:
                logger.warning("ObservationLearner screenshot capture failed: %s", ie)
                return None

        try:
            # Keep UI labels legible for later visual skill synthesis while
            # bounding the six-frame recording buffer.
            img.thumbnail((1280, 720), Image.Resampling.LANCZOS)
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=82, optimize=True)
            return base64.b64encode(buf.getvalue()).decode("utf-8")
        except Exception as e:
            logger.warning("ObservationLearner screenshot encode failed: %s", e)
            return None


    def record_click(self, x: int, y: int, button: str = "left", window_title: str = "", visual_cue: str = ""):
        """Record an observed mouse click."""
        if not self._is_observing or not self._current_demo:
            return
        if "omnivla" in window_title.casefold():
            return

        action_type = "double_click" if button == "double" else ("right_click" if button == "right" else "click")
        # Normalize coordinates [0, 1000]
        local_x = x - self.screen_origin[0]
        local_y = y - self.screen_origin[1]
        norm_x = max(0, min(1000, int(local_x * 1000 / self.screen_dims[0]))) if self.screen_dims[0] else x
        norm_y = max(0, min(1000, int(local_y * 1000 / self.screen_dims[1]))) if self.screen_dims[1] else y

        now = time.time()
        should_capture = len(self._current_demo.key_screenshots) < 6 and now - self._last_frame_at >= 0.6
        frame = self._capture_frame_b64() if should_capture else None
        if frame:
            self._last_frame_at = now
        action = ObservedAction(
            action_type=action_type,
            timestamp=time.time(),
            x=norm_x,
            y=norm_y,
            window_title=window_title,
            visual_cue=visual_cue,
            screenshot_b64=frame,
        )
        self._current_demo.actions.append(action)
        if frame and len(self._current_demo.key_screenshots) < 6:
            self._current_demo.key_screenshots.append(frame)

        if window_title and (not self._current_demo.app_sequence or self._current_demo.app_sequence[-1] != window_title):
            self._current_demo.app_sequence.append(window_title)

    def record_typing(self, text: str, window_title: str = ""):
        """Record observed text input."""
        if not self._is_observing or not self._current_demo:
            return
        if "omnivla" in window_title.casefold():
            return

        if self._current_demo.actions:
            last = self._current_demo.actions[-1]
            if last.action_type == "type" and time.time() - last.timestamp < 1.5:
                last.text = (last.text or "") + text
                last.timestamp = time.time()
                return

        action = ObservedAction(
            action_type="type",
            timestamp=time.time(),
            text=text,
            window_title=window_title,
        )
        self._current_demo.actions.append(action)

        if window_title and (not self._current_demo.app_sequence or self._current_demo.app_sequence[-1] != window_title):
            self._current_demo.app_sequence.append(window_title)

    def record_key(self, key: str, window_title: str = ""):
        """Record observed hotkey or keypress."""
        if not self._is_observing or not self._current_demo:
            return
        if "omnivla" in window_title.casefold():
            return

        action_type = "hotkey" if "+" in key else "key_press"
        action = ObservedAction(
            action_type=action_type,
            timestamp=time.time(),
            key=key,
            window_title=window_title,
        )
        self._current_demo.actions.append(action)

    def stop_observation(self) -> Optional[ObservationDemonstration]:
        """Finish observation session and return the demonstration data."""
        if not self._is_observing or not self._current_demo:
            return None

        self._is_observing = False
        self._current_demo.finished_at = time.time()
        demo = self._current_demo
        self._current_demo = None
        logger.info(
            "Observation finished: %d actions, %d key screenshots over %.1fs",
            len(demo.actions),
            len(demo.key_screenshots),
            demo.finished_at - demo.started_at,
        )
        return demo
