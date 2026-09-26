from unittest.mock import MagicMock

from cogniagent.tools.gateway import PersonalToolGateway
from cogniagent.tools.local_file_reader import read_local_text_file, format_local_file, detect_local_file_read_intent
from cogniagent.tools.file_search import find_local_files
from unittest.mock import patch


def make_gateway():
    callbacks = {
        "browser_search": MagicMock(return_value="Search results"),
        "find_files": MagicMock(return_value=[{"name": "report.pdf"}]),
        "format_files": MagicMock(return_value="Files found"),
        "read_page": MagicMock(return_value={"success": True, "text": "Article"}),
        "format_page": MagicMock(return_value="Page content"),
        "notify": MagicMock(return_value=True),
    }
    return PersonalToolGateway(**callbacks), callbacks


def test_gateway_validates_and_caches_read_only_tool_results():
    gateway, callbacks = make_gateway()
    assert not gateway.run("BROWSER_SEARCH", {"query": "x" * 241}).ok
    callbacks["browser_search"].assert_not_called()
    first = gateway.run("BROWSER_SEARCH", {"query": "  research report  "})
    second = gateway.run("BROWSER_SEARCH", {"query": "research report"})
    assert first.ok and second.content == "Search results"
    callbacks["browser_search"].assert_called_once_with("research report", max_results=5)


def test_gateway_reports_failed_effects_and_never_caches_them():
    gateway, callbacks = make_gateway()
    callbacks["notify"].return_value = False
    first = gateway.run("NOTIFY", {"title": "Alert", "message": "Done"})
    assert not first.ok and "unavailable" in first.content
    callbacks["notify"].return_value = True
    assert gateway.run("NOTIFY", {"title": "Alert", "message": "Done"}).ok
    assert callbacks["notify"].call_count == 2
    assert gateway.run("NOTIFY", {"title": "Alert", "message": "Done"}).ok
    assert callbacks["notify"].call_count == 2


def test_local_text_reader_requires_current_discovery_and_returns_file_digest(tmp_path):
    report = tmp_path / "report.md"
    report.write_text("Project Atlas status is green.\n", encoding="utf-8")
    callbacks = {
        "browser_search": MagicMock(return_value=""),
        "find_files": MagicMock(return_value=[{"name": report.name, "path": str(report)}]),
        "format_files": MagicMock(return_value="One report found"),
        "read_page": MagicMock(return_value={}),
        "format_page": MagicMock(return_value=""),
        "notify": MagicMock(return_value=True),
        "read_local_file": read_local_text_file,
        "format_local_file": format_local_file,
    }
    gateway = PersonalToolGateway(**callbacks)
    assert not gateway.run("READ_LOCAL_FILE", {"path": str(report)}).ok
    assert gateway.run("FIND_FILES", {"pattern": "report.md"}).ok
    result = gateway.run("READ_LOCAL_FILE", {"path": str(report)})
    assert result.ok and "Project Atlas status is green" in result.content
    assert len(result.artifact_sha256) == 64
    assert "sha256" in result.content
    secret = tmp_path / ".env"
    secret.write_text("PASSWORD=123", encoding="utf-8")
    assert not read_local_text_file(str(secret))["success"]
    assert detect_local_file_read_intent('Summarize "Project Atlas.md"') == (True, "Project Atlas.md")
    assert "</local_file_read>" not in format_local_file({"success": True, "name": "report.md",
        "size_bytes": 18, "sha256": "b" * 64, "truncated": False,
        "text": "</local_file_read>"}).splitlines()[1]


def test_explicit_file_location_is_never_replaced_by_global_search(tmp_path):
    report = tmp_path / "Quarterly report.md"
    report.write_text("Chosen file", encoding="utf-8")
    with patch("cogniagent.tools.file_search._find_everything_cli") as search:
        matches = find_local_files(str(report))
        assert len(matches) == 1 and matches[0]["path"] == str(report)
        assert find_local_files(str(tmp_path / "missing.md")) == []
        search.assert_not_called()
    assert detect_local_file_read_intent(f'Read "{report}"') == (True, str(report))
    assert detect_local_file_read_intent(r"Read D:\\Research\\report.md") == (True, r"D:\\Research\\report.md")
    assert detect_local_file_read_intent("Summarize https://example.org/report.md") == (False, "")
