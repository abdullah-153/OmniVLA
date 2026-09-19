"""Unit tests for Compound Macro Actions: click_and_type, compound_action, and multi-tool parsing."""

import unittest
from unittest.mock import patch, MagicMock
import json
import tests.conftest

tests.conftest.init_mocks()

from cogniagent.config import config
from cogniagent.execution.router import ActionRouter
from cogniagent.agent import CogniAgent
from cogniagent.perception.vlm_engine import (
    native_tool_definitions,
    parse_native_tool_call,
    parse_vlm_output,
    ClickAndTypeArgs,
    CompoundActionArgs,
    SubAction,
)


class TestCompoundActions(unittest.TestCase):
    def setUp(self):
        tests.conftest.init_mocks()
        self.router = ActionRouter(config)

    def test_click_and_type_schema_validation(self):
        """ClickAndTypeArgs accepts valid parameters and rejects invalid ones."""
        valid = ClickAndTypeArgs(
            tool_name="click_and_type",
            element="WhatsApp search bar",
            x=250,
            y=120,
            text="Alex",
            submit=True,
            clear_existing=True,
        )
        self.assertEqual(valid.tool_name, "click_and_type")
        self.assertEqual(valid.x, 250)
        self.assertTrue(valid.submit)
        self.assertTrue(valid.clear_existing)

        with self.assertRaises(Exception):
            ClickAndTypeArgs(
                tool_name="click_and_type",
                element="",  # Empty element rejected
                x=500,
                y=500,
                text="hello",
            )

        with self.assertRaises(Exception):
            ClickAndTypeArgs(
                tool_name="click_and_type",
                element="search",
                x=1200,  # Out of bounds coordinate rejected
                y=500,
                text="hello",
            )

    def test_compound_action_schema_validation(self):
        """CompoundActionArgs accepts bounded sub-actions (1 to 5)."""
        sub1 = SubAction(tool_name="click", element="Search", x=200, y=100)
        sub2 = SubAction(tool_name="type", text="Alex", submit=True)
        compound = CompoundActionArgs(tool_name="compound_action", actions=[sub1, sub2])
        self.assertEqual(len(compound.actions), 2)
        self.assertEqual(compound.actions[0].tool_name, "click")
        self.assertEqual(compound.actions[1].text, "Alex")

        # Rejects empty action list
        with self.assertRaises(Exception):
            CompoundActionArgs(tool_name="compound_action", actions=[])

        # Rejects more than 5 actions
        with self.assertRaises(Exception):
            CompoundActionArgs(
                tool_name="compound_action",
                actions=[sub1] * 6,
            )

    def test_native_tool_definitions_includes_compound_tools(self):
        """native_tool_definitions contains click_and_type and compound_action with clean schemas."""
        tools = native_tool_definitions()
        tool_names = [t["function"]["name"] for t in tools]
        self.assertIn("click_and_type", tool_names)
        self.assertIn("compound_action", tool_names)

        # Check click_and_type parameters
        cat_tool = next(t for t in tools if t["function"]["name"] == "click_and_type")
        props = cat_tool["function"]["parameters"]["properties"]
        self.assertIn("element", props)
        self.assertIn("x", props)
        self.assertIn("y", props)
        self.assertIn("text", props)
        self.assertIn("submit", props)
        self.assertIn("clear_existing", props)

        # Check compound_action has inlined items without dangling $defs
        ca_tool = next(t for t in tools if t["function"]["name"] == "compound_action")
        params = ca_tool["function"]["parameters"]
        self.assertNotIn("$defs", params)
        self.assertIn("actions", params["properties"])

    def test_parse_native_tool_call_multi_conversion(self):
        """Multiple native tool calls are packed into a compound_action step."""
        class MockFunction:
            def __init__(self, name, args):
                self.name = name
                self.arguments = json.dumps(args)

        class MockCall:
            def __init__(self, cid, name, args):
                self.id = cid
                self.function = MockFunction(name, args)

        class MockMessage:
            def __init__(self):
                self.tool_calls = [
                    MockCall("call_1", "click", {"element": "Search bar", "x": 300, "y": 150}),
                    MockCall("call_2", "type", {"text": "Alex", "submit": True}),
                ]
                self.reasoning_content = "Need to search contact"

        parsed = parse_native_tool_call(MockMessage())
        self.assertIsNotNone(parsed)
        tool_call = parsed["tool_call"]
        self.assertEqual(tool_call["tool_name"], "compound_action")
        self.assertEqual(len(tool_call["actions"]), 2)
        self.assertEqual(tool_call["actions"][0]["tool_name"], "click")
        self.assertEqual(tool_call["actions"][1]["tool_name"], "type")
        self.assertEqual(tool_call["actions"][1]["text"], "Alex")

    def test_parse_vlm_output_formats(self):
        """parse_vlm_output parses click_and_type and raw actions array."""
        # 1. click_and_type
        payload1 = json.dumps({
            "tool_call": {
                "tool_name": "click_and_type",
                "element": "Search box",
                "x": 200,
                "y": 150,
                "text": "WhatsApp message",
                "submit": True,
            }
        })
        res1 = parse_vlm_output(payload1)
        self.assertIsNotNone(res1)
        self.assertEqual(res1["tool_call"]["tool_name"], "click_and_type")
        self.assertEqual(res1["tool_call"]["text"], "WhatsApp message")

        # 2. Raw actions array format
        payload2 = json.dumps({
            "actions": [
                {"tool_name": "click", "element": "Chat input", "x": 400, "y": 900},
                {"tool_name": "type", "text": "Hello world", "submit": False},
            ]
        })
        res2 = parse_vlm_output(payload2)
        self.assertIsNotNone(res2)
        self.assertEqual(res2["tool_call"]["tool_name"], "compound_action")
        self.assertEqual(len(res2["tool_call"]["actions"]), 2)

    @patch("cogniagent.execution.win32_input.mouse_click")
    @patch("cogniagent.execution.win32_input.type_text")
    @patch("cogniagent.execution.win32_input.key_press")
    @patch("cogniagent.execution.win32_input.hotkey")
    @patch("cogniagent.execution.win32_input.paste_text_preserving_clipboard", return_value=True)
    def test_execute_click_and_type(self, mock_paste, mock_hotkey, mock_key, mock_type, mock_click):
        """ActionRouter executes click, clear, text paste, and Enter for click_and_type."""
        vlm_result = {
            "parsed_action": {
                "tool_name": "click_and_type",
                "element": "Search bar",
                "x": 500,
                "y": 500,
                "text": "Alex",
                "submit": True,
                "clear_existing": True,
            },
            "screen_origin": (0, 0),
        }
        res = self.router.execute_vlm_action(vlm_result, (1920, 1080))
        self.assertTrue(res["success"])
        self.assertIn("Clicked [960, 540]", res["detail"])
        self.assertIn("Cleared existing text", res["detail"])
        self.assertIn("Typed 4 character(s)", res["detail"])
        self.assertIn("Pressed Enter", res["detail"])

        mock_click.assert_called_once_with(960, 540)
        mock_hotkey.assert_called_once_with("ctrl", "a")
        mock_paste.assert_called_once_with("Alex")
        mock_key.assert_any_call("backspace")
        mock_key.assert_any_call("enter")

    @patch("cogniagent.execution.win32_input.mouse_click")
    @patch("cogniagent.execution.win32_input.paste_text_preserving_clipboard", return_value=True)
    def test_execute_compound_action(self, mock_paste, mock_click):
        """ActionRouter executes sequential sub-actions in compound_action."""
        vlm_result = {
            "parsed_action": {
                "tool_name": "compound_action",
                "actions": [
                    {"tool_name": "click", "element": "Input", "x": 250, "y": 250},
                    {"tool_name": "type", "text": "Report", "submit": False},
                ],
            },
            "screen_origin": (0, 0),
        }
        res = self.router.execute_vlm_action(vlm_result, (1920, 1080))
        self.assertTrue(res["success"])
        self.assertIn("[1] Clicked [480, 270]", res["detail"])
        self.assertIn("[2] Typed 6 character(s)", res["detail"])
        mock_click.assert_called_once_with(480, 270)
        mock_paste.assert_called_once_with("Report")

    def test_assess_action_risk_detects_compound_risks(self):
        """assess_action_risk flags destructive or financial operations in compound actions."""
        # 1. click_and_type risk
        risky_cat = {
            "tool_name": "click_and_type",
            "element": "Confirm delete record",
            "x": 500,
            "y": 500,
            "text": "DELETE",
        }
        risk1 = self.router.assess_action_risk(risky_cat)
        self.assertIsNotNone(risk1)
        self.assertIn("destructive change", risk1["reasons"])

        # 2. compound_action risk
        risky_compound = {
            "tool_name": "compound_action",
            "actions": [
                {"tool_name": "click", "element": "Ordinary navigation tab", "x": 100, "y": 100},
                {"tool_name": "click", "element": "Send payment checkout button", "x": 300, "y": 400},
            ],
        }
        risk2 = self.router.assess_action_risk(risky_compound)
        self.assertIsNotNone(risk2)
        self.assertIn("financial commitment", risk2["reasons"])

    def test_action_signature_for_compound_actions(self):
        """action_signature generates unique signatures for repeat detection."""
        cat_action = {
            "parsed_action": {
                "tool_name": "click_and_type",
                "element": "Search",
                "x": 250,
                "y": 120,
                "text": "Alex",
                "submit": True,
            }
        }
        sig = self.router.action_signature(cat_action)
        self.assertIsNotNone(sig)
        self.assertTrue(sig.startswith("click_and_type:250:100:4:"))

        compound_action = {
            "parsed_action": {
                "tool_name": "compound_action",
                "actions": [
                    {"tool_name": "click", "element": "Search", "x": 250, "y": 120},
                    {"tool_name": "key_press", "key": "enter"},
                ],
            }
        }
        csig = self.router.action_signature(compound_action)
        self.assertIsNotNone(csig)
        self.assertTrue(csig.startswith("compound:click:"))
        self.assertIn("key:enter", csig)

    def test_agent_display_and_memory_formatting(self):
        """CogniAgent formats compound actions safely for display and memory."""
        cat_action = {
            "tool_name": "click_and_type",
            "element": "Contact Search",
            "x": 200,
            "y": 100,
            "text": "Alex",
            "submit": True,
        }
        display = CogniAgent._display_action(cat_action)
        self.assertEqual(display, "Type 4 chars into 'Contact Search' (+Enter)")

        memory_str = CogniAgent._memory_action(cat_action)
        memory_json = json.loads(memory_str)
        self.assertNotIn("text", memory_json)  # Text masked for privacy
        self.assertEqual(memory_json["characters"], 4)

        ca_action = {
            "tool_name": "compound_action",
            "actions": [
                {"tool_name": "click", "element": "Search bar", "x": 100, "y": 100},
                {"tool_name": "type", "text": "secret123"},
            ],
        }
        ca_display = CogniAgent._display_action(ca_action)
        self.assertIn("Compound (2)", ca_display)

        ca_memory = json.loads(CogniAgent._memory_action(ca_action))
        self.assertNotIn("text", ca_memory["actions"][1])
        self.assertEqual(ca_memory["actions"][1]["characters"], 9)


if __name__ == "__main__":
    unittest.main()
