"""
cogniagent/perception/state.py

Data classes for representing visual observation state.
Used by ScreenVerifier and the agent loop.
"""
from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass
class UIElement:
    """A bounded UI automation element representation."""
    label: Optional[str] = None
    role: Optional[str] = None
    bounding_box: Optional[Tuple[int, int, int, int]] = None


@dataclass
class VisualObservationState:
    """A snapshot of visual observation metadata."""
    window_title: str = ""
    screen_dims: Tuple[int, int] = (1920, 1080)
    screen_origin: Tuple[int, int] = (0, 0)
    timestamp: float = 0.0
    summary: str = ""
    is_available: bool = True
    source: str = "vlm"
    app: str = ""
    layout_type: str = ""
    is_dialog: bool = False
    visible_text_summary: str = ""
    elements: list[UIElement] = field(default_factory=list)


# Backwards compatibility alias
SemanticState = VisualObservationState

