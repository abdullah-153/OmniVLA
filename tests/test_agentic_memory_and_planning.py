"""Tests for lifetime user preferences, agentic planning, and dynamic step guardrails."""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from cogniagent.agent import CogniAgent
from cogniagent.memory.user_profile import UserProfileMemory
from cogniagent.gui.server_manager import parse_agentic_plan, extract_planner_output
from cogniagent.gui import server as command_server


class TestUserProfileMemory(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.memory = UserProfileMemory(storage_dir=self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_default_user_profile_initialization(self):
        data = self.memory.to_dict()
        self.assertEqual(data["preferences"]["email"]["account"], "")
        self.assertEqual(data["preferences"]["browser"]["default"], "")
        self.assertEqual(data["facts"], [])

    def test_planner_context_includes_email_preference(self):
        self.memory.update_preference("email", "account", "owner@example.invalid")
        self.memory.update_preference("email", "service", "Outlook")
        ctx = self.memory.get_planner_context()
        self.assertIn("owner@example.invalid", ctx)
        self.assertIn("Outlook", ctx)
        self.assertNotIn("Do NOT open desktop Outlook", ctx)

    def test_vla_context_includes_guidance(self):
        self.memory.update_preference("browser", "default", "Firefox")
        vla = self.memory.get_vla_context()
        self.assertIn("Firefox", vla)
        self.assertIn("Current user instructions override", vla)

    def test_update_preference_persists(self):
        self.memory.update_preference("browser", "default", "Google Chrome")
        reloaded = UserProfileMemory(storage_dir=self.temp_dir)
        self.assertEqual(reloaded.to_dict()["preferences"]["browser"]["default"], "Google Chrome")

    def test_add_and_remove_fact(self):
        added = self.memory.add_fact("Always download PDFs to Desktop.")
        self.assertTrue(added)
        self.assertIn("Always download PDFs to Desktop.", self.memory.to_dict()["facts"])

        # Remove the fact
        idx = len(self.memory.to_dict()["facts"]) - 1
        removed = self.memory.remove_fact(idx)
        self.assertTrue(removed)
        self.assertNotIn("Always download PDFs to Desktop.", self.memory.to_dict()["facts"])

    def test_learn_from_task_reinforces_gmail(self):
        self.memory.learn_from_task(
            intent="check my gmail messages",
            steps=[
                {"action_text": "Use · First search result Gmail - ak1399er@gmail.com", "note": "viewing inbox"}
            ],
            status="success",
            summary="Checked unread messages",
        )
        self.assertEqual(self.memory.to_dict()["preferences"]["email"]["account"], "")
        self.assertEqual(len(self.memory.to_dict()["workflows"]), 1)

    def test_learn_from_message_extracts_name_and_facts(self):
        learned = self.memory.learn_from_message("Hello, my name is Abdullah and remember that my downloads folder is D:\\Downloads.")
        self.assertTrue(len(learned) >= 1)
        data = self.memory.to_dict()
        self.assertEqual(data["user_name"], "Abdullah")
        self.assertTrue(any("downloads" in f.lower() for f in data["facts"]))

    def test_learn_from_message_extracts_browser_and_negative_constraints(self):
        learned = self.memory.learn_from_message("I prefer Chrome as my browser and never use outlook.")
        self.assertTrue(len(learned) >= 1)
        data = self.memory.to_dict()
        self.assertEqual(data["preferences"]["browser"]["default"], "Google Chrome")
        self.assertTrue(any("outlook" in f.lower() for f in data["facts"]))


class TestAgenticPlanParser(unittest.TestCase):
    def test_parse_structured_agentic_plan(self):
        raw = (
            "<think>Thinking about email check...</think>\n"
            "Using your preferred Gmail (ak1399er@gmail.com) via Microsoft Edge.\n\n"
            "1. Open Microsoft Edge and navigate to Gmail.\n"
            "2. Locate unread emails in the primary inbox.\n"
            "3. Inspect subjects and senders.\n\n"
            "**Expected Output:** Structured list of unread email senders and subject lines.\n"
            "Prescribed Steps: 35"
        )
        parsed = parse_agentic_plan(raw)
        self.assertTrue(parsed["has_plan"])
        self.assertIn("Using your preferred Gmail", parsed["preface"])
        self.assertEqual(len(parsed["steps"]), 3)
        self.assertEqual(parsed["prescribed_steps"], 35)
        self.assertIn("Structured list of unread email senders", parsed["expected_output"])
        self.assertIn("**Expected Output:**", parsed["formatted"])
        self.assertIn("1. Open Microsoft Edge and navigate to Gmail.", parsed["formatted"])

    def test_parse_conversational_response_without_plan(self):
        raw = "Hello! I am your personal desktop assistant. How can I help you today?"
        parsed = parse_agentic_plan(raw)
        self.assertFalse(parsed["has_plan"])
        self.assertEqual(parsed["steps"], [])
        self.assertEqual(parsed["steps_text"], "")
        self.assertEqual(parsed["formatted"], raw)

    def test_parse_plan_with_desktop_plan_fence(self):
        raw = (
            "I'll help you organize your downloaded receipts.\n\n"
            "```desktop-plan\n"
            "1. Open File Explorer to Downloads.\n"
            "2. Move PDF receipts to Documents.\n"
            "**Expected Output:** Receipts sorted in Documents.\n"
            "Prescribed Steps: 30\n"
            "```"
        )
        parsed = parse_agentic_plan(raw)
        self.assertTrue(parsed["has_plan"])
        self.assertEqual(len(parsed["steps"]), 2)
        self.assertEqual(parsed["prescribed_steps"], 30)
        self.assertIn("Receipts sorted in Documents.", parsed["expected_output"])

    def test_extract_planner_output_backward_compatibility(self):
        raw = (
            "<think>internal</think>\n"
            "1. Inspect active window.\n"
            "2. Click the target button."
        )
        clean = extract_planner_output(raw)
        self.assertEqual(clean, "1. Inspect active window.\n2. Click the target button.")

    def test_parse_agentic_plan_generous_default_overestimation(self):
        raw = (
            "1. Open the browser.\n"
            "2. Navigate to dashboard."
        )
        parsed = parse_agentic_plan(raw)
        self.assertTrue(parsed["has_plan"])
        # Should overestimate to at least 30 steps
        self.assertGreaterEqual(parsed["prescribed_steps"], 30)

    def test_planner_model_configured_to_spark(self):
        from cogniagent.config import config
        self.assertIn("Spark-X2.5-4B", config.llm.planner_model)


class TestDynamicStepBudget(unittest.TestCase):
    def setUp(self):
        self.agent = CogniAgent()

    def test_requested_steps_respected_directly(self):
        budget = self.agent.resolve_step_budget("1. Step A\n2. Step B", requested_steps=45)
        self.assertEqual(budget, 45)

    def test_requested_steps_bounded_by_safety_ceiling(self):
        budget = self.agent.resolve_step_budget("1. Step A\n2. Step B", requested_steps=200)
        self.assertEqual(budget, 60)

    def test_default_budget_scales_with_plan(self):
        budget = self.agent.resolve_step_budget("1. Step A\n2. Step B", requested_steps=None)
        # 2 plan items -> 2 * 6 + 6 = 18
        self.assertEqual(budget, 18)

    def test_dynamic_step_budget_formula(self):
        plan = "1. Step A\n2. Step B\n3. Step C\n4. Step D"
        self.assertEqual(self.agent._dynamic_step_budget(plan, 60), 30)
        self.assertEqual(self.agent._dynamic_step_budget(plan, 15), 15)


class TestControlPlaneProfileAndSteps(unittest.TestCase):
    def setUp(self):
        self.handler = command_server.WebUIRequestHandler.__new__(command_server.WebUIRequestHandler)
        self.handler.client_address = ("127.0.0.1", 54321)
        self.handler.headers = {"Origin": "http://127.0.0.1:8088", "Host": "127.0.0.1:8088"}

    def test_confirm_passes_max_steps_to_start_task(self):
        database = {
            "active_chat_id": "run-1",
            "safety": {"mode": "supervised", "require_plan_approval": True},
            "chats": [{
                "id": "run-1",
                "title": "Check email",
                "intent": "check email",
                "status": "plan_created",
                "reviewed_plan": "1. Open Gmail.\n2. Read inbox.",
                "chat_history": [
                    {"role": "user", "content": "check email"},
                    {"role": "assistant", "content": "1. Open Gmail.\n2. Read inbox."},
                ],
                "execution": None,
            }],
        }
        with (
            patch.object(command_server, "load_chats_db", return_value=database),
            patch.object(command_server, "save_chats_db"),
            patch.object(command_server.gui_app, "agent_status", {"settings": {"model_type": "local"}}),
            patch.object(command_server, "_start_agent_task", return_value=True) as mock_start,
            patch.object(command_server, "assess_task_risk", return_value={"requires_explicit_acknowledgement": False, "reasons": []}),
            patch.object(self.handler, "_json_response") as mock_resp,
        ):
            self.handler._confirm_run({
                "task": "1. Open Gmail.\n2. Read inbox.",
                "source_task": "check email",
                "approved": True,
                "max_steps": 45,
            })
            self.assertTrue(mock_start.called)
            run_policy = mock_start.call_args.args[1]
            self.assertEqual(run_policy.get("max_steps"), 30)  # Stored planner budget, not client override.


if __name__ == "__main__":
    unittest.main()
