"""Bounded, typed dispatch for planner-side personal tools."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import time
from cogniagent.tools.file_search import simplify_scoped_pattern
from typing import Callable, Any


@dataclass(frozen=True)
class ToolResult:
    name: str
    ok: bool
    content: str
    elapsed_ms: int
    artifact_sha256: str = ""


class PersonalToolGateway:
    """Keep tool validation, formatting, and outcomes in one place.

    Callbacks are injected so the gateway can use the configured providers and
    remain testable without a browser, filesystem scan, or native notification.
    """

    _fields = {
        "BROWSER_SEARCH": {"query": 240},
        "FIND_FILES": {"pattern": 240},
        "READ_WEBPAGE": {"url": 2048},
        "READ_LOCAL_FILE": {"path": 2048},
        "NOTIFY": {"title": 120, "message": 500},
    }

    def __init__(self, *, browser_search: Callable, find_files: Callable,
                 format_files: Callable, read_page: Callable, format_page: Callable,
                 notify: Callable, read_local_file: Callable | None = None,
                 format_local_file: Callable | None = None,
                 file_search_roots: list[str] | None = None):
        self.browser_search = browser_search
        self.find_files = find_files
        self.format_files = format_files
        self.read_page = read_page
        self.format_page = format_page
        self.notify = notify
        self.read_local_file = read_local_file
        self.format_local_file = format_local_file
        self.file_search_roots = file_search_roots
        self._discovered_paths: set[str] = set()
        self.file_matches: list[dict[str, Any]] = []
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
        if name == "READ_LOCAL_FILE":
            try:
                resolved = str(Path(values["path"]).resolve(strict=True)).casefold()
            except OSError:
                return ToolResult(name, False, "File is not available.", 0)
            if resolved not in self._discovered_paths or self.read_local_file is None or self.format_local_file is None:
                return ToolResult(name, False, "Read a file discovered during this request.", 0)
        if name not in {"NOTIFY", "READ_LOCAL_FILE"} and cache_key in self._cache:
            return self._cache[cache_key]
        if name == "NOTIFY" and cache_key in self._delivered:
            return ToolResult(name, True, "<notification_event>\nAlready delivered during this request.\n</notification_event>", 0)
        try:
            artifact_sha256 = ""
            if name == "BROWSER_SEARCH":
                content = self.browser_search(values["query"], max_results=5)
                ok = True
            elif name == "FIND_FILES":
                pattern = values["pattern"]
                # Remembered folders are defaults; explicit locations stay exact.
                explicit = os.path.isabs(pattern) or "/" in pattern or "\\" in pattern
                roots = None if explicit else self.file_search_roots
                matches = (self.find_files(pattern) if roots is None else
                           self.find_files(pattern, search_roots=roots))
                retry_pattern = simplify_scoped_pattern(pattern, roots) if roots and not matches else None
                if retry_pattern:
                    matches = self.find_files(retry_pattern, search_roots=roots)
                self.file_matches = matches[:15]
                for item in matches[:15]:
                    try:
                        self._discovered_paths.add(str(Path(item["path"]).resolve(strict=True)).casefold())
                    except (KeyError, OSError, TypeError, ValueError):
                        continue
                content = self.format_files(matches, pattern=values["pattern"])
                if retry_pattern:
                    content = ("Original filename query had no matches. Retried within the same folder using "
                               + json.dumps(retry_pattern) + ".\n" + content)
                if roots is not None:
                    content = ("Search limited to remembered project folders: " + json.dumps(roots)
                               + ". Missing folders do not trigger a broader search.\n" + content)
                ok = True
            elif name == "READ_WEBPAGE":
                page = self.read_page(values["url"])
                content = self.format_page(page)
                ok = page.get("success") is True
            elif name == "READ_LOCAL_FILE":
                file_result = self.read_local_file(values["path"])
                content = self.format_local_file(file_result)
                ok = file_result.get("success") is True
                if ok:
                    artifact_sha256 = str(file_result.get("sha256", ""))[:64]
            else:
                ok = self.notify(values["title"], values["message"]) is True
                content = (f"<notification_event>\nSent Windows desktop notification '{values['title']}'.\n</notification_event>"
                           if ok else "<notification_event>\nNotification was unavailable.\n</notification_event>")
        except Exception:
            ok = False
            content = f"{name} failed."
        result = ToolResult(name, ok, str(content)[:16000] if name == "READ_LOCAL_FILE" else str(content)[:8000],
                            int((time.monotonic() - started) * 1000), artifact_sha256)
        if name not in {"NOTIFY", "READ_LOCAL_FILE"} and ok:
            self._cache[cache_key] = result
        if name == "NOTIFY" and ok:
            self._delivered.add(cache_key)
        return result
