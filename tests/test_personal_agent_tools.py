"""Tests for Personal Agent Tools: find_local_files, send_notification, and read_webpage."""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import tests.conftest
tests.conftest.init_mocks()

from cogniagent.tools.file_search import (
    find_local_files,
    format_file_results,
    detect_file_search_intent,
)
from cogniagent.tools.notifications import (
    send_notification,
    detect_notification_intent,
)
from cogniagent.tools.web_reader import (
    read_webpage,
    format_webpage_summary,
    detect_webpage_read_intent,
)
from cogniagent.gui.server_manager import parse_agentic_plan, run_planner_chat


class TestFileSearchTool(unittest.TestCase):
    def test_find_local_files_in_directory(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_file = os.path.join(tmp_dir, "quarterly_budget.xlsx")
            with open(test_file, "w") as f:
                f.write("test content")

            results = find_local_files("*.xlsx", search_roots=[tmp_dir])
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["name"], "quarterly_budget.xlsx")
            self.assertEqual(results[0]["path"], os.path.abspath(test_file))

    @patch("cogniagent.tools.file_search._find_everything_cli")
    @patch("cogniagent.tools.file_search.subprocess.run")
    def test_find_local_files_everything_cli_integration(self, mock_run, mock_find_cli):
        mock_find_cli.return_value = r"C:\Program Files\Everything\es.exe"
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = r"C:\Users\User\Documents\report.pdf" + "\n"
        mock_run.return_value = mock_proc

        with patch("os.path.exists", return_value=True), patch("os.stat") as mock_stat:
            mock_s = MagicMock()
            mock_s.st_size = 20480
            mock_s.st_mtime = 1700000000
            mock_stat.return_value = mock_s

            results = find_local_files("report.pdf")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["name"], "report.pdf")
            self.assertEqual(results[0]["path"], r"C:\Users\User\Documents\report.pdf")
            self.assertEqual(results[0]["size_kb"], 20.0)

    def test_format_file_results_markup(self):
        sample = [{
            "name": "invoice_2026.pdf",
            "path": r"D:\Documents\invoice_2026.pdf",
            "size_kb": 250.0,
            "modified": "2026-09-18 10:00",
        }]
        formatted = format_file_results(sample, pattern="invoice*")
        self.assertIn("<local_file_search_results pattern=\"invoice*\">", formatted)
        self.assertIn("invoice_2026.pdf", formatted)
        self.assertIn(r"D:\Documents\invoice_2026.pdf", formatted)

    def test_detect_file_search_intent(self):
        queries = [
            ("where is report.pdf", "report.pdf"),
            ("find local files matching *.gguf", "*.gguf"),
            ("locate the file named taxes.xlsx", "taxes.xlsx"),
            ("show me my file invoice.pdf", "invoice.pdf"),
        ]
        for q, expected in queries:
            is_file_search, extracted = detect_file_search_intent(q)
            self.assertTrue(is_file_search, f"Failed on query: {q}")
            self.assertIn(expected, extracted)

        # Destructive command should not be treated as file search intent
        is_search, _ = detect_file_search_intent("delete file report.pdf")
        self.assertFalse(is_search)


class TestNotificationTool(unittest.TestCase):
    @patch("cogniagent.tools.notifications.winotify")
    def test_send_notification_via_winotify(self, mock_winotify):
        mock_toast = MagicMock()
        mock_winotify.Notification.return_value = mock_toast

        success = send_notification("OmniVLA Complete", "Task finished successfully")
        self.assertTrue(success)
        mock_winotify.Notification.assert_called_once()
        mock_toast.show.assert_called_once()

    @patch("cogniagent.tools.notifications.winotify", None)
    def test_missing_native_notifier_is_not_reported_as_delivered(self):
        self.assertFalse(send_notification("Alert", "Done"))

    def test_detect_notification_intent(self):
        queries = [
            ("send me a notification with title 'Alert' and message 'Meeting in 5 mins'", "Alert", "Meeting in 5 mins"),
            ("send a notification saying 'Task completed'", "OmniVLA Reminder", "Task completed"),
            ("remind me to check the oven", "OmniVLA Reminder", "check the oven"),
        ]
        for q, expected_title, expected_msg in queries:
            is_notify, title, msg = detect_notification_intent(q)
            self.assertTrue(is_notify, f"Failed on: {q}")
            self.assertEqual(title, expected_title)
            self.assertIn(expected_msg.lower(), msg.lower())

        # Non-notification prompt
        is_notify, _, _ = detect_notification_intent("Hello, how are you?")
        self.assertFalse(is_notify)


class TestWebReaderTool(unittest.TestCase):
    @patch("cogniagent.tools.web_reader._public_destination", return_value=True)
    @patch("requests.get")
    @patch("cogniagent.tools.web_reader.trafilatura")
    def test_read_webpage_via_trafilatura(self, mock_traf, mock_get, _public):
        response=MagicMock(status_code=200, headers={"Content-Type":"text/html"}, encoding="utf-8")
        response.iter_content.return_value=[b"<html>mock html</html>"]
        mock_get.return_value.__enter__.return_value=response
        mock_traf.extract.return_value = "# Article Title\n\nThis is clean markdown content."
        mock_meta = MagicMock()
        mock_meta.title = "Article Title"
        mock_traf.extract_metadata.return_value = mock_meta

        page = read_webpage("https://example.com/article")
        self.assertTrue(page["success"])
        self.assertEqual(page["title"], "Article Title")
        self.assertIn("This is clean markdown content", page["text"])

    def test_format_webpage_summary_markup(self):
        sample = {
            "title": "Release Notes",
            "url": "https://example.com/notes",
            "text": "Version 2.0 released today.",
            "success": True,
        }
        formatted = format_webpage_summary(sample)
        self.assertIn("<webpage_content url=\"https://example.com/notes\">", formatted)
        self.assertIn("Title: Release Notes", formatted)
        self.assertIn("Version 2.0 released today.", formatted)

    def test_detect_webpage_read_intent(self):
        queries = [
            ("read this webpage: https://python.org", "https://python.org"),
            ("summarize https://example.com/article for me", "https://example.com/article"),
            ("what does https://docs.github.com say?", "https://docs.github.com"),
        ]
        for q, expected_url in queries:
            is_read, url = detect_webpage_read_intent(q)
            self.assertTrue(is_read, f"Failed on: {q}")
            self.assertEqual(url, expected_url)

        is_read, _ = detect_webpage_read_intent("search for best laptops")
        self.assertFalse(is_read)


class TestPlannerPersonalAgentIntegration(unittest.TestCase):
    @patch("cogniagent.gui.server_manager.start_planner_server", return_value=True)
    @patch("cogniagent.gui.server_manager.stop_planner_server")
    @patch("cogniagent.gui.server_manager.find_local_files")
    @patch("cogniagent.gui.server_manager.requests.post")
    def test_planner_autonomous_find_files(self, mock_post, mock_files, _stop, _start):
        mock_files.return_value = [{
            "name": "model.gguf",
            "path": r"D:\Programming\FYP\models\model.gguf",
            "size_kb": 1024000.0,
            "modified": "2026-09-14 12:00",
        }]

        # Turn 1: model emits [FIND_FILES: *.gguf]; Turn 2: model provides synthesized direct answer
        resp1 = MagicMock(status_code=200)
        resp1.json.return_value = {
            "choices": [{"message": {"content": "Searching for files. [FIND_FILES: *.gguf]"}}]
        }
        resp2 = MagicMock(status_code=200)
        resp2.json.return_value = {
            "choices": [{"message": {"content": "Found 1 matching model file at D:\\Programming\\FYP\\models\\model.gguf."}}]
        }
        mock_post.side_effect = [resp1, resp2]

        result = run_planner_chat("Locate any GGUF models on my computer", [])
        mock_files.assert_called_once_with("*.gguf")
        self.assertEqual(mock_post.call_count, 2)
        self.assertIn("Found 1 matching model file", result)
        parsed = parse_agentic_plan(result)
        self.assertFalse(parsed["has_plan"])

    @patch("cogniagent.gui.server_manager.start_planner_server", return_value=True)
    @patch("cogniagent.gui.server_manager.stop_planner_server")
    @patch("cogniagent.gui.server_manager.read_webpage")
    @patch("cogniagent.gui.server_manager.requests.post")
    def test_planner_autonomous_read_webpage(self, mock_post, mock_read, _stop, _start):
        mock_read.return_value = {
            "title": "FastAPI Guide",
            "url": "https://fastapi.tiangolo.com",
            "text": "FastAPI is a modern, fast web framework.",
            "success": True,
        }

        resp1 = MagicMock(status_code=200)
        resp1.json.return_value = {
            "choices": [{"message": {"content": "Inspecting link. [READ_WEBPAGE: https://fastapi.tiangolo.com]"}}]
        }
        resp2 = MagicMock(status_code=200)
        resp2.json.return_value = {
            "choices": [{"message": {"content": "FastAPI is a modern web framework designed for high performance."}}]
        }
        mock_post.side_effect = [resp1, resp2]

        result = run_planner_chat("Please check the official FastAPI documentation page", [])
        mock_read.assert_called_once_with("https://fastapi.tiangolo.com")
        self.assertEqual(mock_post.call_count, 2)
        self.assertIn("FastAPI is a modern web framework", result)
        parsed = parse_agentic_plan(result)
        self.assertFalse(parsed["has_plan"])

    @patch("cogniagent.gui.server_manager.start_planner_server", return_value=True)
    @patch("cogniagent.gui.server_manager.stop_planner_server")
    @patch("cogniagent.gui.server_manager.send_notification")
    @patch("cogniagent.gui.server_manager.requests.post")
    def test_planner_autonomous_notify(self, mock_post, mock_notify, _stop, _start):
        mock_notify.return_value = True

        resp1 = MagicMock(status_code=200)
        resp1.json.return_value = {
            "choices": [{"message": {"content": "Triggering notification. [NOTIFY: Break Time | Remember to stretch]"}}]
        }
        resp2 = MagicMock(status_code=200)
        resp2.json.return_value = {
            "choices": [{"message": {"content": "I have sent a Windows desktop notification to remind you to stretch."}}]
        }
        mock_post.side_effect = [resp1, resp2]

        result = run_planner_chat("Let me know when you finish reviewing my code", [])
        mock_notify.assert_called_once_with("Break Time", "Remember to stretch")
        self.assertEqual(mock_post.call_count, 2)
        self.assertIn("sent a Windows desktop notification", result)
        parsed = parse_agentic_plan(result)
        self.assertFalse(parsed["has_plan"])

    @patch("cogniagent.gui.server_manager.start_planner_server", return_value=True)
    @patch("cogniagent.gui.server_manager.stop_planner_server")
    @patch("cogniagent.gui.server_manager.read_webpage")
    @patch("cogniagent.gui.server_manager.requests.post")
    def test_planner_upfront_webpage_read(self, mock_post, mock_read, _stop, _start):
        mock_read.return_value = {
            "title": "Python Docs",
            "url": "https://docs.python.org",
            "text": "Python is dynamic.",
            "success": True,
        }
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "The Python documentation highlights its dynamic typing."}}]
        }
        mock_post.return_value = mock_resp

        result = run_planner_chat("read this webpage: https://docs.python.org", [])
        mock_read.assert_called_once_with("https://docs.python.org")
        self.assertIn("Python documentation highlights", result)

    @patch("cogniagent.gui.server_manager.start_planner_server", return_value=True)
    @patch("cogniagent.gui.server_manager.stop_planner_server")
    @patch("cogniagent.gui.server_manager.send_notification")
    @patch("cogniagent.gui.server_manager.requests.post")
    def test_planner_upfront_notification(self, mock_post, mock_notify, _stop, _start):
        mock_notify.return_value = True
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "I have sent the toast notification."}}]
        }
        mock_post.return_value = mock_resp

        result = run_planner_chat("send me a notification with title 'Alert' and message 'Done'", [])
        mock_notify.assert_called_once_with("Alert", "Done")
        self.assertIn("sent the toast notification", result)
