"""Instant clean webpage markdown reader for OmniVLA.

Uses trafilatura for high-fidelity article and documentation extraction,
allowing the agent to read and summarize web pages in milliseconds without
slow visual browser navigation.
"""

from __future__ import annotations

import logging
import re
from typing import Any
import urllib.parse

logger = logging.getLogger("omnivla.tools.web_reader")

try:
    import trafilatura
except ImportError:
    trafilatura = None


def read_webpage(
    url: str,
    max_chars: int = 4000,
    timeout_sec: float = 8.0,
) -> dict[str, Any]:
    """Fetch and convert webpage content into clean Markdown text.

    Returns a dictionary with 'title', 'url', 'text', 'success'.
    """
    clean_url = url.strip().strip("<>'\"")
    if not clean_url:
        return {"title": "", "url": "", "text": "Empty URL provided.", "success": False}

    # Prepend http if protocol is missing
    if not clean_url.startswith(("http://", "https://")):
        clean_url = "https://" + clean_url

    # Attempt 1: trafilatura high-fidelity extraction
    if trafilatura is not None:
        try:
            downloaded = trafilatura.fetch_url(clean_url)
            if downloaded:
                extracted = trafilatura.extract(
                    downloaded,
                    output_format="markdown",
                    include_links=True,
                    include_images=False,
                    favor_precision=True,
                )
                if extracted and extracted.strip():
                    # Attempt to extract metadata title
                    meta = trafilatura.extract_metadata(downloaded)
                    title = meta.title if meta and meta.title else ""
                    return {
                        "title": title,
                        "url": clean_url,
                        "text": extracted.strip()[:max_chars],
                        "success": True,
                    }
        except Exception as traf_err:
            logger.warning("Trafilatura failed for '%s': %s", clean_url, traf_err)

    # Attempt 2: Fallback via requests and regex text extraction
    try:
        import requests
        resp = requests.get(
            clean_url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
            timeout=timeout_sec,
        )
        if resp.status_code == 200:
            html = resp.text
            # Extract title
            title_m = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
            title = title_m.group(1).strip() if title_m else ""
            # Strip scripts, styles
            clean_html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.IGNORECASE | re.DOTALL)
            # Replace tags with spaces/newlines
            clean_text = re.sub(r"<[^>]+>", " ", clean_html)
            clean_text = re.sub(r"\s+", " ", clean_text).strip()
            if clean_text:
                return {
                    "title": title,
                    "url": clean_url,
                    "text": clean_text[:max_chars],
                    "success": True,
                }
    except Exception as req_err:
        logger.warning("Requests fallback failed for '%s': %s", clean_url, req_err)

    return {
        "title": "",
        "url": clean_url,
        "text": f"Failed to retrieve or parse content from {clean_url}.",
        "success": False,
    }


def format_webpage_summary(page: dict[str, Any]) -> str:
    """Format extracted webpage content into clean XML context for the planner."""
    url = page.get("url", "")
    title = page.get("title", "Webpage")
    text = page.get("text", "")
    success = page.get("success", False)

    if not success:
        return f"<webpage_content url=\"{url}\">\nError: {text}\n</webpage_content>"

    header = f"Title: {title}\n" if title else ""
    return (
        f"<webpage_content url=\"{url}\">\n"
        f"{header}"
        f"{text}\n"
        f"</webpage_content>"
    )


def detect_webpage_read_intent(message: str) -> tuple[bool, str]:
    """Detect if the user is asking to inspect, read, or summarize a specific URL.

    Returns (is_read_intent, url).
    """
    if not message or not isinstance(message, str):
        return False, ""

    text = message.strip()

    # Look for http(s) URL in the message
    url_match = re.search(r"https?://[^\s<>\"'()]+", text)
    if url_match:
        url = url_match.group(0).rstrip(".,;?!")
        lower = text.lower()
        triggers = ["read", "summarize", "what does", "inspect", "check this link", "look at", "tell me about this page"]
        if any(trig in lower for trig in triggers) or len(text.split()) <= 4:
            return True, url

    return False, ""
