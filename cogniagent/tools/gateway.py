"""Bounded, typed dispatch for planner-side personal tools."""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable, Any


@dataclass(frozen=True)
class ToolResult:
    name: str
    ok: bool
    content: str
    elapsed_ms: int


class PersonalToolGateway:
    """Keep tool validation, formatting, and outcomes in one place.

    Callbacks are injected so the gateway can use the configured providers and
    remain testable without a browser, filesystem scan, or native notification.
    """

    _fields = {
        "BROWSER_SEARCH": {"query": 240},
        "FIND_FILES": {"pattern": 240},
        "READ_WEBPAGE": {"url": 2048},
        "NOTIFY": {"title": 120, "message": 500},
    }

    def __init__(self, *, browser_search: Callable, find_files: Callable,
                 format_files: Callable, read_page: Callable, format_page: Callable,
                 notify: Callable):
        self.browser_search = browser_search
        self.find_files = find_files
        self.format_files = format_files
        self.read_page = read_page
        self.format_page = format_page
        self.notify = notify
        self._cache: dict[tuple[str, tuple[tuple[str, str], ...]], ToolResult] = {}
        self._delivered: set[tuple[str, tuple[tuple[str, str], ...]]] = set()

    def run(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        started = time.monotonic()
        if name not in self._fields or not isinstance(arguments, dict):
            return ToolResult(str(name)[:40], False, "Unsupported tool request.", 0)
        allowed = self._fields[name]
        values = {}
        for field, limit in allowed.items():
            value = arguments.get(field)
            if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
                return ToolResult(name, False, f"Invalid {field} argument.", 0)
            values[field] = value.strip()
        cache_key = (name, tuple(sorted(values.items())))
        if name != "NOTIFY" and cache_key in self._cache:
            return self._cache[cache_key]
        if name == "NOTIFY" and cache_key in self._delivered:
            return ToolResult(name, True, "<notification_event>\nAlready delivered during this request.\n</notification_event>", 0)
        try:
            if name == "BROWSER_SEARCH":
                content = self.browser_search(values["query"], max_results=5)
                ok = True
            elif name == "FIND_FILES":
                content = self.format_files(self.find_files(values["pattern"]), pattern=values["pattern"])
                ok = True
            elif name == "READ_WEBPAGE":
                page = self.read_page(values["url"])
                content = self.format_page(page)
                ok = page.get("success") is True
            else:
                ok = self.notify(values["title"], values["message"]) is True
                content = (f"<notification_event>\nSent Windows desktop notification '{values['title']}'.\n</notification_event>"
                           if ok else "<notification_event>\nNotification was unavailable.\n</notification_event>")
        except Exception:
            ok = False
            content = f"{name} failed."
        result = ToolResult(name, ok, str(content)[:8000], int((time.monotonic() - started) * 1000))
        if name != "NOTIFY" and ok:
            self._cache[cache_key] = result
        if name == "NOTIFY" and ok:
            self._delivered.add(cache_key)
        return result
