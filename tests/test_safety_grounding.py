"""Focused tests for deterministic computer-use safety guards."""

import sys
import types
import unittest

import tests.conftest

tests.conftest.init_mocks()

from cogniagent.perception.uia_grounding import UIAutomationGrounder


class _Rectangle:
    left = 10
    top = 20
    right = 110
    bottom = 60


class _ElementInfo:
    def __init__(self, name, control_type="Button", process_id=42):
        self.name = name
        self.control_type = control_type
        self.process_id = process_id


class _Wrapper:
    def __init__(self, name, children=None):
        self._name = name
        self._children = children or []
        self.element_info = _ElementInfo(name)

    def window_text(self):
        return self._name

    def rectangle(self):
        return _Rectangle()

    def descendants(self):
        return self._children


class _Specification:
    def __init__(self, wrapper):
        self._wrapper = wrapper

    def wrapper_object(self):
        return self._wrapper


class _Desktop:
    point_wrapper = _Wrapper("Cancel")
    active_wrapper = _Wrapper("Settings", [_Wrapper("Save"), _Wrapper("Cancel")])

    def __init__(self, backend):
        assert backend == "uia"

    def from_point(self, x, y):
        return _Specification(self.point_wrapper)

    def get_active(self):
        return _Specification(self.active_wrapper)


class TestSafetyGrounding(unittest.TestCase):
    def setUp(self):
        self.previous_module = sys.modules.get("pywinauto")
        fake_module = types.ModuleType("pywinauto")
        fake_module.Desktop = _Desktop
        sys.modules["pywinauto"] = fake_module

    def tearDown(self):
        if self.previous_module is None:
            sys.modules.pop("pywinauto", None)
        else:
            sys.modules["pywinauto"] = self.previous_module

    def test_labeled_target_mismatch_is_blocked(self):
        reason = UIAutomationGrounder().validate_click_target(50, 30, "Delete account button")

        self.assertIsNotNone(reason)
        self.assertIn("mismatch", reason.lower())
        self.assertIn("Cancel", reason)

    def test_generic_target_is_not_blocked_by_accessibility_gap(self):
        reason = UIAutomationGrounder().validate_click_target(50, 30, "Button")

        self.assertIsNone(reason)

    def test_uia_snapshot_has_explicit_availability(self):
        state = UIAutomationGrounder(max_elements=10).capture_state()

        self.assertTrue(state.is_available)
        self.assertEqual(state.source, "uia")
        self.assertEqual(state.window_title, "Settings")
        self.assertEqual([element.label for element in state.elements], ["Save", "Cancel"])


if __name__ == "__main__":
    unittest.main()
