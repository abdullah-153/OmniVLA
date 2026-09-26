"""Local file discovery tool for OmniVLA.

Uses Voidtools Everything CLI (es.exe) for sub-15ms file indexing when available,
with high-speed time-bounded local directory walking fallback.
"""

from __future__ import annotations

import fnmatch
import logging
import os
import re
import shutil
import subprocess
import time
from typing import Any

logger = logging.getLogger("omnivla.tools.file_search")


def _within_roots(path: str, roots: list[str]) -> bool:
    resolved = os.path.normcase(os.path.realpath(path))
    for root in roots:
        root = os.path.normcase(os.path.realpath(root))
        try:
            if os.path.commonpath([resolved, root]) == root:
                return True
        except ValueError:
            continue  # Different Windows drives.
    return False


def project_search_roots(context_pack: dict) -> list[str] | None:
    """Use explicit folder relationships for one task-relevant project only."""
    projects = [item for item in context_pack.get("linked_context", [])
                if item.get("kind") == "project"]
    if len(projects) != 1:
        return None
    roots = []
    for link in projects[0].get("links", []):
        path = link.get("entity", "")
        if (link.get("relation") == "stored_in" and link.get("kind") == "folder"
                and link.get("direction") == "outgoing" and os.path.isabs(path)
                and path not in roots):
            roots.append(path)
    return roots or None

_EVERYTHING_PATHS = [
    "es.exe",
    r"C:\Program Files\Everything\es.exe",
    r"C:\Program Files (x86)\Everything\es.exe",
]


def _find_everything_cli() -> str | None:
    """Return path to Everything CLI (es.exe) if available on the system."""
    for candidate in _EVERYTHING_PATHS:
        found = shutil.which(candidate) if not os.path.isabs(candidate) else candidate
        if found and os.path.isfile(found):
            return found
    return None


def find_local_files(
    pattern: str,
    search_roots: list[str] | None = None,
    max_results: int = 15,
    max_depth: int = 5,
    timeout_sec: float = 3.0,
) -> list[dict[str, Any]]:
    """Discover local files matching a glob or substring pattern.

    Attempts to use Voidtools Everything CLI first for instant discovery,
    falling back to fast, bounded local filesystem walking.
    """
    clean_pattern = pattern.strip().strip("'\"")
    if not clean_pattern or max_results <= 0 or timeout_sec <= 0:
        return []
    scoped = search_roots is not None
    roots = [os.path.realpath(root) for root in (search_roots or [])]
    if scoped and not roots:
        return []

    # An explicit location is an exact lookup, never a drive-wide name search.
    if os.path.isabs(clean_pattern) or any(separator in clean_pattern for separator in ("/", "\\")):
        try:
            file_path = os.path.abspath(clean_pattern)
            if (scoped and not _within_roots(file_path, roots)) or not os.path.isfile(file_path):
                return []
            stat = os.stat(file_path)
            return [{"name": os.path.basename(file_path), "path": file_path,
                     "size_kb": round(stat.st_size / 1024, 1),
                     "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime))}]
        except OSError:
            return []

    # 1. Attempt Voidtools Everything CLI (instant sub-15ms search)
    # Global index queries cannot enforce a folder boundary. Scoped searches walk
    # only their supplied roots, including when those roots no longer exist.
    es_path = None if scoped else _find_everything_cli()
    if es_path:
        try:
            cmd = [es_path, "-n", str(max_results), clean_pattern]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
                results = []
                for file_path in lines[:max_results]:
                    if os.path.exists(file_path):
                        try:
                            stat = os.stat(file_path)
                            results.append({
                                "name": os.path.basename(file_path),
                                "path": file_path,
                                "size_kb": round(stat.st_size / 1024, 1),
                                "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)),
                            })
                        except Exception:
                            results.append({"name": os.path.basename(file_path), "path": file_path})
                if results:
                    return results
        except Exception as es_err:
            logger.debug("Everything CLI search failed: %s, falling back to local walking.", es_err)

    # 2. Fast local filesystem walking fallback
    if search_roots is None:
        user_home = os.path.expanduser("~")
        search_roots = [
            os.path.abspath("."),
            os.path.join(user_home, "Desktop"),
            os.path.join(user_home, "Downloads"),
            os.path.join(user_home, "Documents"),
        ]
        roots = [os.path.realpath(root) for root in search_roots]

    # Ensure glob pattern matching: if no wildcard provided, wrap with * for substring search
    glob_pattern = clean_pattern
    if not any(c in clean_pattern for c in ("*", "?", "[", "]")):
        glob_pattern = f"*{clean_pattern}*"

    results: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    start_time = time.monotonic()

    excluded_dirs = {
        ".git", "node_modules", "__pycache__", "venv", ".venv",
        "AppData", "$Recycle.Bin", "System Volume Information"
    }

    for root in roots:
        if not os.path.exists(root):
            continue
        base_depth = root.rstrip(os.path.sep).count(os.path.sep)
        for dirpath, dirnames, filenames in os.walk(root):
            if time.monotonic() - start_time > timeout_sec:
                return results
            if not _within_roots(dirpath, [root]):
                dirnames.clear()
                continue
            # Depth bounding
            current_depth = dirpath.count(os.path.sep) - base_depth
            if current_depth > max_depth:
                dirnames.clear()
                continue
            # Prune slow/irrelevant trees
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".") and d not in excluded_dirs
                and _within_roots(os.path.join(dirpath, d), [root])
            ]
            for f in filenames:
                if time.monotonic() - start_time > timeout_sec:
                    return results
                if fnmatch.fnmatch(f.lower(), glob_pattern.lower()):
                    full_path = os.path.abspath(os.path.join(dirpath, f))
                    identity = os.path.normcase(os.path.realpath(full_path))
                    if identity in seen_paths or not _within_roots(full_path, [root]):
                        continue
                    seen_paths.add(identity)
                    try:
                        stat = os.stat(full_path)
                        results.append({
                            "name": f,
                            "path": full_path,
                            "size_kb": round(stat.st_size / 1024, 1),
                            "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)),
                        })
                    except Exception:
                        results.append({"name": f, "path": full_path})

                    if len(results) >= max_results:
                        return results

    return results


def format_file_results(results: list[dict[str, Any]], pattern: str = "") -> str:
    """Format discovered file paths into a structured XML block for the planner."""
    if not results:
        return f"<local_file_search_results pattern=\"{pattern}\">\nNo matching local files found.\n</local_file_search_results>"

    lines = [f"<local_file_search_results pattern=\"{pattern}\">", f"Found {len(results)} matching file(s):"]
    for idx, item in enumerate(results, 1):
        name = item.get("name", "Unknown")
        path = item.get("path", "")
        size = item.get("size_kb")
        modified = item.get("modified")
        meta = []
        if size is not None:
            if size > 1024:
                meta.append(f"{round(size / 1024, 1)} MB")
            else:
                meta.append(f"{size} KB")
        if modified:
            meta.append(f"modified: {modified}")
        meta_str = f" ({', '.join(meta)})" if meta else ""
        lines.append(f"[{idx}] {name}{meta_str}")
        lines.append(f"    Path: {path}")
    lines.append("</local_file_search_results>")
    return "\n".join(lines)


def detect_file_search_intent(message: str) -> tuple[bool, str]:
    """Detect if the user prompt is an explicit local file discovery request.

    Returns (is_file_search, pattern).
    """
    if not message or not isinstance(message, str):
        return False, ""

    text = message.strip()
    lower = text.lower()

    # Skip destructive commands
    if re.search(r"\b(delete|remove|erase|format|kill)\b", lower):
        return False, ""

    patterns = [
        r"^(?:find|locate|search\s+for|where\s+is|show\s+me)\s+(?:local\s+files?|files?|my\s+file|the\s+file)\s+(?:named\s+|matching\s+|called\s+)?['\"]?([^'\"?]+)['\"]?",
        r"^(?:find|locate|where\s+is)\s+['\"]?([\w\-.*]+\.(?:pdf|txt|docx|xlsx|csv|gguf|py|json|md|zip|png|jpg))['\"]?",
    ]
    for pat in patterns:
        m = re.search(pat, lower)
        if m:
            extracted = m.group(1).strip()
            if len(extracted) >= 2:
                return True, extracted

    return False, ""
