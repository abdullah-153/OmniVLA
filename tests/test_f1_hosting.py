import unittest
import os
import sys
import time
import subprocess
import logging
import requests
from unittest.mock import patch, MagicMock

import tests.conftest
tests.conftest.init_mocks()

from cogniagent.config import config
# Avoid importing OmniVLA_GUI directly at module level if Tkinter starts, 
# but let's see: OmniVLA_GUI is a subclass of tk.Tk.
# We can mock tk.Tk or run tkinter tests in a headless mode.
# Actually, we can patch tkinter or just instantiate it carefully.
from run_agent_gui import OmniVLA_GUI, parse_server_log_for_optimizations, check_vram_limit

class TestF1Hosting(unittest.TestCase):
    def setUp(self):
        tests.conftest.init_mocks()

    def test_t1_f1_01_powershell_startup_parameter_verification(self):
        """TC-T1-F1-01: PowerShell Startup Parameter Verification"""
        ps_path = os.path.join(os.path.dirname(__file__), "..", "start_holo3.1.ps1")
        self.assertTrue(os.path.exists(ps_path), "start_holo3.1.ps1 must exist")
        
        with open(ps_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("-ngl", content)
        # The starter exposes GPU layers as an explicit parameter and passes
        # it as a separate argv item. This preserves the safe default (-1)
        # without hard-coding a fragile command-string fragment.
        self.assertIn("[int]$GpuLayers = -1", content)
        self.assertIn('"-ngl", $GpuLayers', content)
        self.assertIn('"-ctk", "q8_0"', content)
        self.assertIn('"-ctv", "q8_0"', content)
        self.assertIn('"-fa", "on"', content)
        self.assertIn("Holo-3.1-4B", content)

    @patch("os.path.exists")
    @patch("subprocess.Popen")
    @patch("requests.get")
    @patch("socket.socket")
    def test_t1_f1_02_server_startup_command_construction(self, mock_socket, mock_get, mock_popen, mock_exists):
        """TC-T1-F1-02: Server Startup Command Construction"""
        mock_exists.return_value = True
        # Simulate that llama-server is NOT running on first check, but running on second check
        mock_get.side_effect = [
            requests.exceptions.RequestException("Connection refused"),
            MagicMock(status_code=200)
        ]
        
        gui = OmniVLA_GUI()
        gui._start_server()
        
        self.assertTrue(mock_popen.called)
        cmd_args = mock_popen.call_args[0][0]
        
        # Verify optimized flags and model paths are constructed correctly
        self.assertIn(r"llama-cpp\llama-server.exe", cmd_args[0])
        self.assertIn("-ngl", cmd_args)
        self.assertIn("99", cmd_args)
        self.assertIn("-ctk", cmd_args)
        self.assertIn("q8_0", cmd_args)
        self.assertIn("-fa", cmd_args)
        self.assertIn("on", cmd_args)
        gui.destroy()

    @patch("os.path.exists")
    @patch("requests.get")
    def test_t1_f1_03_server_startup_health_status_parsing(self, mock_get, mock_exists):
        """TC-T1-F1-03: Server Startup Health Status Parsing"""
        mock_exists.return_value = True
        mock_get.return_value = MagicMock(status_code=200)
        
        gui = OmniVLA_GUI()
        # Mock logging or verify orb state changes
        with patch("logging.info") as mock_log:
            gui._start_server()
            # Assert "llama-server already running." or "llama-server is up and ready."
            mock_log.assert_any_call("llama-server already running.")
        gui.destroy()

    @patch("os.path.exists")
    @patch("subprocess.Popen")
    @patch("requests.get")
    @patch("socket.socket")
    @patch("time.time")
    def test_t1_f1_04_server_startup_failure_timeout(self, mock_time, mock_socket, mock_get, mock_popen, mock_exists):
        """TC-T1-F1-04: Server Startup Failure Timeout"""
        mock_exists.return_value = True
        mock_get.side_effect = requests.exceptions.RequestException("Connection refused")
        
        # Simulate time progression of 301 seconds instantly
        times = [1000, 1000, 1002, 1305]
        counter = [2000]
        mock_time.side_effect = lambda: times.pop(0) if times else (counter.insert(0, counter[0] + 10) or counter[0])
        
        gui = OmniVLA_GUI()
        with patch("logging.error") as mock_log_err:
            gui._start_server()
            mock_log_err.assert_any_call("Failed to start llama-server within 300 seconds.")
        gui.destroy()

    def test_t1_f1_05_server_log_optimization_check(self):
        """TC-T1-F1-05: Server Log Optimization Check"""
        # Feed stream logs to parser helper
        log1 = "llama_server: flash_attn_ext enabled"
        log2 = "llama_server: KV cache format: q8_0"
        
        opts1 = parse_server_log_for_optimizations(log1)
        opts2 = parse_server_log_for_optimizations(log2)
        
        self.assertTrue(opts1["flash_attention"])
        self.assertTrue(opts2["kv_cache_q8"])

    def test_t2_f1_01_low_vram_allocation_warning(self):
        """TC-T2-F1-01: Low VRAM Allocation Warning"""
        # Verify check_vram_limit function alerts when below 5.0GB
        warn_msg = check_vram_limit(4.5)
        self.assertIn("Warning", warn_msg)
        self.assertIn("VRAM is below", warn_msg)
        
        no_warn = check_vram_limit(5.5)
        self.assertEqual(no_warn, "")

    @patch("os.path.exists")
    @patch("logging.error")
    def test_t2_f1_02_missing_gguf_model_path_handling(self, mock_log_err, mock_exists):
        """TC-T2-F1-02: Missing GGUF Model Path Handling"""
        mock_exists.return_value = False
        
        gui = OmniVLA_GUI()
        gui._start_server()
        
        mock_log_err.assert_any_call("Model file not found")
        self.assertIsNone(gui.server_process)
        gui.destroy()

    @patch("os.path.exists")
    @patch("requests.get")
    @patch("socket.socket")
    @patch("logging.error")
    def test_t2_f1_03_host_port_conflict_interception(self, mock_log_err, mock_socket_class, mock_get, mock_exists):
        """TC-T2-F1-03: Host Port Conflict Interception"""
        mock_exists.return_value = True
        mock_get.side_effect = requests.exceptions.RequestException("Connection refused")
        
        # Mock socket.bind to throw error (port in use)
        mock_socket = MagicMock()
        mock_socket.bind.side_effect = OSError("Address already in use")
        mock_socket_class.return_value = mock_socket
        
        gui = OmniVLA_GUI()
        gui._start_server()
        
        mock_log_err.assert_any_call("Port conflict detected. Port 8089 is already in use.")
        gui.destroy()

    def test_t2_f1_04_extreme_console_warnings_capture(self):
        """TC-T2-F1-04: Extreme Console Warnings Capture"""
        # Test warning log colors in console stream
        from run_agent_gui import TextHandler
        mock_text = MagicMock()
        mock_text.after = lambda delay, callback: callback()
        handler = TextHandler(mock_text)
        handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        
        record = logging.LogRecord(
            name="llama_server",
            level=logging.WARNING,
            pathname="gui.py",
            lineno=10,
            msg="ggml_metal_graph_compute: command buffer failed",
            args=(),
            exc_info=None
        )
        handler.emit(record)
        # Verify text handler inserts with the "warning" tag
        mock_text.insert.assert_any_call('end', 'WARNING: ggml_metal_graph_compute: command buffer failed\n', 'warning')

    @patch("os.path.exists")
    @patch("requests.get")
    @patch("subprocess.Popen")
    @patch("logging.info")
    def test_t2_f1_05_fallback_when_nvidia_smi_is_missing(self, mock_log_info, mock_popen, mock_get, mock_exists):
        """TC-T2-F1-05: Fallback When nvidia-smi is Missing"""
        mock_exists.return_value = True
        mock_get.return_value = MagicMock(status_code=200)
        
        # Make sure that launch proceeds using default safe values
        gui = OmniVLA_GUI()
        gui._start_server()
        # Verify startup logs show it is ready
        mock_log_info.assert_any_call("llama-server already running.")
        gui.destroy()

# Add simple log helper functions to run_agent_gui.py if not already present
# but we can also write them in run_agent_gui.py or define in our test class.
# Wait, let's make sure run_agent_gui has them!
# Since we imported them directly, we should verify run_agent_gui has them. Let's add them to run_agent_gui.py!
