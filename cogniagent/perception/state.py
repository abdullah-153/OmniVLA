"""
cogniagent/perception/state.py

Data classes for representing visual observation state.
Used by ScreenVerifier and the agent loop.
"""
from dataclasses import dataclass, field
from typing import Optional, Tuple


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


# Backwards compatibility alias
SemanticState = VisualObservationState
UIElement = object

