"""Focused tests for deterministic computer-use safety guards and coordinate boundaries."""

import unittest
from unittest.mock import patch
import tests.conftest

tests.conftest.init_mocks()

from cogniagent.config import config
from cogniagent.execution.router import ActionRouter
from cogniagent.agent import CogniAgent
from cogniagent.perception.vlm_engine import recent_execution_feedback


class TestSafetyGrounding(unittest.TestCase):
    def setUp(self):
        tests.conftest.init_mocks()
        self.router = ActionRouter(config)

    def test_out_of_bounds_coordinates_are_blocked(self):
        """Coordinates outside [0, 1000] are blocked deterministically."""
        action = {"tool_name": "click", "x": 1500, "y": 500}
        coords, error = self.router.resolve_click_coordinates(action, (1920, 1080), (0, 0))
        self.assertIsNone(coords)
        self.assertIsNotNone(error)
        self.assertIn("range [0, 1000]", error)


    def test_negative_coordinates_are_blocked(self):
        """Negative coordinates are rejected immediately."""
        action = {"tool_name": "click", "x": -50, "y": 200}
        coords, error = self.router.resolve_click_coordinates(action, (1920, 1080), (0, 0))
        self.assertIsNone(coords)
        self.assertIsNotNone(error)

    def test_valid_normalized_coordinates_scale_properly(self):
        """Valid normalized [0, 1000] coordinates map to absolute screen pixels."""
        action = {"tool_name": "click", "x": 500, "y": 500}
        coords, error = self.router.resolve_click_coordinates(action, (1920, 1080), (0, 0))
        self.assertIsNone(error)
        self.assertEqual(coords, (960, 540))

    def test_banned_shortcuts_are_blocked(self):
        """Destructive system shortcuts are blocked."""
        vlm_result = {
            "action_desp": "key_press",
            "parsed_action": {"tool_name": "key_press", "key": "alt+f4"},
            "orig_dims": (1920, 1080),
        }
        res = self.router.execute_vlm_action(vlm_result, (1920, 1080))
        self.assertFalse(res["success"])
        self.assertIn("Banned shortcut blocked", res["detail"])

    def test_consequential_visible_target_requires_just_in_time_review(self):
        risk = self.router.assess_action_risk(
            {"tool_name": "click", "element": "Send payment now", "x": 500, "y": 500}
        )
        self.assertIsNotNone(risk)
        self.assertIn("financial commitment", risk["reasons"])

    def test_ordinary_navigation_target_does_not_trigger_approval(self):
        self.assertIsNone(
            self.router.assess_action_risk(
                {"tool_name": "click", "element": "Reports navigation tab", "x": 500, "y": 500}
            )
        )

    def test_nearby_failed_clicks_share_a_repeat_signature(self):
        first = {
            "parsed_action": {"tool_name": "click", "element": "Start button in the taskbar", "x": 122, "y": 954}
        }
        nearby = {
            "parsed_action": {"tool_name": "click", "element": "Windows Start button", "x": 119, "y": 961}
        }

        self.assertEqual(self.router.action_signature(first), self.router.action_signature(nearby))

    def test_text_tasks_require_verified_typing_before_completion(self):
        self.assertEqual(
            CogniAgent._required_action_evidence('1. Open Notepad. 2. Type "hello" into the document.'),
            {"type"},
        )
        self.assertEqual(CogniAgent._required_action_evidence("Open Calculator."), set())

    def test_step_budget_scales_with_reviewed_plan(self):
        plan = "1. Open the app.\n2. Find the document.\n3. Edit it.\n4. Verify the result."
        self.assertEqual(CogniAgent._dynamic_step_budget(self.router, plan, 60), 30)
        self.assertEqual(CogniAgent._dynamic_step_budget(self.router, plan, 15), 15)

    def test_search_result_action_is_described_as_an_outcome(self):
        self.assertEqual(
            CogniAgent._display_action(
                {
                    "tool_name": "click",
                    "element": "Open button for Notepad app in the search results",
                }
            ),
            "Open Notepad from search results",
        )

    def test_recent_tool_failures_are_repeated_beside_the_newest_screen(self):
        feedback = recent_execution_feedback([
            {"role": "tool", "content": '{"success":true,"detail":"Notepad opened"}'},
            {"role": "tool", "content": '{"success":false,"detail":"No visible screen change"}'},
        ])
        self.assertIn("Succeeded: Notepad opened", feedback)
        self.assertIn("Failed: No visible screen change", feedback)

    @patch("cogniagent.execution.router.time.sleep", return_value=None)
    @patch("cogniagent.execution.router.win32_input.type_text")
    @patch("cogniagent.execution.router.win32_input.key_press")
    def test_open_app_uses_semantic_windows_search(self, key_press, type_text, _sleep):
        result = self.router.execute_vlm_action(
            {
                "action_desp": "open_app",
                "parsed_action": {"tool_name": "open_app", "app_name": "Notepad"},
                "screen_origin": (0, 0),
            },
            (1920, 1080),
        )

        self.assertTrue(result["success"])
        self.assertEqual(key_press.call_args_list[0].args, ("win",))
        self.assertEqual(key_press.call_args_list[1].args, ("enter",))
        type_text.assert_called_once_with(
            "Notepad",
            interval=min(config.execution.typing_interval, 0.03),
        )


if __name__ == "__main__":
    unittest.main()
