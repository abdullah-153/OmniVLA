"""Bounded keyword search over a task's explicitly remembered project folders."""
from __future__ import annotations

import json
import re
import time

from cogniagent.runtime.cancellation import check_planner_cancelled
from cogniagent.tools.file_search import find_local_files, _within_roots
from cogniagent.tools.local_file_reader import read_local_text_file, READABLE_SUFFIXES

MAX_CANDIDATES = 60
MAX_MATCHES = 3


def search_local_text(query: str, roots: list[str] | None, *, cancel_event=None) -> dict:
    if not roots:
        return {"success": False, "error": "No project folder is selected. Ask which project folder to search."}
    terms = list(dict.fromkeys(re.findall(r"\w+", query.casefold())))
    if not terms or len(terms) > 8:
        return {"success": False, "error": "Use one to eight distinctive search words."}
    check_planner_cancelled(cancel_event)
    deadline = time.monotonic() + 3.0
    candidates = find_local_files("*", search_roots=roots, max_results=MAX_CANDIDATES,
                                  max_depth=5, timeout_sec=1.0, allowed_suffixes=READABLE_SUFFIXES)
    matches, scanned, skipped = [], 0, 0
    for candidate in candidates:
        check_planner_cancelled(cancel_event)
        if time.monotonic() >= deadline or len(matches) >= MAX_MATCHES:
            break
        path = candidate["path"]
        # Recheck containment immediately before reading, including link targets.
        if not _within_roots(path, roots):
            skipped += 1
            continue
        document = read_local_text_file(path)
        if not document.get("success"):
            skipped += 1
            continue
        scanned += 1
        lines = document["text"].splitlines()
        for index, line in enumerate(lines):
            if index % 32 == 0:
                check_planner_cancelled(cancel_event)
                if time.monotonic() >= deadline:
                    break
            # Search a three-line passage so words can straddle wrapped lines.
            passage = "\n".join(lines[index:index + 3])
            occurrences = [re.search(re.escape(term), passage, re.I) for term in terms]
            if all(occurrences):
                first = min(match.start() for match in occurrences)
                last = max(match.end() for match in occurrences)
                if last - first > 260:
                    continue
                start = max(0, first - 40)
                matches.append({"path": path, "line": index + 1 + passage[:start].count("\n"),
                    "excerpt": passage[start:start + 320], "excerpt_truncated": start > 0 or len(passage) > start + 320,
                    "file_excerpt_truncated": document["truncated"], "sha256": document["sha256"]})
                break
    check_planner_cancelled(cancel_event)
    return {"success": True, "query": query, "folders": roots, "matches": matches,
            "files_scanned": scanned, "files_skipped": skipped,
            "coverage": "Bounded search only: up to 60 supported files, depth 5, first 12000 characters per file, and 3 matches. No match does not prove absence."}


def format_text_search(result: dict) -> str:
    return "<local_text_search>\n" + json.dumps(result, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e") + "\n</local_text_search>"
