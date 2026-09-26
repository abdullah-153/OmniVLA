from unittest.mock import MagicMock, patch

from cogniagent.tools.file_search import find_local_files, project_search_roots
from tests.test_tool_gateway import make_gateway
from tests.test_planner_tool_sequence import reply
from cogniagent.gui import server_manager


def pack(folder):
    return {"linked_context": [{"kind": "project", "entity": "Atlas", "links": [
        {"relation": "stored_in", "kind": "folder", "direction": "outgoing", "entity": str(folder)}]}]}


def test_scoped_search_skips_global_index_and_outside_exact_paths(tmp_path):
    project = tmp_path / "Atlas"
    project.mkdir()
    inside = project / "report.md"
    outside = tmp_path / "report.md"
    inside.write_text("Atlas")
    outside.write_text("Other project")
    with patch("cogniagent.tools.file_search._find_everything_cli") as index:
        assert [item["path"] for item in find_local_files("report", [str(project)])] == [str(inside)]
        assert find_local_files(str(outside), [str(project)]) == []
        assert find_local_files("report", []) == []
        assert find_local_files("report", [str(tmp_path / "missing")]) == []
        index.assert_not_called()


def test_project_scope_requires_single_project_and_absolute_folder(tmp_path):
    context = pack(tmp_path)
    assert project_search_roots(context) == [str(tmp_path)]
    context["linked_context"].append({"kind": "project", "entity": "Other"})
    assert project_search_roots(context) is None
    assert project_search_roots(pack("relative-folder")) is None
    assert project_search_roots({}) is None


def test_gateway_reports_scope_and_explicit_path_overrides_default(tmp_path):
    gateway, callbacks = make_gateway()
    gateway.file_search_roots = [str(tmp_path)]
    result = gateway.run("FIND_FILES", {"pattern": "report.md"})
    callbacks["find_files"].assert_called_once_with("report.md", search_roots=[str(tmp_path)])
    assert "Search limited to remembered project folders" in result.content
    path = str(tmp_path / "other" / "report.md")
    gateway.run("FIND_FILES", {"pattern": path})
    callbacks["find_files"].assert_called_with(path)


def test_planner_uses_relevant_project_folder(tmp_path):
    profile = MagicMock()
    profile.get_planner_context.return_value = "Atlas project context"
    profile.build_context_pack.return_value = pack(tmp_path)
    receipts = []
    with patch("cogniagent.memory.user_profile.get_user_profile", return_value=profile), \
         patch.object(server_manager, "start_planner_server", return_value=True), \
         patch.object(server_manager, "stop_planner_server"), \
         patch.object(server_manager, "find_local_files", return_value=[]) as search, \
         patch.object(server_manager.requests, "post", side_effect=[reply("[FIND_FILES: report.md]"), reply("No report found in Atlas folder.")]):
        server_manager.run_planner_chat("Check Atlas status", [], learn_personal_context_enabled=False,
                                       tool_result_callback=receipts.append)
    profile.build_context_pack.assert_called_once_with("Check Atlas status")
    search.assert_called_once_with("report.md", search_roots=[str(tmp_path)])
    assert "remembered project folders" in receipts[0].content
