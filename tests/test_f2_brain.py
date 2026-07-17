import unittest
import sys
import json
from PIL import Image

import tests.conftest
tests.conftest.init_mocks()

from cogniagent.config import config
from cogniagent.perception.vlm_engine import VLMEngine, trim_to_last_n_images
from tests.mocks.mock_llama_server import MockLlamaServerController

class TestF2Brain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.mocks.mock_llama_server import get_shared_server
        cls.server = get_shared_server()

    @classmethod
    def tearDownClass(cls):
        pass

    def setUp(self):
        config.llm.base_url = "http://127.0.0.1:58089/v1"
        self.server.clear()
        tests.conftest.init_mocks()

    def tearDown(self):
        config.llm.base_url = "http://127.0.0.1:8089/v1"

    def test_t1_f2_01_config_target_configuration(self):
        """TC-T1-F2-01: Config Target Configuration"""
        from cogniagent.config import OmniVLAConfig
        fresh_config = OmniVLAConfig()
        self.assertEqual(fresh_config.llm.base_url, "http://127.0.0.1:8089/v1")
        self.assertEqual(fresh_config.llm.model, "models/Holo-3.1-4B-abliterated-rdo.Q4_K_M.gguf")

    def test_t1_f2_02_observation_wrapper_insertion(self):
        """TC-T1-F2-02: Observation Wrapper Insertion"""
        # Queue standard response to avoid failures
        self.server.queue_response({
            "note": "Checked page",
            "thought": "Click button",
            "tool_call": {
                "tool_name": "click",
                "element": "Button",
                "x": 500,
                "y": 500
            }
        })
        
        vlm = VLMEngine()
        vlm.reason("Test task", [])
        
        requests = self.server.get_requests()
        self.assertEqual(len(requests), 1)
        last_msg = requests[0]["messages"][-1]
        
        # Verify observation tags wrapped around contents
        self.assertEqual(last_msg["content"][0]["text"], "<observation>\n")
        self.assertEqual(last_msg["content"][2]["text"], "\n</observation>")

    def test_t1_f2_03_structured_schema_prompt_request(self):
        """TC-T1-F2-03: Structured Schema Prompt Request"""
        self.server.queue_response({
            "note": "Checked page",
            "thought": "Click button",
            "tool_call": {
                "tool_name": "click",
                "element": "Button",
                "x": 500,
                "y": 500
            }
        })
        
        vlm = VLMEngine()
        vlm.reason("Test task", [])
        
        requests = self.server.get_requests()
        system_msg = requests[0]["messages"][0]["content"]
        
        # Check system message has schema rules
        self.assertIn("note", system_msg)
        self.assertIn("thought", system_msg)
        self.assertIn("tool_call", system_msg)

    def test_t1_f2_04_successful_structured_output_parse(self):
        """TC-T1-F2-04: Successful Structured Output Parse"""
        mock_response = {
            "note": "Success note",
            "thought": "Let us click the icon",
            "tool_call": {
                "tool_name": "click",
                "element": "Icon",
                "x": 200,
                "y": 300
            }
        }
        self.server.queue_response(mock_response)
        
        vlm = VLMEngine()
        res = vlm.reason("Click icon", [])
        
        self.assertIsNotNone(res)
        self.assertEqual(res["think"], "Let us click the icon")
        self.assertEqual(res["action_desp"], "click")
        self.assertEqual(res["parsed_action"]["x"], 200)

    def test_t1_f2_05_screenshot_eviction_history_trimming(self):
        """TC-T1-F2-05: Screenshot Eviction History Trimming"""
        # Create message history with 5 image components
        messages = []
        for i in range(5):
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": "Something"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,fake{i}"}}
                ]
            })
            
        trim_to_last_n_images(messages, n=3)
        
        # Verify first two are evicted
        self.assertEqual(messages[0]["content"][1]["type"], "text")
        self.assertEqual(messages[0]["content"][1]["text"], "[screenshot evicted]")
        self.assertNotIn("image_url", messages[0]["content"][1])
        
        self.assertEqual(messages[1]["content"][1]["type"], "text")
        self.assertEqual(messages[1]["content"][1]["text"], "[screenshot evicted]")
        
        # Verify remaining 3 are NOT evicted
        self.assertEqual(messages[2]["content"][1]["type"], "image_url")
        self.assertEqual(messages[3]["content"][1]["type"], "image_url")
        self.assertEqual(messages[4]["content"][1]["type"], "image_url")

    def test_t2_f2_01_malformed_json_vlm_response_parsing(self):
        """TC-T2-F2-01: Malformed JSON VLM Response Parsing"""
        # Return truncated/invalid JSON for all 3 attempts
        self.server.queue_response('{ "thought": "Clicking button", ')
        self.server.queue_response('{ "thought": "Clicking button", ')
        self.server.queue_response('{ "thought": "Clicking button", ')
        
        vlm = VLMEngine()
        # Should catch JSONDecodeError and return None without crash
        res = vlm.reason("Click button", [])
        self.assertIsNone(res)

    def test_t2_f2_02_missing_schema_fields_rejection(self):
        """TC-T2-F2-02: Missing Schema Fields Rejection"""
        # Missing thought and tool_call for all 3 attempts
        self.server.queue_response({"note": "Only note present"})
        self.server.queue_response({"note": "Only note present"})
        self.server.queue_response({"note": "Only note present"})
        
        vlm = VLMEngine()
        # Should fail validation on all attempts and return None
        res = vlm.reason("Click button", [])
        self.assertIsNone(res)

    def test_t2_f2_03_eviction_logic_on_non_image_payloads(self):
        """TC-T2-F2-03: Eviction Logic on Non-Image Payloads"""
        messages = [
            {"role": "user", "content": "Just text message 1"},
            {"role": "user", "content": "Just text message 2"}
        ]
        trim_to_last_n_images(messages, n=3)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["content"], "Just text message 1")

    def test_t2_f2_04_eviction_logic_with_exactly_n_screenshots(self):
        """TC-T2-F2-04: Eviction Logic with Exactly N Screenshots"""
        messages = []
        for i in range(3):
            messages.append({
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,fake{i}"}}
                ]
            })
            
        trim_to_last_n_images(messages, n=3)
        for i in range(3):
            self.assertEqual(messages[i]["content"][0]["type"], "image_url")

    def test_t2_f2_05_api_endpoint_500_server_error_response(self):
        """TC-T2-F2-05: API Endpoint 500 Server Error Response"""
        # Inject standard 500 server error response by returning malformed/broken response 
        # or we can mock request directly
        # Let's mock client.chat.completions.create to raise exception
        vlm = VLMEngine()
        from unittest.mock import patch
        with patch.object(vlm.client.chat.completions, "create", side_effect=Exception("HTTP 500 Server Error")):
            res = vlm.reason("Click button", [])
            self.assertIsNone(res)
