import time
import unittest
from io import BytesIO
from unittest.mock import MagicMock, patch

import tests.conftest
tests.conftest.init_mocks()

import cogniagent.gui.server as command_server

from cogniagent.gui.control_plane import (
    PairingSession,
    RequestValidationError,
    assess_task_risk,
    default_safety_policy,
    validate_safety_policy,
    validate_settings,
    validate_task,
)


class TestCommandCenterControlPlane(unittest.TestCase):
    def test_json_mutations_require_json_content_type(self):
        handler = object.__new__(command_server.WebUIRequestHandler)
        handler.headers = {"Content-Type": "text/plain", "Content-Length": "2"}
        handler.rfile = BytesIO(b"{}")

        with self.assertRaisesRegex(RequestValidationError, "Content-Type"):
            handler._read_json()

    def test_provider_key_is_runtime_only(self):
        settings, runtime_key = validate_settings(
            {
                "model_type": "openai",
                "model_path": "provider-vision-model",
                "temperature": 0.4,
                "max_steps": 20,
                "api_key": "test-provider-key",
            },
            {
                "model_path": "models/Holo-3.1-4B-abliterated-rdo.Q4_K_M.gguf",
                "temperature": 0.2,
                "max_steps": 15,
                "enable_recording": False,
                "model_type": "local",
            },
        )

        self.assertEqual(runtime_key, "test-provider-key")
        self.assertNotIn("api_key", settings)
        self.assertEqual(settings["model_type"], "openai")
        self.assertEqual(settings["model_path"], "provider-vision-model")
        self.assertEqual(settings["max_steps"], 20)

    def test_invalid_task_is_rejected_before_agent_execution(self):
        with self.assertRaises(RequestValidationError):
            validate_task(" ")

        with self.assertRaises(RequestValidationError):
            validate_task("x" * 12_001)

    def test_high_impact_intent_requires_extra_acknowledgement(self):
        risk = assess_task_risk("Upload the report and send it by email, then delete the local copy.")

        self.assertTrue(risk["requires_explicit_acknowledgement"])
        self.assertIn("sharing or sending data externally", risk["reasons"])
        self.assertIn("deleting or overwriting data", risk["reasons"])

    def test_remote_control_policy_is_strictly_boolean(self):
        with self.assertRaises(RequestValidationError):
            validate_safety_policy({"remote_control_enabled": "yes"}, default_safety_policy())

        policy = validate_safety_policy(
            {"mode": "autonomous", "remote_control_enabled": True},
            default_safety_policy(),
        )
        self.assertEqual(policy["mode"], "autonomous")
        self.assertTrue(policy["remote_control_enabled"])

    def test_pairing_code_is_short_lived_and_constant_time_checked(self):
        pairing = PairingSession(ttl_seconds=1)
        token = pairing.local_payload()["token"]

        self.assertTrue(pairing.verify(token))
        self.assertFalse(pairing.verify("not-the-code"))

        time.sleep(1.05)
        self.assertFalse(pairing.verify(token))

    def test_legacy_api_key_is_removed_during_schema_normalization(self):
        normalized = command_server._normalize_database(
            {
                "active_chat_id": "run-1",
                "chats": [{"id": "run-1", "chat_history": []}],
                "settings": {"api_key": "must-not-persist"},
            }
        )

        self.assertNotIn("api_key", normalized["settings"])

    def test_legacy_planner_scratch_text_is_not_rendered_as_chat(self):
        normalized = command_server._normalize_database(
            {
                "active_chat_id": "run-1",
                "chats": [
                    {
                        "id": "run-1",
                        "chat_history": [
                            {"role": "user", "content": "Open the report"},
                            {"role": "assistant", "content": "Let me analyze the user's intent."},
                            {"role": "assistant", "content": "The plan is ready to review."},
                        ],
                    }
                ],
            }
        )

        self.assertEqual(
            normalized["chats"][0]["chat_history"],
            [
                {"role": "user", "content": "Open the report"},
                {"role": "assistant", "content": "The plan is ready to review."},
            ],
        )

    def test_incomplete_saved_run_is_recovered_as_stopped_on_startup(self):
        database = command_server._normalize_database(
            {
                "active_chat_id": "run-1",
                "chats": [
                    {
                        "id": "run-1",
                        "status": "running",
                        "chat_history": [],
                        "execution": {"status": "thinking", "phase": "perception", "step": 1},
                    }
                ],
            }
        )

        recovered = command_server._recover_interrupted_chats(database)

        self.assertEqual(recovered["chats"][0]["status"], "stopped")
        self.assertEqual(recovered["chats"][0]["execution"]["status"], "stopped")
        self.assertEqual(recovered["chats"][0]["execution"]["step"], 1)

    def test_saved_execution_actions_are_normalized_for_user_facing_copy(self):
        separator = "\u00b7"
        normalized = command_server._normalize_execution_snapshot(
            {
                "status": "done",
                "steps": [
                    {"action": "open_app", "action_text": f"Open app {separator} Notepad", "success": True},
                    {
                        "action": "click",
                        "action_text": f"Click {separator} Open button for Notepad app in the search results",
                        "success": True,
                    },
                    {"action": "type", "action_text": "Enter 23 characters", "success": True},
                    {"action": "terminate", "result": "Completed"},
                ],
            }
        )

        self.assertEqual(
            [step["action_text"] for step in normalized["steps"]],
            ["Open · Notepad", "Open Notepad from search results", "Enter 23 characters", "Finish task"],
        )

    def test_selected_chat_keeps_its_own_execution_while_another_chat_runs(self):
        database = command_server._normalize_database(
            {
                "active_chat_id": "chat-b",
                "chats": [
                    {"id": "chat-a", "title": "Running task", "status": "running", "chat_history": []},
                    {
                        "id": "chat-b",
                        "title": "Finished task",
                        "status": "success",
                        "chat_history": [],
                        "execution": {"status": "done", "phase": "done", "step": 3},
                    },
                ],
            }
        )
        live = {
            "execution_chat_id": "chat-a",
            "status": "thinking",
            "phase": "thinking",
            "phase_started_at": 123.0,
            "step": 1,
            "total_time_ms": 800,
            "current_action": "Reading the screen",
            "current_thought": "",
            "paused": False,
            "steps": [],
            "timing": {},
        }
        handler = object.__new__(command_server.WebUIRequestHandler)
        handler.client_address = ("127.0.0.1", 50000)
        handler.server = type("Server", (), {"server_address": ("127.0.0.1", 8000)})()

        with (
            patch.object(command_server, "load_chats_db", return_value=database),
            patch.object(command_server.gui_app, "get_safe_status", return_value=live),
            patch.object(command_server, "_public_settings", return_value={}),
            patch.object(command_server, "_mobile_status", return_value={}),
        ):
            payload = handler._status_payload()

        self.assertEqual(payload["active_chat_id"], "chat-b")
        self.assertEqual(payload["status"], "done")
        self.assertEqual(payload["step"], 3)
        self.assertEqual(payload["execution_live"]["execution_chat_id"], "chat-a")
        self.assertEqual(payload["execution_live"]["status"], "thinking")

    def test_confirm_cannot_substitute_an_unreviewed_task(self):
        database = {
            "active_chat_id": "run-1",
            "chats": [
                {
                    "id": "run-1",
                    "title": "Quarterly review",
                    "status": "plan_created",
                    "intent": "Summarize the quarterly report.",
                    "reviewed_plan": "Open the report and prepare a concise summary.",
                    "chat_history": [],
                    "current_task": "",
                }
            ],
            "settings": {},
            "safety": default_safety_policy(),
            "audit_events": [],
        }
        handler = object.__new__(command_server.WebUIRequestHandler)
        handler._error = MagicMock()
        handler._json_response = MagicMock()

        with (
            patch.object(command_server, "load_chats_db", return_value=database),
            patch.object(command_server, "_start_agent_task") as start_task,
        ):
            handler._confirm_run(
                {
                    "task": "Delete every report in the folder.",
                    "source_task": "Summarize the quarterly report.",
                    "approved": True,
                    "risk_acknowledged": True,
                }
            )

        handler._error.assert_called_once_with(
            409, "The reviewed plan changed. Refresh it before approval."
        )
        start_task.assert_not_called()

    def test_confirm_executes_original_objective_with_reviewed_plan(self):
        database = {
            "active_chat_id": "run-1",
            "chats": [{
                "id": "run-1", "title": "Write note", "status": "plan_created",
                "intent": "Type the note and leave it open without saving.",
                "reviewed_plan": "1. Open the editor.\n2. Type the note and leave it open.",
                "chat_history": [], "current_task": "",
            }],
            "settings": {"model_type": "local"},
            "safety": default_safety_policy(), "audit_events": [],
        }
        handler = object.__new__(command_server.WebUIRequestHandler)
        handler._error = MagicMock()
        handler._json_response = MagicMock()
        with (
            patch.object(command_server, "load_chats_db", return_value=database),
            patch.object(command_server, "save_chats_db"),
            patch.object(command_server, "_start_agent_task", return_value=True) as start_task,
            patch.object(command_server, "assess_task_risk", return_value={"requires_explicit_acknowledgement": False, "reasons": []}),
        ):
            handler._confirm_run({
                "task": database["chats"][0]["reviewed_plan"],
                "source_task": database["chats"][0]["intent"],
                "approved": True,
            })
        prompt = start_task.call_args.args[0]
        self.assertIn("without saving", prompt)
        self.assertIn("Reviewed plan", prompt)

    def test_legacy_planner_scratch_is_reduced_to_numbered_steps(self):
        dirty = "Thinking Process:\n* Goal: do a thing\n* Step 1: Open the app.\n* Step 2: Verify the result."
        self.assertEqual(command_server._plan_copy(dirty), "1. Open the app.\n2. Verify the result.")

    def test_any_model_authored_plan_can_be_selected(self):
        older = "1. Open the editor.\n2. Type the first draft."
        newer = "1. Open the editor.\n2. Type the revised draft."
        database = {
            "active_chat_id": "run-1",
            "chats": [{
                "id": "run-1", "title": "Draft", "status": "plan_created", "intent": "Draft text",
                "reviewed_plan": newer, "current_task": "", "updated_at": 1,
                "chat_history": [
                    {"role": "assistant", "content": older},
                    {"role": "assistant", "content": newer},
                ],
            }],
            "settings": {}, "safety": default_safety_policy(), "audit_events": [],
        }
        handler = object.__new__(command_server.WebUIRequestHandler)
        handler._error = MagicMock()
        handler._json_response = MagicMock()
        with (
            patch.object(command_server, "load_chats_db", return_value=database),
            patch.object(command_server, "save_chats_db"),
        ):
            handler._select_plan({"chat_id": "run-1", "plan": older})
        self.assertEqual(database["chats"][0]["reviewed_plan"], older)
        handler._json_response.assert_called_once_with({"success": True})

    def test_retry_creates_a_fresh_reviewable_run(self):
        database = {
            "active_chat_id": "run-1",
            "chats": [
                {
                    "id": "run-1",
                    "title": "Quarterly review",
                    "status": "success",
                    "intent": "Summarize the quarterly report.",
                    "reviewed_plan": "Open the report and prepare a concise summary.",
                    "chat_history": [],
                    "current_task": "Open the report and prepare a concise summary.",
                }
            ],
            "settings": {},
            "safety": default_safety_policy(),
            "audit_events": [],
        }
        handler = object.__new__(command_server.WebUIRequestHandler)
        handler._error = MagicMock()
        handler._json_response = MagicMock()
        handler._sync_active_chat = MagicMock()

        with (
            patch.object(command_server, "load_chats_db", return_value=database),
            patch.object(command_server, "save_chats_db"),
            patch.object(command_server.gui_app, "running_thread", None),
        ):
            handler._retry_run()

        self.assertEqual(len(database["chats"]), 2)
        retried = database["chats"][-1]
        self.assertEqual(database["active_chat_id"], retried["id"])
        self.assertEqual(retried["status"], "plan_created")
        self.assertEqual(retried["reviewed_plan"], "Open the report and prepare a concise summary.")
        handler._json_response.assert_called_once_with({"success": True}, 201)


if __name__ == "__main__":
    unittest.main()
