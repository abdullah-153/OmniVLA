import sys
import unittest
from unittest.mock import patch, MagicMock

# Mock missing modules before they can be imported
import tests.mocks.mock_states as mock_states
sys.modules['cogniagent.perception.state'] = mock_states
sys.modules['cogniagent.reasoning.action_reasoner'] = mock_states

# Import the modules under test
from cogniagent.config import config
from cogniagent.perception.vlm_engine import VLMEngine, trim_to_last_n_images
import cogniagent.agent

class TestMilestone2(unittest.TestCase):
    def test_config_base_url(self):
        """Verify the default config base URL is correct."""
        self.assertEqual(config.llm.base_url, "http://127.0.0.1:8089/v1")

    @patch('mss.mss')
    @patch('cogniagent.perception.vlm_engine.OpenAI')
    def test_vlm_engine_default_endpoint(self, mock_openai, mock_mss):
        """Verify VLMEngine endpoints target http://127.0.0.1:8089/v1 by default."""
        mock_mss_instance = MagicMock()
        mock_mss_instance.monitors = [{"dummy": "monitor"}, {"dummy": "monitor_1"}]
        mock_mss.return_value = mock_mss_instance
        
        vlm = VLMEngine()
        
        self.assertEqual(vlm.endpoint, "http://127.0.0.1:8089/v1")
        self.assertEqual(vlm.model_name, "models/Holo-3.1-4B-abliterated-rdo.Q4_K_M.gguf")
        
        mock_openai.assert_called_once_with(base_url="http://127.0.0.1:8089/v1", api_key="antigravity")

    @patch('mss.mss')
    @patch('cogniagent.perception.vlm_engine.OpenAI')
    def test_vlm_engine_custom_endpoint(self, mock_openai, mock_mss):
        """Verify VLMEngine respects custom endpoint and model name."""
        mock_mss_instance = MagicMock()
        mock_mss_instance.monitors = [{"dummy": "monitor"}, {"dummy": "monitor_1"}]
        mock_mss.return_value = mock_mss_instance
        
        vlm = VLMEngine(endpoint="http://127.0.0.1:9000/v1", model_name="custom_model")
        
        self.assertEqual(vlm.endpoint, "http://127.0.0.1:9000/v1")
        self.assertEqual(vlm.model_name, "custom_model")
        mock_openai.assert_called_once_with(base_url="http://127.0.0.1:9000/v1", api_key="antigravity")

    def test_trim_to_last_n_images(self):
        """Verify trim_to_last_n_images keeps only the latest 3 screenshots and evicts older ones."""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "<observation>\n"},
                    {"type": "image_url", "image_url": {"url": "dummy_1"}},
                    {"type": "text", "text": "\n</observation>"},
                ]
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "<observation>\n"},
                    {"type": "image_url", "image_url": {"url": "dummy_2"}},
                    {"type": "text", "text": "\n</observation>"},
                ]
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "<observation>\n"},
                    {"type": "image_url", "image_url": {"url": "dummy_3"}},
                    {"type": "text", "text": "\n</observation>"},
                ]
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "<observation>\n"},
                    {"type": "image_url", "image_url": {"url": "dummy_4"}},
                    {"type": "text", "text": "\n</observation>"},
                ]
            },
        ]
        
        trim_to_last_n_images(messages, n=3)
        
        self.assertEqual(messages[0]["content"][0]["text"], "<observation>\n")
        self.assertEqual(messages[0]["content"][1]["type"], "text")
        self.assertEqual(messages[0]["content"][1]["text"], "[screenshot evicted]")
        self.assertNotIn("image_url", messages[0]["content"][1])
        self.assertEqual(messages[0]["content"][2]["text"], "\n</observation>")
        
        self.assertEqual(messages[1]["content"][1]["type"], "image_url")
        self.assertEqual(messages[1]["content"][1]["image_url"]["url"], "dummy_2")
        
        self.assertEqual(messages[2]["content"][1]["type"], "image_url")
        self.assertEqual(messages[2]["content"][1]["image_url"]["url"], "dummy_3")
        
        self.assertEqual(messages[3]["content"][1]["type"], "image_url")
        self.assertEqual(messages[3]["content"][1]["image_url"]["url"], "dummy_4")

    @patch('mss.mss')
    @patch('cogniagent.perception.vlm_engine.OpenAI')
    def test_vlm_engine_retry_and_cleaning(self, mock_openai, mock_mss):
        """Verify VLMEngine reason() method handles retries and markdown code blocks."""
        mock_mss_instance = MagicMock()
        mock_mss_instance.monitors = [{"dummy": "monitor"}, {"dummy": "monitor_1"}]
        mock_mss.return_value = mock_mss_instance
        
        vlm = VLMEngine()
        
        vlm.capture_screen = MagicMock(return_value=(MagicMock(), (1920, 1080)))
        vlm.encode_screenshot = MagicMock(return_value="dummy_base64")
        
        mock_choice_1 = MagicMock()
        mock_choice_1.message.content = "invalid json response"
        
        mock_choice_2 = MagicMock()
        mock_choice_2.message.content = '```json\n{\n  "note": "retrieved value",\n  "thought": "clicking start",\n  "tool_call": {\n    "tool_name": "click",\n    "element": "start button",\n    "x": 500,\n    "y": 500\n  }\n}\n```'
        
        mock_completion_1 = MagicMock()
        mock_completion_1.choices = [mock_choice_1]
        
        mock_completion_2 = MagicMock()
        mock_completion_2.choices = [mock_choice_2]
        
        mock_openai_instance = mock_openai.return_value
        mock_openai_instance.chat.completions.create.side_effect = [
            mock_completion_1,
            mock_completion_2
        ]
        
        messages = []
        result = vlm.reason("open app", messages)
        
        self.assertIsNotNone(result)
        self.assertEqual(result["think"], "clicking start")
        self.assertEqual(result["action_desp"], "click")
        
        self.assertEqual(mock_openai_instance.chat.completions.create.call_count, 2)
        
        first_call_kwargs = mock_openai_instance.chat.completions.create.call_args_list[0][1]
        self.assertEqual(first_call_kwargs["response_format"], {"type": "json_object"})

    @patch('cogniagent.agent.VLMEngine')
    @patch('cogniagent.agent.ActionRouter')
    @patch('cogniagent.agent.EpisodicMemory')
    @patch('cogniagent.agent.ScreenVerifier')
    def test_run_task_wraps_tool_output_in_observation(self, mock_verifier, mock_memory, mock_router, mock_vlm):
        """Verify that tool outputs in CogniAgent.run_task are wrapped in <observation> tags."""
        import numpy as np
        from cogniagent.agent import CogniAgent

        agent = CogniAgent()

        # Mock VLM Engine methods
        agent.vlm.capture_screen = MagicMock(return_value=(np.zeros((10, 10, 3), dtype=np.uint8), (1920, 1080)))
        
        vlm_result = {
            "think": "Let's click the button",
            "action_desp": "click",
            "action_call": "click(500, 500)",
            "orig_dims": (1920, 1080),
            "screenshot": np.zeros((10, 10, 3), dtype=np.uint8),
            "parsed_action": {"text": "click"}
        }
        agent.vlm.reason = MagicMock(return_value=vlm_result)

        # Mock Router execution to return is_done=False on the first step, then is_done=True on the second step
        agent.executor.execute_vlm_action = MagicMock(side_effect=[
            {"success": True, "detail": "Clicked start button", "is_done": False},
            {"success": True, "detail": "Done", "is_done": True}
        ])

        # Mock Verifier
        agent.verifier.compute_screen_diff = MagicMock(return_value={"changed": True})
        agent.verifier.detect_failure = MagicMock(return_value=None)

        # Run task with max_steps=2 to trigger the second loop iteration where reason is called with updated messages
        with patch('time.sleep', return_value=None):
            result = agent.run_task("test task", max_steps=2)

        # Let's inspect the call history of reason.
        # Call 1: reason("test task", [])
        # Call 2: reason("test task", messages) where messages contains the tool output
        self.assertEqual(agent.vlm.reason.call_count, 2)
        
        # Get the second call arguments
        second_call_args = agent.vlm.reason.call_args_list[1]
        called_messages = second_call_args[0][1] # messages list is the second positional argument
        
        self.assertEqual(len(called_messages), 1)
        self.assertEqual(called_messages[0]["role"], "user")
        
        expected_content = '<observation>\n<tool_output tool="click">\nClicked start button\n</tool_output>\n</observation>'
        self.assertEqual(called_messages[0]["content"], expected_content)

if __name__ == '__main__':
    unittest.main()
