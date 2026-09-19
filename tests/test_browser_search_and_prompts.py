"""Tests for Browser Search capability and optimized system prompts for Planner and Holo models."""

import unittest
from unittest.mock import patch, MagicMock

import tests.conftest
tests.conftest.init_mocks()

from cogniagent.tools.browser_search import (
    detect_search_intent,
    search_web,
    format_search_results,
    execute_browser_search,
)
from cogniagent.perception.vlm_engine import SYSTEM_PROMPT as VLM_SYSTEM_PROMPT
from cogniagent.gui.server_manager import (
    parse_agentic_plan,
    run_planner_chat,
    parse_model_tool_call,
    strip_tool_syntaxes,
)


class TestBrowserSearchTool(unittest.TestCase):
    def test_detect_search_intent_positive(self):
        queries = [
            ("Search for the latest Python version", "the latest Python version"),
            ("search the web for artificial intelligence news", "artificial intelligence news"),
            ("look up weather in Paris", "weather in Paris"),
            ("browse for best noise cancelling headphones", "best noise cancelling headphones"),
            ("google current stock price of Apple", "current stock price of Apple"),
            ("find online documentation for FastAPI", "documentation for FastAPI"),
            ("what is the latest release of PyTorch?", "release of PyTorch"),
            ("who is Alan Turing?", "Alan Turing"),
            ("weather forecast in Tokyo", "in Tokyo"),
        ]
        for query, expected_snippet in queries:
            is_search, extracted = detect_search_intent(query)
            self.assertTrue(is_search, f"Failed to detect search intent for: {query}")
            self.assertIn(expected_snippet.lower(), extracted.lower())

    def test_detect_search_intent_negative_for_desktop_tasks(self):
        desktop_commands = [
            "Open Edge and download the latest Python installer",
            "Click on the first search result in browser",
            "Type my password into the login box",
            "Close the Chrome window",
            "Delete old logs from Downloads folder",
            "Move invoice.pdf to Documents",
            "Organize files on my desktop",
            "can you manually search from my system in edge for the latest match schedule and provide me the answer",
            "search on my system in edge for the latest scores",
            "look up in chrome on my computer",
        ]
        for cmd in desktop_commands:
            is_search, extracted = detect_search_intent(cmd)
            self.assertFalse(is_search, f"Should not treat local desktop task as pure search: {cmd}")
            self.assertEqual(extracted, "")

    @patch("cogniagent.tools.browser_search._search_monid")
    def test_search_web_monid_structured_output(self, mock_monid):
        mock_monid.return_value = [
            {"title": "Monid AI Search Result", "href": "https://octen.ai", "snippet": "Live internet search via Monid octen provider."}
        ]
        results = search_web("monid search test")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Monid AI Search Result")
        self.assertEqual(results[0]["href"], "https://octen.ai")
        mock_monid.assert_called_once()

    @patch("cogniagent.tools.browser_search._search_monid", return_value=[])
    @patch("cogniagent.tools.browser_search._get_exa_client")
    def test_search_web_exa_structured_output(self, mock_get_client, _mock_monid):
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_item1 = MagicMock()
        mock_item1.title = "Python 3.14 Release"
        mock_item1.url = "https://python.org"
        mock_item1.highlights = ["Python 3.14 introduces performance optimizations."]
        mock_item2 = MagicMock()
        mock_item2.title = "Python Docs"
        mock_item2.url = "https://docs.python.org"
        mock_item2.highlights = ["Official documentation."]
        mock_result.results = [mock_item1, mock_item2]
        mock_client.search.return_value = mock_result
        mock_get_client.return_value = mock_client

        results = search_web("python release", max_results=2)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["title"], "Python 3.14 Release")
        self.assertEqual(results[0]["href"], "https://python.org")
        self.assertIn("Python 3.14 introduces", results[0]["snippet"])

    @patch("cogniagent.tools.browser_search._search_monid", return_value=[])
    @patch("cogniagent.tools.browser_search._search_exa", return_value=[])
    @patch("cogniagent.tools.browser_search.DDGS")
    def test_search_web_ddgs_fallback(self, mock_ddgs_cls, _mock_exa, _mock_monid):
        mock_instance = MagicMock()
        mock_instance.__enter__.return_value = mock_instance
        mock_instance.text.return_value = [
            {"title": "Python 3.14 Release", "href": "https://python.org", "body": "Python 3.14 introduces..."},
            {"title": "Python Docs", "href": "https://docs.python.org", "body": "Official documentation."},
        ]
        mock_ddgs_cls.return_value = mock_instance

        results = search_web("python release", max_results=2)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["title"], "Python 3.14 Release")
        self.assertEqual(results[0]["href"], "https://python.org")
        self.assertIn("Python 3.14 introduces", results[0]["snippet"])

    def test_format_search_results_markup(self):
        sample = [
            {"title": "Rust vs Python", "href": "https://example.com/rust-python", "snippet": "Performance comparison..."},
        ]
        formatted = format_search_results(sample, query="Rust vs Python")
        self.assertIn("<browser_search_results query=\"Rust vs Python\">", formatted)
        self.assertIn("[1] Rust vs Python", formatted)
        self.assertIn("URL: https://example.com/rust-python", formatted)
        self.assertIn("Summary: Performance comparison...", formatted)
        self.assertIn("</browser_search_results>", formatted)

    @patch("cogniagent.tools.browser_search._search_monid", return_value=[])
    @patch("cogniagent.tools.browser_search._search_exa", return_value=[])
    @patch("cogniagent.tools.browser_search._search_ddg_html", side_effect=Exception("Network timeout"))
    @patch("cogniagent.tools.browser_search.DDGS", side_effect=Exception("Network timeout"))
    def test_search_web_handles_network_failure_gracefully(self, _mock_ddgs, _mock_html, _mock_exa, _mock_monid):
        results = search_web("failing query")
        self.assertEqual(results, [])

    @patch("cogniagent.tools.browser_search._search_monid", return_value=[])
    @patch("cogniagent.tools.browser_search._search_exa", return_value=[])
    @patch("cogniagent.tools.browser_search._search_ddg_html")
    @patch("cogniagent.tools.browser_search.DDGS", side_effect=Exception("403 Forbidden Ratelimit"))
    def test_search_web_falls_back_to_html_on_ddgs_403(self, _mock_ddgs, mock_html, _mock_exa, _mock_monid):
        mock_html.return_value = [
            {"title": "HTML Fallback Result", "href": "https://example.com", "snippet": "Unblocked general search content"}
        ]
        results = search_web("quantum computing")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "HTML Fallback Result")
        mock_html.assert_called_once()



class TestPlannerBrowserSearchIntegration(unittest.TestCase):
    @patch("cogniagent.gui.server_manager.start_planner_server", return_value=True)
    @patch("cogniagent.gui.server_manager.stop_planner_server")
    @patch("cogniagent.gui.server_manager.execute_browser_search")
    @patch("cogniagent.gui.server_manager.requests.post")
    def test_planner_resolves_search_directly_without_holo_plan(
        self, mock_post, mock_search, _mock_stop, _mock_start
    ):
        mock_search.return_value = (
            "<browser_search_results query=\"latest Python release\">\n"
            "[1] Python 3.14 Released\n"
            "    URL: https://python.org\n"
            "    Summary: Python 3.14 is now stable.\n"
            "</browser_search_results>"
        )

        resp1 = MagicMock(status_code=200)
        resp1.json.return_value = {
            "choices": [{"message": {"content": "Let me look that up. [BROWSER_SEARCH: latest Python release]"}}]
        }
        resp2 = MagicMock(status_code=200)
        resp2.json.return_value = {
            "choices": [{
                "message": {
                    "content": (
                        "According to python.org, Python 3.14 is the latest stable release! "
                        "Key improvements include a faster JIT compiler and enhanced concurrency."
                    )
                }
            }]
        }
        mock_post.side_effect = [resp1, resp2]

        result = run_planner_chat("Search for the latest Python release", [])

        # Verify browser search was triggered autonomously by model reasoning
        mock_search.assert_called_once_with("latest Python release", max_results=5)

        # Verify output answers conversationally without a desktop-plan
        self.assertIn("Python 3.14 is the latest stable release", result)
        parsed = parse_agentic_plan(result)
        self.assertFalse(parsed["has_plan"], "Search task should resolve directly without creating a desktop plan for Holo")

    @patch("cogniagent.gui.server_manager.start_planner_server", return_value=True)
    @patch("cogniagent.gui.server_manager.stop_planner_server")
    @patch("cogniagent.gui.server_manager.execute_browser_search")
    @patch("cogniagent.gui.server_manager.requests.post")
    def test_planner_handles_autonomous_browser_search_tag(
        self, mock_post, mock_search, _mock_stop, _mock_start
    ):
        mock_search.return_value = "[1] Quantum Computing breakthrough 2026"

        # First LLM response requests browser search; second LLM response provides final answer
        resp1 = MagicMock(status_code=200)
        resp1.json.return_value = {
            "choices": [{"message": {"content": "I'll look that up for you. [BROWSER_SEARCH: quantum computing 2026]"}}]
        }
        resp2 = MagicMock(status_code=200)
        resp2.json.return_value = {
            "choices": [{"message": {"content": "Recent 2026 breakthroughs in quantum computing include 10,000 physical qubits."}}]
        }
        mock_post.side_effect = [resp1, resp2]

        result = run_planner_chat("Tell me about recent quantum computing breakthroughs", [])

        mock_search.assert_called_once_with("quantum computing 2026", max_results=5)
        self.assertEqual(mock_post.call_count, 2)
        self.assertIn("Recent 2026 breakthroughs in quantum computing", result)
        parsed = parse_agentic_plan(result)
        self.assertFalse(parsed["has_plan"])

    @patch("cogniagent.gui.server_manager.start_planner_server", return_value=True)
    @patch("cogniagent.gui.server_manager.stop_planner_server")
    @patch("cogniagent.gui.server_manager.execute_browser_search")
    @patch("cogniagent.gui.server_manager.requests.post")
    def test_planner_strips_tool_tags_from_user_visible_chat(
        self, mock_post, mock_search, _mock_stop, _mock_start
    ):
        mock_search.return_value = "[1] Result"
        resp1 = MagicMock(status_code=200)
        resp1.json.return_value = {
            "choices": [{"message": {"content": "```\n[BROWSER_SEARCH: cricket today]\n```\nHere is some preface."}}]
        }
        resp2 = MagicMock(status_code=200)
        resp2.json.return_value = {
            "choices": [{"message": {"content": "Here are the live cricket findings without any leaked tags."}}]
        }
        mock_post.side_effect = [resp1, resp2]
        result = run_planner_chat("cricket today", [])
        self.assertNotIn("BROWSER_SEARCH", result)
        self.assertIn("Here are the live cricket findings without any leaked tags.", result)

    @patch("cogniagent.gui.server_manager.start_planner_server", return_value=True)
    @patch("cogniagent.gui.server_manager.stop_planner_server")
    @patch("cogniagent.gui.server_manager.execute_browser_search")
    @patch("cogniagent.gui.server_manager.requests.post")
    def test_planner_creates_desktop_plan_for_manual_desktop_request(
        self, mock_post, mock_search, _mock_stop, _mock_start
    ):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {
            "choices": [{
                "message": {
                    "content": (
                        "```desktop-plan\n"
                        "1. Open Microsoft Edge from the taskbar\n"
                        "2. In Edge, navigate to skysports.com/cricket\n"
                        "3. Find today's match schedule\n"
                        "**Expected Output:** Today's match schedule displayed on screen\n"
                        "Prescribed Steps: 25\n"
                        "```"
                    )
                }
            }]
        }
        mock_post.return_value = mock_resp

        result = run_planner_chat("can you manually search from my system in edge for the latest match schedule and provide me the answer", [])

        # Verify headless browser search was NOT triggered
        mock_search.assert_not_called()

        # Verify plan was parsed
        parsed = parse_agentic_plan(result)
        self.assertTrue(parsed["has_plan"], "Manual desktop request should generate a desktop plan for Holo")
        self.assertEqual(len(parsed["steps"]), 3)

    def test_parse_model_tool_call_formats(self):
        # 1. Partial/open JSON stream (exact user scenario)
        user_scenario = '[\n{\n"tool": "BROWSER_SEARCH",\n"query": "cricket match schedule today"\n'
        name, args = parse_model_tool_call(user_scenario)
        self.assertEqual(name, "BROWSER_SEARCH")
        self.assertEqual(args.get("query"), "cricket match schedule today")

        # 2. Complete JSON array
        json_array = '[{"tool": "BROWSER_SEARCH", "query": "latest AI news"}]'
        name, args = parse_model_tool_call(json_array)
        self.assertEqual(name, "BROWSER_SEARCH")
        self.assertEqual(args.get("query"), "latest AI news")

        # 3. Complete JSON object with name & arguments
        json_obj = '{"name": "FIND_FILES", "arguments": {"pattern": "*.py"}}'
        name, args = parse_model_tool_call(json_obj)
        self.assertEqual(name, "FIND_FILES")
        self.assertEqual(args.get("pattern"), "*.py")

        # 4. Standard bracket tag format
        tag_str = '[BROWSER_SEARCH: weather in Tokyo]'
        name, args = parse_model_tool_call(tag_str)
        self.assertEqual(name, "BROWSER_SEARCH")
        self.assertEqual(args.get("query"), "weather in Tokyo")

        # 5. Non-tool text
        name, args = parse_model_tool_call("Hello, how can I help you today?")
        self.assertIsNone(name)
        self.assertEqual(args, {})

    def test_strip_tool_syntaxes_removes_json_and_orphan_brackets(self):
        # Unclosed JSON stream
        user_raw = '[\n{\n"tool": "BROWSER_SEARCH",\n"query": "cricket match schedule today"\n'
        self.assertEqual(strip_tool_syntaxes(user_raw), "")

        # JSON inside markdown code block with text
        markdown_raw = "I'll look into that for you.\n```json\n[{\"tool\": \"BROWSER_SEARCH\", \"query\": \"cricket\"}]\n```"
        self.assertEqual(strip_tool_syntaxes(markdown_raw), "I'll look into that for you.")

        # Bracket tag
        tag_raw = "[BROWSER_SEARCH: test query] Here are the findings."
        self.assertEqual(strip_tool_syntaxes(tag_raw), "Here are the findings.")

    @patch("cogniagent.gui.server_manager.start_planner_server", return_value=True)
    @patch("cogniagent.gui.server_manager.stop_planner_server")
    @patch("cogniagent.gui.server_manager.execute_browser_search")
    @patch("cogniagent.gui.server_manager.requests.post")
    def test_planner_handles_json_tool_call_stream(
        self, mock_post, mock_search, _mock_stop, _mock_start
    ):
        mock_search.return_value = (
            "<browser_search_results query=\"cricket match schedule today\">\n"
            "[1] England vs Sri Lanka 3rd T20I\n"
            "    URL: https://skysports.com/cricket\n"
            "</browser_search_results>"
        )

        # Pass 1: Model emits JSON format tool call (as happened in the live scenario)
        resp1 = MagicMock(status_code=200)
        resp1.json.return_value = {
            "choices": [{
                "message": {
                    "content": '[\n{\n"tool": "BROWSER_SEARCH",\n"query": "cricket match schedule today"'
                }
            }]
        }
        # Pass 2: Model synthesizes response based on verified search findings
        resp2 = MagicMock(status_code=200)
        resp2.json.return_value = {
            "choices": [{
                "message": {
                    "content": "Today's marquee cricket match is England vs Sri Lanka (3rd T20I) starting at 2:30pm."
                }
            }]
        }
        mock_post.side_effect = [resp1, resp2]

        result = run_planner_chat("what is the cricket match schedule today", [])

        # Verify search was executed with the parsed query
        mock_search.assert_called_once_with("cricket match schedule today", max_results=5)

        # Verify JSON was not leaked into the user chat and synthesized answer was returned
        self.assertNotIn('"tool": "BROWSER_SEARCH"', result)
        self.assertNotIn('"query"', result)
        self.assertIn("England vs Sri Lanka", result)
        parsed = parse_agentic_plan(result)
        self.assertFalse(parsed["has_plan"])


class TestSystemPromptsEfficiency(unittest.TestCase):
    def test_holo_vlm_system_prompt_is_token_efficient(self):
        words = VLM_SYSTEM_PROMPT.split()
        # Prompt must be concise and under 180 words for fast 4B vision processing
        self.assertLess(len(words), 180, f"Holo VLM prompt is too verbose: {len(words)} words")

        # Must maintain all vital operational guarantees
        self.assertIn("[0, 1000]", VLM_SYSTEM_PROMPT)
        self.assertIn("Visual Grounding", VLM_SYSTEM_PROMPT)
        self.assertIn("No Repetition", VLM_SYSTEM_PROMPT)
        self.assertIn("note", VLM_SYSTEM_PROMPT)
        self.assertIn("terminate", VLM_SYSTEM_PROMPT)
        self.assertIn("hitl_intervention", VLM_SYSTEM_PROMPT)

    @patch("cogniagent.gui.server_manager.start_planner_server", return_value=True)
    @patch("cogniagent.gui.server_manager.stop_planner_server")
    @patch("cogniagent.gui.server_manager.requests.post")
    def test_planner_system_prompt_contains_browser_search_and_plan_separation(
        self, mock_post, _stop, _start
    ):
        captured_messages = []

        def capture_call(*args, **kwargs):
            captured_messages.extend(kwargs.get("json", {}).get("messages", []))
            resp = MagicMock(status_code=200)
            resp.json.return_value = {"choices": [{"message": {"content": "Hello!"}}]}
            return resp

        mock_post.side_effect = capture_call
        run_planner_chat("Hello", [])

        system_message = next((m["content"] for m in captured_messages if m.get("role") == "system"), "")
        self.assertTrue(system_message)
        words = system_message.split()
        self.assertLess(len(words), 230, f"Planner prompt too verbose: {len(words)} words")
        self.assertIn("BROWSER_SEARCH", system_message)
        self.assertIn("desktop-plan", system_message)
        self.assertIn("DIRECT ANSWERS & RESEARCH", system_message)

