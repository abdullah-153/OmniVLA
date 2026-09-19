"""Regression checks for the constrained local-inference performance profile."""

import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

from cogniagent.config import config
from cogniagent.gui.server_manager import (
    build_planner_messages,
    build_planner_server_command,
    build_vla_server_command,
    extract_planner_output,
)
from cogniagent.perception.vlm_engine import (
    checkpoint_execution_context,
    compact_execution_history,
    configured_output_tokens,
)
import cogniagent.gui.app as gui_app
import cogniagent.gui.server_manager as server_manager


class TestPerformanceProfile(unittest.TestCase):
    def setUp(self):
        self.previous_context_size = config.llm.context_size

    def tearDown(self):
        config.llm.context_size = self.previous_context_size

    def test_vla_uses_one_slot_and_a_bounded_context(self):
        config.llm.context_size = 8192
        command = build_vla_server_command("models/holo.gguf", "28")

        self.assertEqual(command[command.index("-np") + 1], "1")
        self.assertEqual(command[command.index("-c") + 1], "6144")
        self.assertIn("--cache-prompt", command)
        self.assertNotIn("--cache-ram", command)
        self.assertEqual(command[command.index("--reasoning") + 1], "on")
        self.assertEqual(command[command.index("--reasoning-format") + 1], "deepseek")
        self.assertEqual(command[command.index("--image-min-tokens") + 1], "1536")
        self.assertEqual(command[command.index("--image-max-tokens") + 1], "2048")
        self.assertNotIn("--chat-template", command)

    def test_cpu_critic_profile_has_one_short_slot(self):
        command = build_planner_server_command("models/critic.gguf", "0")

        self.assertEqual(command[command.index("-ngl") + 1], "0")
        self.assertEqual(command[command.index("--device") + 1], "none")
        self.assertIn("--no-kv-offload", command)
        self.assertIn("--no-op-offload", command)
        self.assertEqual(command[command.index("-np") + 1], "1")
        self.assertEqual(command[command.index("-c") + 1], "2048")
        self.assertEqual(command[command.index("--reasoning") + 1], "off")
        self.assertIn("--cache-prompt", command)
        self.assertEqual(command[command.index("--batch-size") + 1], "512")
        self.assertEqual(command[command.index("--ubatch-size") + 1], "256")

    def test_planner_output_never_leaks_private_reasoning(self):
        raw = "<think>private analysis</think>\n1. Inspect the current state.\n2. Complete and verify the task."
        self.assertEqual(
            extract_planner_output(raw),
            "1. Inspect the current state.\n2. Complete and verify the task.",
        )

    def test_planner_history_is_bounded_without_losing_the_latest_request(self):
        history = [
            {"role": "user" if index % 2 == 0 else "assistant", "content": f"message-{index} " + ("x" * 2000)}
            for index in range(20)
        ]
        latest = "create a concise note"

        messages = build_planner_messages("system", latest, history)

        self.assertEqual(messages[0], {"role": "system", "content": "system"})
        self.assertEqual(messages[-1], {"role": "user", "content": latest})
        self.assertLessEqual(sum(len(item["content"]) for item in messages[1:]), 4200)

    @patch.object(server_manager, "stop_planner_server")
    @patch.object(server_manager, "start_planner_server", return_value=True)
    @patch.object(server_manager.requests, "post")
    def test_planner_is_released_after_a_successful_request(self, post, _start, stop):
        response = Mock(status_code=200)
        response.json.return_value = {
            "choices": [{"message": {"content": "1. Inspect the current state.\n2. Complete the task."}}]
        }
        post.return_value = response

        result = server_manager.run_planner_chat("do the task", [])

        self.assertEqual(result, "1. Inspect the current state.\n2. Complete the task.")
        stop.assert_called_once_with()

    def test_visual_runtime_stop_releases_its_active_profile(self):
        previous = (
            server_manager.server_process,
            server_manager.active_vla_model,
            server_manager.active_vla_max_gpu,
            server_manager.active_vla_cuda,
        )
        try:
            server_manager.server_process = None
            server_manager.active_vla_model = "models/holo.gguf"
            server_manager.active_vla_max_gpu = True
            server_manager.active_vla_cuda = True
            with patch.object(server_manager, "kill_port_owner") as kill:
                profile = server_manager.stop_vla_server()

            self.assertEqual(profile, ("models/holo.gguf", True))
            self.assertIsNone(server_manager.active_vla_model)
            self.assertIsNone(server_manager.active_vla_max_gpu)
            self.assertFalse(server_manager.active_vla_cuda)
            kill.assert_called_once_with(8089)
        finally:
            (
                server_manager.server_process,
                server_manager.active_vla_model,
                server_manager.active_vla_max_gpu,
                server_manager.active_vla_cuda,
            ) = previous

    @patch.object(server_manager, "stop_planner_server")
    @patch.object(server_manager, "start_planner_server", return_value=True)
    @patch.object(server_manager.requests, "post", side_effect=TimeoutError("planner timeout"))
    def test_planner_is_released_after_a_failed_request(self, _post, _start, stop):
        with self.assertRaises(TimeoutError):
            server_manager.run_planner_chat("do the task", [])

        stop.assert_called_once_with()

    def test_checkpoint_removes_embedded_screenshot_payloads(self):
        messages = [
            {"role": "system", "content": "stable system"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "old screen"},
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,very-large"}},
                ],
            },
        ]

        checkpoint = checkpoint_execution_context(messages)
        image_chunks = [
            chunk
            for message in checkpoint
            if isinstance(message.get("content"), list)
            for chunk in message["content"]
            if chunk.get("type") == "image_url"
        ]

        self.assertEqual(image_chunks, [])
        self.assertIn("[screenshot evicted]", checkpoint[1]["content"][1]["text"])

    def test_context_compaction_retains_an_explicit_eviction_marker(self):
        messages = [{"role": "system", "content": "stable system"}]
        messages.extend({"role": "user", "content": f"event {index}"} for index in range(14))

        compact_execution_history(messages, max_non_system_messages=6)

        self.assertLessEqual(len(messages), 8)
        self.assertIn("[screenshot evicted]", messages[1]["content"][0]["text"])
        self.assertEqual(messages[-1]["content"], "event 13")

    def test_action_output_cap_reserves_reasoning_and_remains_bounded(self):
        self.assertEqual(configured_output_tokens(384), 384)
        self.assertEqual(configured_output_tokens(50), 256)
        self.assertEqual(configured_output_tokens(9999), 512)

    def test_status_poll_can_exclude_all_screenshot_payloads(self):
        previous = deepcopy(gui_app.agent_status)
        try:
            gui_app.agent_status["latest_screenshot_b64"] = "large-frame"
            gui_app.agent_status["steps"] = [{"step": 1, "screenshot_b64": "step-frame"}]
            status = gui_app.get_safe_status(include_media=False)
            self.assertNotIn("latest_screenshot_b64", status)
            self.assertNotIn("screenshot_b64", status["steps"][0])
        finally:
            gui_app.agent_status.clear()
            gui_app.agent_status.update(previous)


if __name__ == "__main__":
    unittest.main()
