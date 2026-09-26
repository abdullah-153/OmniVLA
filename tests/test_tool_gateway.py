from unittest.mock import MagicMock

from cogniagent.tools.gateway import PersonalToolGateway


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
