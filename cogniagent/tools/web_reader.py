"""Instant clean webpage markdown reader for OmniVLA.

Uses trafilatura for high-fidelity article and documentation extraction,
allowing the agent to read and summarize web pages in milliseconds without
slow visual browser navigation.
"""

from __future__ import annotations

import logging
import ipaddress
import re
import socket
from typing import Any
import urllib.parse

logger = logging.getLogger("omnivla.tools.web_reader")
MAX_RESPONSE_BYTES = 1_000_000
MAX_REDIRECTS = 3


def _public_destination(url: str) -> bool:
    """Reject local, private, and ambiguous destinations before each request."""
    try:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return False
        if len(url) > 2048 or parsed.port is None and parsed.netloc.endswith(":"):
            return False
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        return bool(addresses) and all(ipaddress.ip_address(item[4][0].split("%", 1)[0]).is_global for item in addresses)
    except (ValueError, OSError):
        return False

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

    if not _public_destination(clean_url):
        return {"title": "", "url": clean_url, "text": "This destination is unavailable to the web reader.", "success": False}

    # One bounded fetch path is shared by trafilatura and the HTML fallback.
    # This prevents the extractor's independent downloader from bypassing the
    # destination policy and timeout.
    try:
        import requests
        current = clean_url
        for _ in range(MAX_REDIRECTS + 1):
            if not _public_destination(current):
                raise ValueError("Redirect target is not public")
            with requests.get(
                current,
                headers={"User-Agent": "OmniVLA-WebReader/1.0", "Accept": "text/html,application/xhtml+xml,text/plain"},
                timeout=(min(3.0, timeout_sec), timeout_sec), stream=True, allow_redirects=False,
            ) as resp:
                if resp.status_code in {301, 302, 303, 307, 308}:
                    location = resp.headers.get("Location", "")
                    if not location:
                        raise ValueError("Redirect has no destination")
                    current = urllib.parse.urljoin(current, location)
                    continue
                if resp.status_code != 200:
                    raise ValueError(f"HTTP {resp.status_code}")
                content_type = resp.headers.get("Content-Type", "text/html").split(";", 1)[0].lower()
                if content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
                    raise ValueError("Unsupported page content type")
                if resp.headers.get("Content-Length", "").isdigit() and int(resp.headers["Content-Length"]) > MAX_RESPONSE_BYTES:
                    raise ValueError("Page exceeds the download limit")
                chunks = []
                size = 0
                for chunk in resp.iter_content(chunk_size=16_384):
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise ValueError("Page exceeds the download limit")
                    chunks.append(chunk)
                html = b"".join(chunks).decode(resp.encoding or "utf-8", errors="replace")
            clean_url = current
            if trafilatura is not None:
                try:
                    extracted = trafilatura.extract(html, output_format="markdown", include_links=True,
                                                    include_images=False, favor_precision=True)
                    if extracted and extracted.strip():
                        meta = trafilatura.extract_metadata(html)
                        return {"title": meta.title if meta and meta.title else "", "url": clean_url,
                                "text": extracted.strip()[:max_chars], "success": True}
                except Exception as traf_err:
                    logger.warning("Page extraction failed for '%s': %s", clean_url, traf_err)
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
            break
        else:
            raise ValueError("Too many redirects")
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
