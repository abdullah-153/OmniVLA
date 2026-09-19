"""Unit and regression tests for Human-In-The-Loop (HITL), OTP/2FA guardrails, and step limit continuation."""

import unittest
from unittest.mock import patch, MagicMock
from PIL import Image

import tests.conftest
tests.conftest.init_mocks()

from cogniagent.config import config
from cogniagent.agent import CogniAgent
from cogniagent.execution.router import ActionRouter
from cogniagent.perception.vlm_engine import SYSTEM_PROMPT as VLM_SYSTEM_PROMPT
from cogniagent.memory.user_profile import UserProfileMemory


class TestOTPAndRiskAssessment(unittest.TestCase):
    def setUp(self):
        tests.conftest.init_mocks()
        self.router = ActionRouter(config)

    def test_assess_action_risk_detects_otp_and_2fa(self):
        # Click on 2FA button
        risk_click = self.router.assess_action_risk({
            "tool_name": "click",
            "element": "Submit OTP code button",
        })
        self.assertIsNotNone(risk_click)
        self.assertIn("authentication or verification code", risk_click["reasons"])

        # Type into verification code box
        risk_type = self.router.assess_action_risk({
            "tool_name": "type",
            "element": "Enter 6-digit verification code",
            "text": "123456",
        })
        self.assertIsNotNone(risk_type)
        self.assertIn("authentication or verification code", risk_type["reasons"])

        # click_and_type targeting authenticator passcode
        risk_cat = self.router.assess_action_risk({
            "tool_name": "click_and_type",
            "element": "Two-factor passcode input",
            "text": "000000",
        })
        self.assertIsNotNone(risk_cat)
        self.assertIn("authentication or verification code", risk_cat["reasons"])

        # compound action with an OTP step
        risk_compound = self.router.assess_action_risk({
            "tool_name": "compound_action",
            "actions": [
                {"tool_name": "click", "element": "Focus input"},
                {"tool_name": "type", "element": "Security code", "text": "1234"},
            ],
        })
        self.assertIsNotNone(risk_compound)
        self.assertIn("authentication or verification code", risk_compound["reasons"])

    def test_dummy_verification_code_detection(self):
        # Known dummy codes in OTP contexts
        self.assertTrue(self.router.is_dummy_verification_code("123456", "Enter OTP"))
        self.assertTrue(self.router.is_dummy_verification_code("000000", "2FA verification code"))
        self.assertTrue(self.router.is_dummy_verification_code("111111", "One-time passcode"))
        self.assertTrue(self.router.is_dummy_verification_code("1234", "Security PIN"))
        self.assertTrue(self.router.is_dummy_verification_code("test", "auth code"))
        self.assertTrue(self.router.is_dummy_verification_code("888888", "Verification code"))

        # Real/genuine user OTP codes should NOT be flagged as dummy
        self.assertFalse(self.router.is_dummy_verification_code("849201", "Enter OTP"))
        self.assertFalse(self.router.is_dummy_verification_code("392019", "2FA code"))

        # Normal text outside auth context should NOT be flagged
        self.assertFalse(self.router.is_dummy_verification_code("123456", "Search box"))

    def test_execute_vlm_action_blocks_dummy_otp_in_type(self):
        action_data = {
            "tool_name": "type",
            "element": "Email OTP verification field",
            "text": "123456",
            "submit": True,
        }
        res = self.router.execute_vlm_action({"parsed_action": action_data}, (1920, 1080))
        self.assertFalse(res["success"])
        self.assertIn("Dummy verification code blocked", res["detail"])
        self.assertIn("hitl_intervention", res["detail"])

    def test_execute_vlm_action_blocks_dummy_otp_in_click_and_type(self):
        action_data = {
            "tool_name": "click_and_type",
            "element": "One-time password input box",
            "x": 500,
            "y": 500,
            "text": "000000",
            "submit": True,
        }
        res = self.router.execute_vlm_action({"parsed_action": action_data}, (1920, 1080))
        self.assertFalse(res["success"])
        self.assertIn("Dummy verification code blocked", res["detail"])


class TestStepLimitContinuationAndHITL(unittest.TestCase):
    def setUp(self):
        tests.conftest.init_mocks()
        self.agent = CogniAgent()
        self.agent.config.perception.visual_verification_enabled = False
        self.agent.verify_action_with_critic = MagicMock(return_value={"status": "CORRECT", "reason": "OK"})
        self.agent.verifier.detect_failure = MagicMock(return_value=None)
        self.agent.verifier.compute_screen_diff = MagicMock(return_value={"has_change": True, "diff_score": 10.0, "is_stagnant": False})

    @patch("cogniagent.agent.time.sleep")
    def test_step_limit_continuation_with_instruction(self, mock_sleep):
        """Verify that when step limit is reached, user's instruction is appended and execution continues."""
        mock_vlm = MagicMock()
        mock_vlm.capture_screen.return_value = (Image.new("RGB", (100, 100)), (100, 100))
        
        # Step 1: Click search
        step1_res = {
            "action_desp": "click",
            "tool_name": "click",
            "parsed_action": {"tool_name": "click", "element": "Search", "x": 100, "y": 100},
            "think": "Clicking search",
            "tool_call_id": "call-1",
            "screenshot": Image.new("RGB", (100, 100)),
        }
        # Step 2: Terminate success
        step2_res = {
            "action_desp": "terminate",
            "tool_name": "terminate",
            "parsed_action": {"tool_name": "terminate", "status": "success", "reason": "Task completed."},
            "think": "Done",
            "tool_call_id": "call-2",
            "screenshot": Image.new("RGB", (100, 100)),
        }
        mock_vlm.reason.side_effect = [step1_res, step2_res]
        self.agent.vlm = mock_vlm

        # Mock executor to succeed
        def mock_exec(vlm_res, dims):
            is_term = vlm_res.get("action_desp") == "terminate" or vlm_res.get("parsed_action", {}).get("tool_name") == "terminate"
            return {"success": True, "detail": "Executed", "is_done": is_term}

        self.agent.executor.execute_vlm_action = mock_exec

        # Set max_steps=1 so it hits the limit immediately at step 1
        user_responses = ["Check my email inbox for the verification code"]
        self.agent.wait_for_hitl_response = lambda: user_responses.pop(0)

        notified_phases = []
        self.agent.on_status_change = lambda phase, detail: notified_phases.append(phase)

        result = self.agent.run_task("Sign in and check order", max_steps=1)

        self.assertIn("hitl", notified_phases)
        self.assertEqual(result["status"], "success")

    @patch("cogniagent.agent.time.sleep")
    def test_step_limit_continuation_with_continue_keyword(self, mock_sleep):
        """Verify that typing 'continue' extends the budget and proceeds."""
        mock_vlm = MagicMock()
        mock_vlm.capture_screen.return_value = (Image.new("RGB", (100, 100)), (100, 100))
        
        step1_res = {
            "action_desp": "click",
            "tool_name": "click",
            "parsed_action": {"tool_name": "click", "element": "Next", "x": 200, "y": 200},
            "think": "Clicking next",
            "tool_call_id": "call-1",
            "screenshot": Image.new("RGB", (100, 100)),
        }
        step2_res = {
            "action_desp": "terminate",
            "tool_name": "terminate",
            "parsed_action": {"tool_name": "terminate", "status": "success", "reason": "Done."},
            "think": "Done",
            "tool_call_id": "call-2",
            "screenshot": Image.new("RGB", (100, 100)),
        }
        mock_vlm.reason.side_effect = [step1_res, step2_res]
        self.agent.vlm = mock_vlm

        def mock_exec(vlm_res, dims):
            is_term = vlm_res.get("action_desp") == "terminate" or vlm_res.get("parsed_action", {}).get("tool_name") == "terminate"
            return {"success": True, "detail": "Clicked", "is_done": is_term}

        self.agent.executor.execute_vlm_action = mock_exec

        self.agent.wait_for_hitl_response = lambda: "continue"

        result = self.agent.run_task("Navigate through pages", max_steps=1)
        self.assertEqual(result["status"], "success")

    @patch("cogniagent.agent.time.sleep")
    def test_step_limit_abort_on_stop(self, mock_sleep):
        """Verify that typing 'stop' at step limit aborts the task."""
        mock_vlm = MagicMock()
        mock_vlm.capture_screen.return_value = (Image.new("RGB", (100, 100)), (100, 100))
        
        step1_res = {
            "action_desp": "click",
            "tool_name": "click",
            "parsed_action": {"tool_name": "click", "element": "Button", "x": 100, "y": 100},
            "think": "Clicking",
            "tool_call_id": "call-1",
            "screenshot": Image.new("RGB", (100, 100)),
        }
        mock_vlm.reason.return_value = step1_res
        self.agent.vlm = mock_vlm
        self.agent.executor.execute_vlm_action = MagicMock(return_value={"success": True, "detail": "Clicked", "is_done": False})

        self.agent.wait_for_hitl_response = lambda: "stop"

        result = self.agent.run_task("Do something", max_steps=1)
        self.assertEqual(result["status"], "failed")

    @patch("cogniagent.agent.time.sleep")
    def test_otp_hitl_replaces_dummy_code_with_user_code(self, mock_sleep):
        """Verify that when an OTP action triggers risk assessment, the operator's real code replaces the text."""
        mock_vlm = MagicMock()
        mock_vlm.capture_screen.return_value = (Image.new("RGB", (100, 100)), (100, 100))

        otp_step = {
            "action_desp": "type",
            "tool_name": "type",
            "parsed_action": {
                "tool_name": "type",
                "element": "Email OTP verification box",
                "text": "123456",
                "submit": True,
            },
            "think": "Entering OTP",
            "tool_call_id": "call-otp",
            "screenshot": Image.new("RGB", (100, 100)),
        }
        done_step = {
            "action_desp": "terminate",
            "tool_name": "terminate",
            "parsed_action": {"tool_name": "terminate", "status": "success", "reason": "Logged in."},
            "think": "Success",
            "tool_call_id": "call-done",
            "screenshot": Image.new("RGB", (100, 100)),
        }
        mock_vlm.reason.side_effect = [otp_step, done_step]
        self.agent.vlm = mock_vlm

        executed_actions = []
        def capture_execution(vlm_res, dims):
            act = dict(vlm_res.get("parsed_action", {}))
            executed_actions.append(act)
            is_term = act.get("tool_name") == "terminate" or vlm_res.get("action_desp") == "terminate"
            return {"success": True, "detail": "Typed OTP", "is_done": is_term}

        self.agent.executor.execute_vlm_action = capture_execution

        # Operator provides real OTP: "749210"
        self.agent.wait_for_hitl_response = lambda: "749210"

        result = self.agent.run_task("Log in with OTP", max_steps=5)
        self.assertEqual(result["status"], "success")

        # Verify that the executed action had the user's real OTP, NOT the dummy 123456
        self.assertEqual(executed_actions[0]["text"], "749210")

    @patch("cogniagent.agent.time.sleep")
    def test_cycle_detection_triggers_for_repetitive_typing(self, mock_sleep):
        """Verify cycle detection catches repetitive typing loops."""
        mock_vlm = MagicMock()
        mock_vlm.capture_screen.return_value = (Image.new("RGB", (100, 100)), (100, 100))

        type_step = {
            "action_desp": "type",
            "tool_name": "type",
            "parsed_action": {"tool_name": "type", "text": "123456", "submit": True},
            "think": "Typing again",
            "tool_call_id": "call-t",
            "screenshot": Image.new("RGB", (100, 100)),
        }
        mock_vlm.reason.return_value = type_step
        self.agent.vlm = mock_vlm
        self.agent.executor.execute_vlm_action = MagicMock(return_value={"success": True, "detail": "Typed", "is_done": False})

        self.agent.wait_for_hitl_response = lambda: "stop"
        result = self.agent.run_task("Loop test", max_steps=4)

        self.assertTrue(len(result.get("steps", [])) >= 3)


class TestPromptEfficiencyAndProfileContext(unittest.TestCase):
    def test_holo_vlm_system_prompt_word_count(self):
        words = VLM_SYSTEM_PROMPT.split()
        self.assertLess(len(words), 180, f"Holo VLM prompt exceeds 180 words: {len(words)}")
        self.assertIn("Auth & Safety", VLM_SYSTEM_PROMPT)
        self.assertIn("hitl_intervention", VLM_SYSTEM_PROMPT)

    def test_user_profile_vla_context_has_auth_guidance(self):
        profile = UserProfileMemory()
        vla_ctx = profile.get_vla_context()
        self.assertIn("ak1399er@gmail.com", vla_ctx)
        self.assertIn("Gmail", vla_ctx)
        self.assertIn("hitl_intervention", vla_ctx)
        self.assertIn("saved passwords", vla_ctx)


if __name__ == "__main__":
    unittest.main()
