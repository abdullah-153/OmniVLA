from unittest.mock import MagicMock, patch
import pytest
import threading
from cogniagent.runtime.cancellation import PlannerCancelled

from cogniagent.gui import server_manager


def reply(text):
    response = MagicMock(status_code=200)
    response.json.return_value = {"choices": [{"message": {"content": text}}]}
    return response


@pytest.mark.parametrize("text", [
    "<tool_call>FIND_FILES: status</tool_call>",
    "I'll search.<tool_call>FIND_FILES: status</arg_value></tool_call>",
])
def test_closed_read_only_xml_tool_variant(text):
    assert server_manager.parse_model_tool_call(text) == ("FIND_FILES", {"pattern": "status"})


@pytest.mark.parametrize("text", [
    "<tool_call>FIND_FILES: status",
    "<tool_call>NOTIFY: sent | done</tool_call>",
    "<tool_call>FIND_FILES: <instruction>status</instruction></tool_call>",
])
def test_xml_variant_rejects_partial_nested_and_effectful_calls(text):
    assert server_manager.parse_model_tool_call(text) == (None, {})


def test_planner_can_discover_then_read_and_answer(tmp_path):
    report = tmp_path / "report.md"
    report.write_text("Atlas milestone complete.", encoding="utf-8")
    receipts = []
    with patch.object(server_manager, "start_planner_server", return_value=True), \
         patch.object(server_manager, "stop_planner_server"), \
         patch.object(server_manager, "find_local_files", return_value=[{"name": report.name, "path": str(report)}]), \
         patch.object(server_manager.requests, "post", side_effect=[
             reply("[FIND_FILES: report.md]"), reply(f"[READ_LOCAL_FILE: {report}]"),
             reply("Atlas milestone is complete according to the report.")]) as model:
        answer = server_manager.run_planner_chat("Check the project status", [],
            learn_personal_context_enabled=False, tool_result_callback=receipts.append)
    assert "according to the report" in answer
    assert model.call_count == 3
    assert [receipt.name for receipt in receipts] == ["FIND_FILES", "READ_LOCAL_FILE"]
    assert receipts[-1].artifact_sha256


def test_failed_upfront_read_discovery_never_reads_an_earlier_match(tmp_path):
    old_report = tmp_path / "old.md"
    old_report.write_text("Outdated status", encoding="utf-8")
    receipts = []
    with patch.object(server_manager, "start_planner_server", return_value=True), \
         patch.object(server_manager, "stop_planner_server"), \
         patch.object(server_manager, "detect_file_search_intent", return_value=(True, "old.md")), \
         patch.object(server_manager, "detect_local_file_read_intent", return_value=(True, "new.md")), \
         patch.object(server_manager, "find_local_files", side_effect=[
             [{"name": old_report.name, "path": str(old_report)}], OSError("Search failed")]), \
         patch.object(server_manager, "read_local_text_file") as read_file, \
         patch.object(server_manager.requests, "post", return_value=reply("The file search failed.")) as model:
        server_manager.run_planner_chat("Find old.md and read new.md", [],
            user_profile_context="No defaults.", learn_personal_context_enabled=False,
            tool_result_callback=receipts.append)
    read_file.assert_not_called()
    assert [(r.name, r.ok) for r in receipts] == [("FIND_FILES", True), ("FIND_FILES", False)]
    prompt = model.call_args.kwargs["json"]["messages"][0]["content"]
    assert "file search failed" in prompt


def test_repeated_tool_call_stops_without_claiming_completion():
    with patch.object(server_manager, "start_planner_server", return_value=True), \
         patch.object(server_manager, "stop_planner_server"), \
         patch.object(server_manager, "execute_browser_search", return_value="No results") as search, \
         patch.object(server_manager.requests, "post", return_value=reply("[BROWSER_SEARCH: atlas]")) as model:
        answer = server_manager.run_planner_chat("Investigate Atlas", [], learn_personal_context_enabled=False)
    assert "not confirmed complete" in answer
    assert search.call_count == 1 and model.call_count == 2


def test_tool_sequence_has_finite_budget():
    with patch.object(server_manager, "start_planner_server", return_value=True), \
         patch.object(server_manager, "stop_planner_server"), \
         patch.object(server_manager, "execute_browser_search", return_value="Results") as search, \
         patch.object(server_manager.requests, "post", side_effect=[reply(f"[BROWSER_SEARCH: query {i}]") for i in range(4)]) as model:
        answer = server_manager.run_planner_chat("Investigate Atlas", [], learn_personal_context_enabled=False)
    assert "tool-call limit" in answer
    assert search.call_count == 3 and model.call_count == 4


def test_empty_planner_response_is_failure():
    with patch.object(server_manager, "start_planner_server", return_value=True), \
         patch.object(server_manager, "stop_planner_server"), \
         patch.object(server_manager.requests, "post", return_value=reply("")):
        with pytest.raises(RuntimeError, match="empty response"):
            server_manager.run_planner_chat("Investigate Atlas", [], learn_personal_context_enabled=False)


def test_stop_during_model_reply_prevents_late_notification():
    event = threading.Event()
    def late_reply(*args, **kwargs):
        event.set()
        return reply("[NOTIFY: Reminder | Late message]")
    with patch.object(server_manager, "start_planner_server", return_value=True), \
         patch.object(server_manager, "stop_planner_server"), \
         patch.object(server_manager.requests, "post", side_effect=late_reply), \
         patch.object(server_manager, "send_notification") as notify:
        with pytest.raises(PlannerCancelled):
            server_manager.run_planner_chat("Check project status", [], user_profile_context="No defaults.",
                                           cancel_event=event)
    notify.assert_not_called()


def test_stop_after_tool_retains_receipt_and_prevents_synthesis():
    event = threading.Event()
    receipts = []
    def completed_tool(outcome):
        receipts.append(outcome)
        event.set()
    with patch.object(server_manager, "start_planner_server", return_value=True), \
         patch.object(server_manager, "stop_planner_server"), \
         patch.object(server_manager.requests, "post", return_value=reply("[BROWSER_SEARCH: Atlas]")) as model, \
         patch.object(server_manager, "execute_browser_search", return_value="Results"):
        with pytest.raises(PlannerCancelled):
            server_manager.run_planner_chat("Check project status", [], user_profile_context="No defaults.",
                                           cancel_event=event, tool_result_callback=completed_tool)
    assert model.call_count == 1
    assert len(receipts) == 1 and receipts[0].ok


def test_tool_transcript_is_bounded_and_preserves_original_request():
    base = [{"role": "system", "content": "System rules"}, {"role": "user", "content": "Find the Atlas report"}]
    messages = [dict(item) for item in base]
    for number in range(4):
        server_manager.append_planner_tool_result(messages, len(base), "Reading", f"result-{number} " + "x" * 12000)
    assert messages[:2] == base
    assert sum(len(item["content"]) for item in messages[2:]) <= 6000
    assert "result-3" in messages[-1]["content"]
    assert "Excerpt truncated" in messages[-1]["content"]
    assert "result-0" not in str(messages[2:])


def test_failed_synthesis_does_not_reuse_pretool_success_claim():
    receipts = []
    with patch.object(server_manager, "start_planner_server", return_value=True), \
         patch.object(server_manager, "stop_planner_server"), \
         patch.object(server_manager, "execute_browser_search", return_value="Results"), \
         patch.object(server_manager.requests, "post", side_effect=[
             reply("Everything is complete. [BROWSER_SEARCH: atlas]"), RuntimeError("Model disconnected")]):
        answer = server_manager.run_planner_chat("Investigate Atlas", [], learn_personal_context_enabled=False,
                                                 tool_result_callback=receipts.append)
    assert "not confirmed complete" in answer
    assert "Everything is complete" not in answer
    assert len(receipts) == 1
