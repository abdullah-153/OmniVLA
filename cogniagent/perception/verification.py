import numpy as np
import logging
from cogniagent.reasoning.action_reasoner import AgentAction

logger = logging.getLogger(__name__)

class ScreenVerifier:
    """Verifies the visual outcome of an agent action using bounded screen diffs."""

    def __init__(self, max_sample_pixels: int = 250_000):
        self.max_sample_pixels = max(1, int(max_sample_pixels))
    
    def compute_screen_diff(self, before_frame: np.ndarray, after_frame: np.ndarray, threshold: int = 30) -> dict:
        """Compare screenshots using a bounded CPU and memory budget."""
        if before_frame is None or after_frame is None:
            return {"changed": True, "diff_ratio": 1.0, "description": "Missing frames"}
            
        if before_frame.shape != after_frame.shape:
            return {"changed": True, "diff_ratio": 1.0, "description": "Resolution changed"}
        
        height, width = before_frame.shape[:2]
        total_pixels = height * width
        sample_stride = max(1, int(np.ceil(np.sqrt(total_pixels / self.max_sample_pixels))))
        before_sample = before_frame[::sample_stride, ::sample_stride]
        after_sample = after_frame[::sample_stride, ::sample_stride]

        # int16 is sufficient for the [-255, 255] pixel delta and avoids full-frame int64 allocation
        if before_sample.ndim == 3:
            before_sample = before_sample[:, :, :3]
            after_sample = after_sample[:, :, :3]
        diff = np.abs(before_sample.astype(np.int16) - after_sample.astype(np.int16))
            
        changed_pixels = np.any(diff >= threshold, axis=2) if diff.ndim == 3 else diff >= threshold
        diff_ratio = float(changed_pixels.sum()) / changed_pixels.size
        
        # Classify visual change
        if diff_ratio < 0.01:
            description = "No visible change"
            changed = False
        elif diff_ratio < 0.10:
            description = "Minor change (tooltip, cursor, highlight)"
            changed = True
        elif diff_ratio < 0.30:
            description = "Moderate change (menu opened, element selected)"
            changed = True
        elif diff_ratio < 0.50:
            description = "Significant change (dialog opened, page scrolled)"
            changed = True
        else:
            description = "Major change (new window, page navigation)"
            changed = True
        
        return {
            "changed": changed,
            "diff_ratio": diff_ratio,
            "description": description,
            "sample_stride": sample_stride,
            "sampled_pixels": int(changed_pixels.size),
        }

    def detect_failure(self, diff_result: dict, old_state: object = None, new_state: object = None, action: AgentAction = None, execution_result: dict = None) -> str | None:
        """Detect if an action resulted in visual stagnation or failure. Returns failure reason or None."""
        if not action:
            return None

        # These tools are observational or control-flow; they don't visibly mutate the screen
        passive_actions = {"wait", "get_open_apps", "hitl_intervention", "terminate"}
        if action.action_type in passive_actions:
            return None

        # Text, a caret, or a focus ring can affect far less than 1% of a
        # 1080p frame. They are meaningful outcomes even though they sit below
        # the navigation-oriented screen-change cutoff.
        if action.action_type in {"type", "key_press"} and float(diff_result.get("diff_ratio", 0.0)) >= 0.00002:
            return None
        if action.action_type in {"click", "double_click", "right_click"} and (execution_result or {}).get("focus_changed"):
            return None

        if not diff_result.get("changed", True):
            return "No visible screen change after action"

        return None
