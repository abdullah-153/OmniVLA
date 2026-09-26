from unittest.mock import MagicMock, patch
import pytest

from cogniagent.gui import server_manager


def reply(text):
    response = MagicMock(status_code=200)
    response.json.return_value = {"choices": [{"message": {"content": text}}]}
    return response


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
