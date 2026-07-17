"""Best-effort UI Automation grounding for safe native computer use.

The visual model proposes an action, but it should not be the only source of
truth when Windows accessibility data is available.  This module deliberately
fails open when UI Automation is unavailable; native execution still has its
own strict coordinate validation.  When a labelled control is found at a
proposed click point, an obvious label mismatch is treated as a safety block
instead of a potentially destructive misclick.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from cogniagent.perception.state import SemanticState, UIElement


logger = logging.getLogger(__name__)

_GENERIC_TARGET_WORDS = {
    "a", "an", "and", "button", "control", "icon", "item", "link", "menu",
    "option", "tab", "text", "the", "this", "to", "ui",
}


def _target_tokens(value: str) -> set[str]:
    """Extract meaningful words from model and accessibility labels."""
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value)
    return {
        token
        for token in re.findall(r"[a-z0-9]+", spaced.lower())
        if len(token) > 1 and token not in _GENERIC_TARGET_WORDS
    }


def _wrapper_for(specification):
    """Resolve a pywinauto specification without tying callers to its API."""
    return specification.wrapper_object() if hasattr(specification, "wrapper_object") else specification


def _element_from_wrapper(wrapper) -> UIElement:
    info = getattr(wrapper, "element_info", None)
    label = ""
    try:
        label = wrapper.window_text() or ""
    except Exception:
        pass
    if not label:
        label = str(getattr(info, "name", "") or "")

    role = str(getattr(info, "control_type", "") or "")
    bounding_box = None
    try:
        rect = wrapper.rectangle()
        bounding_box = (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
    except Exception:
        pass
    return UIElement(label=label or None, role=role or None, bounding_box=bounding_box)


class UIAutomationGrounder:
    """Read a bounded UIA snapshot and preflight click targets when possible."""

    def __init__(self, max_elements: int = 200):
        self.max_elements = max(1, int(max_elements))

    def capture_state(self) -> SemanticState:
        """Capture the foreground UI tree, returning an empty state on failure."""
        try:
            from pywinauto import Desktop

            desktop = Desktop(backend="uia")
            wrapper = _wrapper_for(desktop.get_active())
            root = _element_from_wrapper(wrapper)
            info = getattr(wrapper, "element_info", None)

            elements = []
            seen: set[tuple[str | None, str | None, tuple | None]] = set()
            for child in list(wrapper.descendants())[: self.max_elements]:
                element = _element_from_wrapper(child)
                identity = (element.label, element.role, element.bounding_box)
                if identity in seen:
                    continue
                seen.add(identity)
                elements.append(element)

            title = root.label or ""
            control_type = (root.role or "").lower()
            summary = " | ".join(
                element.label for element in elements if element.label
            )[:800]
            state = SemanticState(
                app=str(getattr(info, "process_id", "") or ""),
                window_title=title,
                layout_type=root.role or "",
                is_dialog=control_type == "dialog",
                visible_text_summary=summary,
                elements=elements,
            )
            # setattr keeps compatibility with the lightweight test doubles.
            state.is_available = True
            state.source = "uia"
            return state
        except Exception as exc:
            logger.debug("UI Automation state capture unavailable: %s", exc)
            return SemanticState()

    def validate_click_target(self, x: int, y: int, expected_description: object) -> Optional[str]:
        """Return a block reason for an obvious labelled-target mismatch.

        An unlabeled control, a generic model description, or unavailable UIA
        data never blocks execution.  That avoids turning accessibility gaps
        into false failures while still catching the useful high-confidence
        case: the model says "Delete" but UIA identifies "Cancel".
        """
        if not isinstance(expected_description, str):
            return None
        expected = _target_tokens(expected_description)
        if not expected:
            return None

        try:
            from pywinauto import Desktop

            wrapper = _wrapper_for(Desktop(backend="uia").from_point(int(x), int(y)))
            actual = _element_from_wrapper(wrapper)
        except Exception as exc:
            logger.debug("UI Automation click preflight unavailable: %s", exc)
            return None

        actual_tokens = _target_tokens(actual.label or "")
        if actual_tokens and expected.isdisjoint(actual_tokens):
            return (
                "Accessibility target mismatch: model expected "
                f"'{expected_description}', but the control at that point is '{actual.label}'."
            )
        return None
