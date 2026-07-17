"""Regression checks for the constrained local-inference performance profile."""

import unittest

from cogniagent.config import config
from cogniagent.gui.server_manager import (
    build_planner_server_command,
    build_vla_server_command,
)
from cogniagent.perception.vlm_engine import (
    checkpoint_execution_context,
    compact_execution_history,
    configured_output_tokens,
)


class TestPerformanceProfile(unittest.TestCase):
    def setUp(self):
        self.previous_context_size = config.llm.context_size

    def tearDown(self):
        config.llm.context_size = self.previous_context_size

    def test_vla_uses_one_slot_and_a_bounded_context(self):
        config.llm.context_size = 8192
        command = build_vla_server_command("models/holo.gguf", "28")

        self.assertEqual(command[command.index("-np") + 1], "1")
        self.assertEqual(command[command.index("-c") + 1], "4096")
        self.assertIn("--cache-prompt", command)

    def test_cpu_critic_profile_has_one_short_slot(self):
        command = build_planner_server_command("models/critic.gguf", "0")

        self.assertEqual(command[command.index("-ngl") + 1], "0")
        self.assertEqual(command[command.index("-np") + 1], "1")
        self.assertEqual(command[command.index("-c") + 1], "2048")

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
        self.assertIn("[screenshot evicted]", messages[1]["content"])
        self.assertEqual(messages[-1]["content"], "event 13")

    def test_action_output_cap_stays_small_and_valid(self):
        self.assertEqual(configured_output_tokens(320), 320)
        self.assertEqual(configured_output_tokens(50), 96)
        self.assertEqual(configured_output_tokens(9999), 512)


if __name__ == "__main__":
    unittest.main()
