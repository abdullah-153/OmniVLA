import unittest
import numpy as np
import threading
import time

import tests.conftest
tests.conftest.init_mocks()

from cogniagent.perception.verification import ScreenVerifier
from cogniagent.perception.state import SemanticState, UIElement
from cogniagent.reasoning.action_reasoner import AgentAction
from cogniagent.memory.episodic_memory import EpisodicMemory, Episode

class TestF4Verify(unittest.TestCase):
    def setUp(self):
        tests.conftest.init_mocks()
        self.verifier = ScreenVerifier()

    def test_t1_f4_01_ssim_visual_stagnation_verification(self):
        """TC-T1-F4-01: SSIM Visual Stagnation Verification"""
        frame1 = np.zeros((100, 100, 3), dtype=np.uint8)
        frame2 = np.zeros((100, 100, 3), dtype=np.uint8)
        
        res = self.verifier.compute_screen_diff(frame1, frame2)
        self.assertFalse(res["changed"])
        self.assertEqual(res["diff_ratio"], 0.0)

    def test_t1_f4_02_ssim_stagnation_tolerance_bound(self):
        """TC-T1-F4-02: SSIM Stagnation Tolerance Bound"""
        frame1 = np.zeros((100, 100, 3), dtype=np.uint8)
        frame2 = np.zeros((100, 100, 3), dtype=np.uint8)
        # Change only 5 pixels (5 / 10000 = 0.0005, which is < 1% of pixels)
        frame2[0, :5, 0] = 255
        
        res = self.verifier.compute_screen_diff(frame1, frame2)
        self.assertFalse(res["changed"]) # diff_ratio is below 0.01 threshold

    def test_t1_f4_03_visual_scene_transition_detection(self):
        """TC-T1-F4-03: Visual Scene Transition Detection"""
        frame1 = np.zeros((100, 100, 3), dtype=np.uint8)
        frame2 = np.zeros((100, 100, 3), dtype=np.uint8)
        # Change 600 pixels (6% of pixels, which is > 5%)
        frame2[:6, :100, 0] = 255
        
        res = self.verifier.compute_screen_diff(frame1, frame2)
        self.assertTrue(res["changed"])
        self.assertEqual(res["description"], "Minor change (tooltip, cursor, highlight)")

    def test_t1_f4_04_visual_stagnation_failure_detection(self):
        """TC-T1-F4-04: Visual Stagnation Failure Detection"""
        diff_res = {"changed": False, "diff_ratio": 0.0}
        action = AgentAction(action_type="click", thought="Click the submit button")
        
        fail_reason = self.verifier.detect_failure(diff_res, action=action)
        self.assertEqual(fail_reason, "No visible screen change after action")

    def test_t1_f4_05_visual_success_no_failure(self):
        """TC-T1-F4-05: Visual Change Verified Success"""
        diff_res = {"changed": True, "diff_ratio": 0.25}
        action = AgentAction(action_type="click", thought="Click the menu")
        
        fail_reason = self.verifier.detect_failure(diff_res, action=action)
        self.assertIsNone(fail_reason)

    def test_focus_change_verifies_a_visually_static_click(self):
        diff_res = {"changed": False, "diff_ratio": 0.0}
        action = AgentAction(action_type="click", thought="Focus the editor")

        fail_reason = self.verifier.detect_failure(
            diff_res,
            action=action,
            execution_result={"focus_changed": True},
        )

        self.assertIsNone(fail_reason)

    def test_small_text_delta_is_verified_below_navigation_threshold(self):
        diff_res = {"changed": False, "diff_ratio": 0.0002}
        action = AgentAction(action_type="type", thought="Enter text")

        self.assertIsNone(self.verifier.detect_failure(diff_res, action=action))

    def test_t2_f4_01_invalid_image_dimensions_to_verifier(self):
        """TC-T2-F4-01: Invalid Image Dimensions to Verifier"""
        frame1 = np.zeros((100, 100, 3), dtype=np.uint8)
        frame2 = np.zeros((100, 200, 3), dtype=np.uint8)
        
        res = self.verifier.compute_screen_diff(frame1, frame2)
        self.assertTrue(res["changed"])
        self.assertEqual(res["description"], "Resolution changed")

    def test_t2_f4_02_extreme_noise_filtering(self):
        """TC-T2-F4-02: Extreme Noise Filtering (SSIM vs Pixel-Diff)"""
        frame1 = np.zeros((100, 100, 3), dtype=np.uint8)
        frame2 = np.zeros((100, 100, 3), dtype=np.uint8)
        # Add random noise below threshold (e.g. value of 10)
        # Verifier ignores changes below threshold (default 30)
        frame2.fill(10)
        
        res = self.verifier.compute_screen_diff(frame1, frame2)
        self.assertFalse(res["changed"])

    def test_t2_f4_02b_visual_diff_uses_a_bounded_sample(self):
        """Large frames are sampled instead of allocating full int64 buffers."""
        verifier = ScreenVerifier(max_sample_pixels=100)
        frame1 = np.zeros((100, 100, 3), dtype=np.uint8)
        frame2 = np.full((100, 100, 3), 255, dtype=np.uint8)

        res = verifier.compute_screen_diff(frame1, frame2)

        self.assertTrue(res["changed"])
        self.assertGreater(res["sample_stride"], 1)
        self.assertLessEqual(res["sampled_pixels"], 100)

    def test_t2_f4_03_verification_skip_on_special_tool_actions(self):
        """TC-T2-F4-03: Verification Skip on Special Tool Actions"""
        diff_res = {"changed": False}
        action_wait = AgentAction(action_type="wait")
        fail_reason = self.verifier.detect_failure(diff_res, action=action_wait)
        # For "wait" action type, no visible screen change should NOT flag failure
        self.assertIsNone(fail_reason)


    def test_t2_f4_05_backtracking_trajectory_persistence(self):
        """TC-T2-F4-05: Backtracking Trajectory Persistence"""
        from cogniagent.config import config
        memory = EpisodicMemory(config)
        
        ep1 = Episode(
            task="Register form",
            app_context="FormApp",
            goal="Click Input",
            action_type="click",
            action_args=["input"],
            action_method="vlm_router",
            success=True,
            state_summary="Entered name",
            outcome="Focused",
            timestamp=time.time(),
            execution_time_ms=50,
            retry_count=0
        )
        
        ep2 = Episode(
            task="Register form",
            app_context="FormApp",
            goal="Submit form",
            action_type="click",
            action_args=["submit"],
            action_method="vlm_router",
            success=False, # Failure!
            state_summary="Error dialog",
            outcome="Failed submit",
            timestamp=time.time(),
            execution_time_ms=50,
            retry_count=0
        )
        
        memory.store(ep1)
        memory.store(ep2)
        
        # Verify both episodes are stored in ChromaDB mock collections
        count = memory.client.get_or_create_collection("episodes").count()
        self.assertEqual(count, 2)
