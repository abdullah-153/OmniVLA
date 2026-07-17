import unittest
import sys
import time
from PIL import Image

import tests.conftest
tests.conftest.init_mocks()

from cogniagent.agent import CogniAgent
from cogniagent.perception.state import SemanticState, UIElement
from tests.mocks.mock_llama_server import MockLlamaServerController
from tests.mocks.mock_screen import mock_mss_instance
from tests.mocks.mock_ctypes import registry

class TestScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.mocks.mock_llama_server import get_shared_server
        cls.server = get_shared_server()

    @classmethod
    def tearDownClass(cls):
        pass

    def setUp(self):
        from cogniagent.config import config
        config.llm.base_url = "http://127.0.0.1:58089/v1"
        self.server.clear()
        tests.conftest.init_mocks()
        # Mock default screens to support transitions
        self.img1 = Image.new("RGB", (100, 100), color=(10, 20, 30))
        self.img2 = Image.new("RGB", (100, 100), color=(40, 50, 60))
        self.img3 = Image.new("RGB", (100, 100), color=(70, 80, 90))

    def tearDown(self):
        from cogniagent.config import config
        config.llm.base_url = "http://127.0.0.1:8089/v1"

    def test_t4_01_agent_ui_login_flow(self):
        """TC-T4-01: Agent UI Login Flow"""
        # Step 1: Click Username
        self.server.queue_response({
            "note": "Login screen seen",
            "thought": "Click username text box",
            "tool_call": {
                "tool_name": "click",
                "element": "UsernameInput",
                "x": 200,
                "y": 300
            }
        })
        mock_mss_instance.queue_image(self.img1)
        
        # Step 2: Type Username
        self.server.queue_response({
            "note": "Username focused",
            "thought": "Type user name",
            "tool_call": {
                "tool_name": "type",
                "text": "admin",
                "submit": False
            }
        })
        mock_mss_instance.queue_image(self.img2)
        
        # Step 3: Click Password
        self.server.queue_response({
            "note": "Typed username",
            "thought": "Click password input box",
            "tool_call": {
                "tool_name": "click",
                "element": "PasswordInput",
                "x": 200,
                "y": 400
            }
        })
        mock_mss_instance.queue_image(self.img1)
        
        # Step 4: Type Password
        self.server.queue_response({
            "note": "Password focused",
            "thought": "Type secret password",
            "tool_call": {
                "tool_name": "type",
                "text": "secret123",
                "submit": False
            }
        })
        mock_mss_instance.queue_image(self.img2)
        
        # Step 5: Click Login
        self.server.queue_response({
            "note": "Typed password",
            "thought": "Click the login button",
            "tool_call": {
                "tool_name": "click",
                "element": "LoginButton",
                "x": 200,
                "y": 500
            }
        })
        mock_mss_instance.queue_image(self.img1)
        
        # Step 6: Conclude / Terminate
        self.server.queue_response({
            "note": "Dashboard screen loaded",
            "thought": "Login success! Terminating",
            "tool_call": {
                "tool_name": "terminate",
                "status": "success",
                "reason": "Successfully logged in and reached dashboard"
            }
        })
        mock_mss_instance.queue_image(self.img3)

        # Each active step captures a before and after frame.  Supply a full
        # sequence so the test verifies real state transitions instead of
        # relying on the mock's static fallback image.
        mock_mss_instance.queue.clear()
        for frame in (
            self.img1, self.img2,
            self.img2, self.img3,
            self.img3, self.img1,
            self.img1, self.img2,
            self.img2, self.img3,
            self.img3, self.img1,
        ):
            mock_mss_instance.queue_image(frame)
        
        agent = CogniAgent()
        res = agent.run_task("Login as admin", max_steps=6)
        
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["episodes"], 6)

    def test_t4_02_settings_page_navigation_and_toggle_switch(self):
        """TC-T4-02: Settings Page Navigation and Toggle Switch"""
        # Step 1: Open settings menu
        self.server.queue_response({
            "note": "Main page seen",
            "thought": "Click settings icon",
            "tool_call": {
                "tool_name": "click",
                "element": "SettingsIcon",
                "x": 900,
                "y": 100
            }
        })
        mock_mss_instance.queue_image(self.img1)
        
        # Step 2: Toggle switch
        self.server.queue_response({
            "note": "Settings page opened",
            "thought": "Click the dark mode toggle switch",
            "tool_call": {
                "tool_name": "click",
                "element": "DarkModeToggle",
                "x": 500,
                "y": 400
            }
        })
        mock_mss_instance.queue_image(self.img2)
        
        # Step 3: Done
        self.server.queue_response({
            "note": "Dark mode is toggled active",
            "thought": "Settings configured. Terminating",
            "tool_call": {
                "tool_name": "terminate",
                "status": "success",
                "reason": "Settings modified successfully"
            }
        })
        mock_mss_instance.queue_image(self.img3)
        
        agent = CogniAgent()
        res = agent.run_task("Toggle dark mode", max_steps=3)
        
        self.assertEqual(res["status"], "success")

    def test_t4_03_offline_database_sync_trigger_and_success_verification(self):
        """TC-T4-03: Offline Database Sync Trigger and Success verification"""
        # Step 1: Click sync button
        self.server.queue_response({
            "note": "Sync page seen",
            "thought": "Click synchronise database button",
            "tool_call": {
                "tool_name": "click",
                "element": "SyncButton",
                "x": 400,
                "y": 400
            }
        })
        mock_mss_instance.queue_image(self.img1)
        
        # Step 2: Terminate when synchronized label appears
        self.server.queue_response({
            "note": "Synchronized label visible",
            "thought": "Database synced successfully. Terminating",
            "tool_call": {
                "tool_name": "terminate",
                "status": "success",
                "reason": "Sync done"
            }
        })
        mock_mss_instance.queue_image(self.img2)
        
        agent = CogniAgent()
        
        # Inject mock states to verify synchronized state label
        agent._last_semantic_state = SemanticState(elements=[UIElement("Synchronising...")])
        agent.next_mock_state = SemanticState(elements=[UIElement("Synchronised successfully")])
        
        res = agent.run_task("Sync database", max_steps=2)
        
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["episodes"], 2)

    def test_t4_04_agent_recovery_from_unexpected_error_dialog(self):
        """TC-T4-04: Agent Recovery from Unexpected Error Dialog"""
        # Step 1: Click action button
        self.server.queue_response({
            "note": "Dashboard open",
            "thought": "Click action button",
            "tool_call": {
                "tool_name": "click",
                "element": "ActionButton",
                "x": 300,
                "y": 300
            }
        })
        mock_mss_instance.queue_image(self.img1)
        
        # Step 2: Dismiss error dialog (after detecting error semantic state)
        self.server.queue_response({
            "note": "Error popup detected",
            "thought": "Dismiss error popup by clicking Cancel",
            "tool_call": {
                "tool_name": "click",
                "element": "CancelButton",
                "x": 500,
                "y": 600
            }
        })
        mock_mss_instance.queue_image(self.img2)
        
        # Step 3: Recover and finish
        self.server.queue_response({
            "note": "Error popup dismissed, back to normal dashboard",
            "thought": "Completed recovery",
            "tool_call": {
                "tool_name": "terminate",
                "status": "success",
                "reason": "Dismissed popup error successfully"
            }
        })
        mock_mss_instance.queue_image(self.img3)
        
        agent = CogniAgent()
        
        # Inject states: step 1 results in an error dialog appearing
        agent._last_semantic_state = SemanticState(is_dialog=False)
        agent.next_mock_state = SemanticState(is_dialog=True, visible_text_summary="Error: Action failed")
        
        res = agent.run_task("Run action with fallback safety", max_steps=3)
        
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["episodes"], 3)

    def test_t4_05_repeated_invalid_form_submission_is_not_marked_successful(self):
        """TC-T4-05: A repeated failed submission must not become a false success."""
        # Step 1: Click next on page 1
        self.server.queue_response({
            "note": "Form page 1 open",
            "thought": "Click next page button",
            "tool_call": {
                "tool_name": "click",
                "element": "NextButton",
                "x": 800,
                "y": 800
            }
        })
        mock_mss_instance.queue_image(self.img1)
        
        # Step 2: Form error on page 2 (we typed bad input, got warning)
        self.server.queue_response({
            "note": "Form page 2 open",
            "thought": "Click next page button again",
            "tool_call": {
                "tool_name": "click",
                "element": "NextButton",
                "x": 800,
                "y": 800
            }
        })
        mock_mss_instance.queue_image(self.img2)
        
        # Step 3: Finish
        self.server.queue_response({
            "note": "Final page loaded",
            "thought": "Submit form, terminating",
            "tool_call": {
                "tool_name": "terminate",
                "status": "success",
                "reason": "Form fully completed"
            }
        })
        mock_mss_instance.queue_image(self.img3)
        
        agent = CogniAgent()
        
        # Inject states: step 2 returns form invalid warning dialog
        agent._last_semantic_state = SemanticState(is_dialog=False)
        agent.next_mock_state = SemanticState(is_dialog=True, visible_text_summary="Warning: invalid input")
        
        res = agent.run_task("Submit multi-page form", max_steps=3)
        
        self.assertEqual(res["status"], "failed")
        self.assertEqual(res["episodes"], 3)
