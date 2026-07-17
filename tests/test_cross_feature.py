import unittest
import sys
import numpy as np
from PIL import Image

import tests.conftest
tests.conftest.init_mocks()

from cogniagent.config import config
from cogniagent.agent import CogniAgent
from cogniagent.perception.vlm_engine import VLMEngine
from tests.mocks.mock_screen import mock_mss_instance
from tests.mocks.mock_llama_server import MockLlamaServerController
from tests.mocks.mock_ctypes import registry
from cogniagent.perception.state import SemanticState, UIElement
from cogniagent.reasoning.action_reasoner import AgentAction

class TestCrossFeature(unittest.TestCase):
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

    def test_t3_01_server_startup_port_lock_prevents_agent_interaction(self):
        """TC-T3-01: Server Startup Port Lock prevents Agent Interaction"""
        # Set server offline to simulate port connection/handshake failure (OpenAI client throws connection error)
        self.server.stop()
        
        agent = CogniAgent()
        # Since server is stopped, run_task should exit/return failed status
        res = agent.run_task("Task when server is locked/dead", max_steps=1)
        self.assertEqual(res["status"], "failed")
        
        # Restart mock server for subsequent tests
        self.server.start()

    def test_t3_02_mouse_action_stagnation_triggers_vlm_replanning(self):
        """TC-T3-02: Mouse Action Stagnation triggers VLM Re-planning"""
        # Queue identical screenshots to mock stagnation
        img = Image.new("RGB", (100, 100), color=(12, 34, 56))
        mock_mss_instance.queue_image(img)
        mock_mss_instance.queue_image(img)
        
        # Step 1 response: click button
        self.server.queue_response({
            "note": "Let's click button",
            "thought": "Clicking button",
            "tool_call": {
                "tool_name": "click",
                "element": "Button",
                "x": 100,
                "y": 100
            }
        })
        # Step 2 response: since stagnation is detected, next prompt contains warning,
        # and server returns terminate action
        self.server.queue_response({
            "note": "Saw warning, terminating task",
            "thought": "Stopping since button click had no effect",
            "tool_call": {
                "tool_name": "terminate",
                "status": "success",
                "reason": "Replanned and stopped"
            }
        })
        
        agent = CogniAgent()
        res = agent.run_task("Click button task", max_steps=2)
        
        # A model cannot turn an unverified, stagnant click into a success
        # merely by issuing terminate on the following step.
        self.assertEqual(res["status"], "failed")
        
        # Verify warnings were injected in messages sent to the VLM server on step 2
        reqs = self.server.get_requests()
        self.assertEqual(len(reqs), 2)
        step2_payload = reqs[1]["messages"]
        
        # The warning should be in the user prompt before the second inference step
        warning_found = False
        for msg in step2_payload:
            if msg["role"] == "user":
                content = msg.get("content")
                if isinstance(content, str):
                    if "Warning: The previous action had no effect" in content:
                        warning_found = True
                elif isinstance(content, list):
                    for chunk in content:
                        if isinstance(chunk, dict) and chunk.get("type") == "text" and "Warning: The previous action had no effect" in chunk.get("text", ""):
                            warning_found = True
                
        self.assertTrue(warning_found)

    def test_t3_03_keyboard_action_with_layout_delay_triggers_verification_failure(self):
        """TC-T3-03: Keyboard Action with Layout Delay triggers Verification Failure"""
        # Setup: VLM types some text but semantic verifier expects "Hello" in the UI.
        # But we do not provide "Hello" in the next mock semantic state -> triggers failure warning.
        self.server.queue_response({
            "note": "Typing text",
            "thought": "Typing Hello",
            "tool_call": {
                "tool_name": "type",
                "text": "Hello",
                "submit": False
            }
        })
        self.server.queue_response({
            "note": "Failure seen, terminating",
            "thought": "Stopping",
            "tool_call": {
                "tool_name": "terminate",
                "status": "success",
                "reason": "Stopped"
            }
        })
        
        agent = CogniAgent()
        # Inject mock states:
        # First state before action
        agent._last_semantic_state = SemanticState(elements=[UIElement("Empty")])
        # Next state after typing, but does NOT contain typed text "Hello"
        agent.next_mock_state = SemanticState(elements=[UIElement("Empty")])
        
        agent.run_task("Type hello task", max_steps=2)
        
        reqs = self.server.get_requests()
        step2_payload = reqs[1]["messages"]
        
        warning_found = False
        for msg in step2_payload:
            if msg["role"] == "user":
                content = msg.get("content")
                if isinstance(content, str):
                    if "Warning: Action failed" in content:
                        warning_found = True
                elif isinstance(content, list):
                    for chunk in content:
                        if isinstance(chunk, dict) and chunk.get("type") == "text" and "Warning: Action failed" in chunk.get("text", ""):
                            warning_found = True
        self.assertTrue(warning_found)

    def test_t3_04_eviction_logic_triggers_during_multi_page_verification_backtracking(self):
        """TC-T3-04: Eviction Logic triggers during Multi-page Verification Backtracking"""
        # Send 5 steps of messages to see if history images are evicted to max 3
        # during backtracking self-correction loop
        for i in range(4):
            self.server.queue_response({
                "note": f"Step {i}",
                "thought": "Going next",
                "tool_call": {
                    "tool_name": "click",
                    "element": "Next",
                    "x": 200,
                    "y": 200
                }
            })
        self.server.queue_response({
            "note": "Final step",
            "thought": "Done",
            "tool_call": {
                "tool_name": "terminate",
                "status": "success",
                "reason": "Completed"
            }
        })
        
        agent = CogniAgent()
        agent.run_task("Multi-step task", max_steps=5)
        
        # Check last request payload
        reqs = self.server.get_requests()
        last_payload = reqs[-1]["messages"]
        
        image_count = 0
        eviction_count = 0
        
        for msg in last_payload:
            if msg["role"] == "user" and isinstance(msg["content"], list):
                for chunk in msg["content"]:
                    if chunk.get("type") == "image_url":
                        image_count += 1
                    elif chunk.get("type") == "text" and "[screenshot evicted]" in chunk.get("text", ""):
                        eviction_count += 1
                        
        self.assertEqual(image_count, 1)
        self.assertTrue(eviction_count >= 1)
