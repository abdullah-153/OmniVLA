"""Bounded, read-only access to text files discovered for the current task."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

READABLE_SUFFIXES = {".txt", ".md", ".csv", ".json", ".py", ".log"}
MAX_FILE_BYTES = 256_000
MAX_EXCERPT_CHARS = 12_000
_SENSITIVE_NAME = re.compile(r"(?i)(?:^\.|password|credential|secret|token|private.?key|\.env)")


def read_local_text_file(path: str) -> dict:
    """Read a supported small text file and return verifiable source metadata."""
    try:
        target = Path(path).resolve(strict=True)
        if not target.is_file() or target.suffix.lower() not in READABLE_SUFFIXES:
            raise ValueError("Unsupported local file type.")
        if any(_SENSITIVE_NAME.search(part) for part in target.parts):
            raise ValueError("Protected local file name.")
        before = target.stat()
        if before.st_size > MAX_FILE_BYTES:
            raise ValueError("Local file is too large to read safely.")
        with target.open("rb") as handle:
            raw = handle.read(MAX_FILE_BYTES + 1)
        after = target.stat()
        if len(raw) > MAX_FILE_BYTES or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("Local file changed while being read.")
        text = raw.decode("utf-8-sig")
        return {"success": True, "name": target.name, "text": text[:MAX_EXCERPT_CHARS],
                "truncated": len(text) > MAX_EXCERPT_CHARS, "size_bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest()}
    except (OSError, UnicodeError, ValueError) as error:
        return {"success": False, "error": str(error)[:160]}


def format_local_file(result: dict) -> str:
    if result.get("success") is not True:
        return "<local_file_read>\nFile could not be read.\n</local_file_read>"
    # Escaped angle brackets keep file text from spoofing the wrapper.
    import json
    return "<local_file_read>\n" + json.dumps({
        "name": result["name"], "size_bytes": result["size_bytes"],
        "sha256": result["sha256"], "truncated": result["truncated"],
        "text": result["text"],
    }, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e") + "\n</local_file_read>"


def detect_local_file_read_intent(message: str) -> tuple[bool, str]:
    """Recognize an explicit request to inspect one named, supported text file."""
    if not isinstance(message, str) or not re.search(r"(?i)\b(read|summari[sz]e|inspect|review|analy[sz]e)\b", message):
        return False, ""
    quoted = re.search(r"(?i)[\"']([^\"']{1,100}\.(?:txt|md|csv|json|py|log))[\"']", message)
    unquoted = re.search(r"(?i)(?<![\w.])([\w.-]{1,100}\.(?:txt|md|csv|json|py|log))\b", message)
    candidate = (quoted or unquoted)
    return (True, candidate.group(1).strip()) if candidate else (False, "")
