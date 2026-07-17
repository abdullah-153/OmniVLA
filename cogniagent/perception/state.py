"""
cogniagent/perception/state.py

Lightweight data classes for representing the semantic state of the UI.
Used by ScreenVerifier and the hybrid verification loop in agent.py.
"""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class UIElement:
    """Represents a single interactive UI element detected in the current screen."""
    label: Optional[str] = None          # Visible text or accessible name
    role: Optional[str] = None           # e.g. "button", "textbox", "menuitem"
    bounding_box: Optional[tuple] = None # (x1, y1, x2, y2) in screen pixels


@dataclass
class SemanticState:
    """
    A snapshot of the screen's semantic state at a given moment.

    In the current VLM-first architecture, this is populated from UIA tree queries
    or left as empty defaults (safe no-op) when UIA is unavailable.
    """
    app: str = ""                              # Foreground application name
    window_title: str = ""                     # Foreground window title
    layout_type: str = ""                      # e.g. "dialog", "explorer", "browser"
    is_dialog: bool = False                    # True if a modal dialog is in focus
    visible_text_summary: str = ""             # Short summary of visible text content
    elements: List[UIElement] = field(default_factory=list)
    # Semantic extraction is deliberately best-effort.  Consumers can tell an
    # unavailable accessibility tree from a real, empty UI tree.
    is_available: bool = False
    source: str = ""
