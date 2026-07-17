import time
import unittest
from unittest.mock import MagicMock, patch

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
            409, "The reviewed runbook changed. Refresh it before approval."
        )
        start_task.assert_not_called()

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
