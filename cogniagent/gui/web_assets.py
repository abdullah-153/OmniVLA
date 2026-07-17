"""Safe file-backed assets for the command-center web application."""

from __future__ import annotations

from pathlib import Path


WEB_ROOT = Path(__file__).with_name("web")

CONTENT_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".webmanifest": "application/manifest+json; charset=utf-8",
}


def get_asset(relative_path: str) -> tuple[bytes, str] | None:
    """Read a whitelisted static asset without allowing path traversal."""
    requested = (WEB_ROOT / relative_path).resolve()
    try:
        requested.relative_to(WEB_ROOT.resolve())
    except ValueError:
        return None

    if not requested.is_file():
        return None

    content_type = CONTENT_TYPES.get(requested.suffix.lower(), "application/octet-stream")
    return requested.read_bytes(), content_type
