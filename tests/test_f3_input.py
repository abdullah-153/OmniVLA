import unittest
import os
import sys

import tests.conftest
tests.conftest.init_mocks()

from cogniagent.config import config
from cogniagent.execution.router import ActionRouter
from cogniagent.execution import win32_input
from tests.mocks.mock_ctypes import registry

class TestF3Input(unittest.TestCase):
    def setUp(self):
        tests.conftest.init_mocks()
        # Ensure failsafe doesn't trigger by default
        registry.cursor_x = 100
        registry.cursor_y = 100
        registry.screen_width = 1920
        registry.screen_height = 1080

    def test_t1_f3_01_click_coordinate_scaling(self):
        """TC-T1-F3-01: Click Coordinate Scaling"""
        router = ActionRouter(config)
        vlm_result = {
            "action_desp": "click",
            "parsed_action": {
                "tool_name": "click",
                "element": "Button",
                "x": 500,
                "y": 500
            }
        }
        
        router.execute_vlm_action(vlm_result, (1920, 1080))
        
        # Scaling of x: 500 -> 500/1000 * 1920 = 960
        # Scaling of y: 500 -> 500/1000 * 1080 = 540
        self.assertEqual(registry.cursor_x, 960)
        self.assertEqual(registry.cursor_y, 540)
        
        # Assert SetCursorPos was called
        calls = [c[0] for c in registry.calls]
        self.assertIn("SetCursorPos", calls)

    def test_t1_f3_02_native_mouse_click_event_generation(self):
        """TC-T1-F3-02: Native Mouse Click Event Generation"""
        router = ActionRouter(config)
        vlm_result = {
            "action_desp": "click",
            "parsed_action": {
                "tool_name": "click",
                "element": "Button",
                "x": 500,
                "y": 500
            }
        }
        
        router.execute_vlm_action(vlm_result, (1920, 1080))
        
        # Verify SendInput events for left click down/up
        mouse_events = [ev for ev in registry.send_input_events if ev["type"] == "mouse"]
        self.assertTrue(len(mouse_events) >= 2)
        
        # Verify MOUSEEVENTF_LEFTDOWN = 0x0002 and MOUSEEVENTF_LEFTUP = 0x0004
        flags = [ev["dwFlags"] for ev in mouse_events]
        self.assertIn(0x0002, flags)
        self.assertIn(0x0004, flags)

    def test_t1_f3_03_native_type_text_sequence(self):
        """TC-T1-F3-03: Native Type Text Sequence"""
        router = ActionRouter(config)
        vlm_result = {
            "action_desp": "type",
            "parsed_action": {
                "tool_name": "type",
                "text": "Test",
                "submit": False
            }
        }
        
        router.execute_vlm_action(vlm_result, (1920, 1080))
        
        # Verify keyboard unicode events were sent for T, e, s, t
        kb_events = [ev for ev in registry.send_input_events if ev["type"] == "keyboard"]
        self.assertTrue(len(kb_events) >= 8) # 4 chars * 2 (down and up) = 8 events
        
        # Char codes
        scan_codes = [ev["wScan"] for ev in kb_events]
        self.assertIn(ord('T'), scan_codes)
        self.assertIn(ord('e'), scan_codes)
        self.assertIn(ord('s'), scan_codes)
        self.assertIn(ord('t'), scan_codes)

    def test_t1_f3_04_native_key_press_event_generation(self):
        """TC-T1-F3-04: Native Key Press Event Generation"""
        router = ActionRouter(config)
        vlm_result = {
            "action_desp": "key_press",
            "parsed_action": {
                "tool_name": "key_press",
                "key": "enter"
            }
        }
        
        router.execute_vlm_action(vlm_result, (1920, 1080))
        
        # Verify SendInput keyboard events for VK_RETURN (0x0D)
        kb_events = [ev for ev in registry.send_input_events if ev["type"] == "keyboard"]
        self.assertTrue(len(kb_events) >= 2) # down + up
        
        vks = [ev["wVk"] for ev in kb_events]
        self.assertIn(0x0D, vks)

    def test_t1_f3_05_native_scroll_down_action(self):
        """TC-T1-F3-05: Native Scroll Down Action"""
        router = ActionRouter(config)
        vlm_result = {
            "action_desp": "scroll",
            "parsed_action": {
                "tool_name": "scroll",
                "direction": "down"
            }
        }
        
        router.execute_vlm_action(vlm_result, (1920, 1080))
        
        mouse_events = [ev for ev in registry.send_input_events if ev["type"] == "mouse"]
        self.assertTrue(len(mouse_events) >= 1)
        
        # MOUSEEVENTF_WHEEL = 0x0800
        self.assertEqual(mouse_events[0]["dwFlags"], 0x0800)
        # Scroll down is negative amount
        self.assertTrue(mouse_events[0]["mouseData"] > 0x7FFFFFFF) # unsigned representation of negative int

    def test_t2_f3_01_out_of_range_coordinates_are_rejected(self):
        """TC-T2-F3-01: Invalid coordinates must not turn into edge clicks."""
        router = ActionRouter(config)
        vlm_result = {
            "action_desp": "click",
            "parsed_action": {
                "tool_name": "click",
                "element": "Button",
                "x": -50,
                "y": 1111,
            }
        }

        result = router.execute_vlm_action(vlm_result, (1920, 1080))

        self.assertFalse(result["success"])
        self.assertIn("range [0, 1000]", result["detail"])
        self.assertEqual(registry.cursor_x, 100)
        self.assertEqual(registry.cursor_y, 100)
        self.assertNotIn("SetCursorPos", [call[0] for call in registry.calls])

    def test_t2_f3_01b_secondary_monitor_origin_is_preserved(self):
        """A screenshot from a secondary monitor must click in that monitor."""
        old_pause = config.execution.click_pause
        config.execution.click_pause = 0.0
        try:
            router = ActionRouter(config)
            vlm_result = {
                "action_desp": "click",
                "screen_origin": (-1920, 100),
                "parsed_action": {
                    "tool_name": "click",
                    "element": "Continue button",
                    "x": 500,
                    "y": 500,
                },
            }

            result = router.execute_vlm_action(vlm_result, (1920, 1080))

            self.assertTrue(result["success"])
            self.assertEqual(registry.cursor_x, -960)
            self.assertEqual(registry.cursor_y, 640)
        finally:
            config.execution.click_pause = old_pause

    def test_t2_f3_02_instant_click_execution(self):
        """TC-T2-F3-02: Instant Click Execution (Pause 0)"""
        old_pause = config.execution.click_pause
        config.execution.click_pause = 0.0
        
        router = ActionRouter(config)
        vlm_result = {
            "action_desp": "click",
            "parsed_action": {
                "tool_name": "click",
                "element": "Button",
                "x": 500,
                "y": 500
            }
        }
        import time
        t0 = time.time()
        res = router.execute_vlm_action(vlm_result, (1920, 1080))
        duration = time.time() - t0
        
        self.assertTrue(res["success"])
        self.assertTrue(duration < 0.1, "Should execute immediately with pause=0")
        
        config.execution.click_pause = old_pause

    def test_t2_f3_03_keyboard_typing_with_complex_emojis(self):
        """TC-T2-F3-03: Keyboard Typing with Complex Emojis"""
        router = ActionRouter(config)
        vlm_result = {
            "action_desp": "type",
            "parsed_action": {
                "tool_name": "type",
                "text": "Hello 👋",
                "submit": False
            }
        }
        
        router.execute_vlm_action(vlm_result, (1920, 1080))
        
        kb_events = [ev for ev in registry.send_input_events if ev["type"] == "keyboard"]
        scan_codes = [ev["wScan"] for ev in kb_events]
        
        # Verify ord('👋') = 128075 is split into surrogate pairs or typed as Unicode
        # Lead: 0xD83D (55357), Trail: 0xDC4B (56395)
        self.assertIn(55357, scan_codes)
        self.assertIn(56395, scan_codes)

    def test_t2_f3_04_block_banned_shortcut_alt_f4(self):
        """TC-T2-F3-04: Block Banned Shortcut Alt+F4"""
        router = ActionRouter(config)
        vlm_result = {
            "action_desp": "key_press",
            "parsed_action": {
                "tool_name": "key_press",
                "key": "alt+f4"
            }
        }
        
        res = router.execute_vlm_action(vlm_result, (1920, 1080))
        
        self.assertFalse(res["success"])
        self.assertEqual(res["detail"], "Banned shortcut blocked")
        
        # Verify no key events were recorded
        kb_events = [ev for ev in registry.send_input_events if ev["type"] == "keyboard"]
        self.assertEqual(len(kb_events), 0)

    def test_t2_f3_05_active_failsafe_boundary_trigger(self):
        """TC-T2-F3-05: Active Failsafe Boundary Trigger"""
        # Set cursor to (0,0) which triggers failsafe
        registry.cursor_x = 0
        registry.cursor_y = 0
        
        router = ActionRouter(config)
        vlm_result = {
            "action_desp": "click",
            "parsed_action": {
                "tool_name": "click",
                "element": "Button",
                "x": 500,
                "y": 500
            }
        }
        
        # Should raise RuntimeError: FailSafeException
        with self.assertRaises(RuntimeError) as context:
            router.execute_vlm_action(vlm_result, (1920, 1080))
            
        self.assertIn("FailSafeException", str(context.exception))

    def test_zero_pyautogui_static_scan(self):
        """Verify that pyautogui is completely removed and never imported in codebase"""
        root_dir = os.path.join(os.path.dirname(__file__), "..", "cogniagent")
        pyautogui_found = False
        
        for root, dirs, files in os.walk(root_dir):
            for file in files:
                if file.endswith(".py"):
                    filepath = os.path.join(root, file)
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            cleaned = "".join(line.split())
                            if "importpyautogui" in cleaned:
                                pyautogui_found = True
                                print(f"Violation: pyautogui imported in {filepath}")
                                
        self.assertFalse(pyautogui_found, "Code base must have zero pyautogui imports")
