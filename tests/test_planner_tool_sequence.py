from unittest.mock import MagicMock, patch

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
