import numpy as np
import logging
from cogniagent.perception.state import SemanticState
from cogniagent.reasoning.action_reasoner import AgentAction

logger = logging.getLogger(__name__)

class ScreenVerifier:
    """Verifies the success of an action using screen diffs and semantic checks."""

    def __init__(self, max_sample_pixels: int = 250_000):
        self.max_sample_pixels = max(1, int(max_sample_pixels))

    @staticmethod
    def has_semantic_observation(state: SemanticState) -> bool:
        """Tell a real accessibility snapshot from an unavailable empty one."""
        return bool(
            getattr(state, "is_available", False)
            or getattr(state, "elements", None)
            or getattr(state, "is_dialog", False)
            or getattr(state, "visible_text_summary", "")
        )
    
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

        # int16 is sufficient for the [-255, 255] pixel delta and avoids the
        # much larger default int64 full-frame allocation.
        if before_sample.ndim == 3:
            before_sample = before_sample[:, :, :3]
            after_sample = after_sample[:, :, :3]
        diff = np.abs(before_sample.astype(np.int16) - after_sample.astype(np.int16))
            
        # A difference exactly at the configured threshold is meaningful.  The
        # prior strict comparison silently discarded real, deterministic UI
        # transitions at that boundary.
        changed_pixels = np.any(diff >= threshold, axis=2) if diff.ndim == 3 else diff >= threshold
        diff_ratio = float(changed_pixels.sum()) / changed_pixels.size
        
        # Classify the change
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

    def verify_semantically(self, old_state: SemanticState, new_state: SemanticState, action: AgentAction, expected_outcome: str = "") -> bool:
        """Check if the action produced the expected semantic change."""
        
        old_labels = {e.label for e in old_state.elements if e.label}
        new_labels = {e.label for e in new_state.elements if e.label}
        
        new_elements = new_labels - old_labels
        removed_elements = old_labels - new_labels
        
        # Action-specific verification
        if action.action_type == "click":
            # After clicking a menu item, new items should appear
            if action.thought and "menu" in action.thought.lower():
                return len(new_elements) > 0
            
            # After clicking a tab, the tab layout might change or new elements appear
            if action.thought and "tab" in action.thought.lower():
                return new_state.layout_type != old_state.layout_type or len(new_elements) > 0
                
        elif action.action_type == "type":
            # After typing, the text should appear somewhere in the state
            if action.args:
                typed_text = action.args[0]
                return any(typed_text.lower() in (e.label or "").lower() for e in new_state.elements)
                
        # Fallback: any visible change in labels is a potential success
        if len(new_elements) > 0 or len(removed_elements) > 0:
            return True
            
        # If the active application changed, it is an observable state change.
        if old_state.app and new_state.app and old_state.app != new_state.app:
            return True
            
        return False

    def detect_failure(self, diff_result: dict, old_state: SemanticState, new_state: SemanticState, action: AgentAction) -> str:
        """Detect if an action failed. Returns failure reason or None."""
        
        # Unexpected dialog appeared
        if new_state.is_dialog and not old_state.is_dialog:
            dialog_text = str(new_state.visible_text_summary or "").lower()
            if any(w in dialog_text for w in ["error", "warning", "failed"]):
                return f"Error dialog appeared: {new_state.visible_text_summary}"

        # These tools are observations or control-flow states; they need not
        # visibly mutate the screen to be valid.
        passive_actions = {"wait", "get_open_apps", "hitl_intervention", "terminate"}
        if not diff_result.get("changed", True) and action.action_type not in passive_actions:
            return "No visible screen change after action"

        # A changed screenshot can be just a cursor hover or animation.  When
        # UIA supplied genuine before/after states, require it to corroborate
        # interactive actions before treating the step as verified.
        interactive_actions = {"click", "type", "key_press", "scroll", "switch_to_app"}
        if (
            action.action_type in interactive_actions
            and self.has_semantic_observation(old_state)
            and self.has_semantic_observation(new_state)
            and not self.verify_semantically(old_state, new_state, action)
        ):
            return "Accessible UI state did not confirm the requested action"
        
        # Application crashed or lost focus entirely unexpectedly
        if new_state.app != old_state.app and old_state.app not in new_state.window_title:
            # Not necessarily a failure if we wanted to switch apps, but a risk
            pass
            
        return None
