"""Browser search engine tool for OmniVLA.

Enables the planner to conduct real-time web research using DuckDuckGo (ddgs),
answering informational, research, and lookup queries directly in chat without
triggering desktop vision-language-action (Holo VLA) execution.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger("omnivla.tools.browser_search")

# Exa search SDK
try:
    from exa_py import Exa
except ImportError:
    Exa = None

# DuckDuckGo fallback
try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        DDGS = None

# Regex pattern to identify explicit search / lookup intent
_SEARCH_PREFIXES = [
    r"^search\s+(?:the\s+web\s+for|for|about|google|online)\s+",
    r"^look\s+up\s+",
    r"^browse\s+(?:the\s+web\s+for|for)\s+",
    r"^google\s+",
    r"^find\s+(?:online|on\s+the\s+web|information\s+about|news\s+about)\s+",
    r"^what\s+(?:is|are)\s+(?:the\s+latest|the\s+current|the)\s+",
    r"^who\s+(?:is|was|are)\s+",
    r"^how\s+to\s+",
    r"^weather\s+(?:in|for|forecast)\s+",
]

_DESKTOP_GUI_ACTIONS = [
    r"\bopen\s+(?:edge|chrome|browser|outlook|notepad|app|file|folder|settings|spotify|word|excel)\b",
    r"\bclick\s+(?:on|the|button|link|icon)\b",
    r"\btype\s+(?:in|into|text)\b",
    r"\bclose\s+(?:window|app|tab)\b",
    r"\bdownload\s+(?:to|file)\b",
    r"\bdelete\s+(?:file|folder|email)\b",
    r"\bmove\s+(?:file|folder)\b",
    r"\borganize\s+(?:downloads|desktop|files)\b",
    r"\bmanually\b",
    r"\bfrom\s+my\s+(?:system|computer|pc|machine|desktop)\b",
    r"\bon\s+my\s+(?:system|computer|pc|machine|desktop)\b",
    r"\bin\s+(?:edge|chrome|browser|firefox)\b",
    r"\busing\s+(?:edge|chrome|browser|firefox)\b",
]


def detect_search_intent(message: str) -> tuple[bool, str]:
    """Detect if a user prompt is an informational web search query.

    Returns (is_search, cleaned_query).
    """
    if not message or not isinstance(message, str):
        return False, ""

    text = message.strip()
    lower = text.lower()

    # If prompt explicitly demands local desktop GUI actions, don't hijack as pure search
    for desktop_pat in _DESKTOP_GUI_ACTIONS:
        if re.search(desktop_pat, lower):
            return False, ""

    # Check for direct search prefixes
    for prefix in _SEARCH_PREFIXES:
        match = re.match(prefix, lower)
        if match:
            query = text[match.end():].strip()
            # Clean trailing punctuation
            query = re.sub(r"[?!.]+$", "", query).strip()
            if len(query) >= 2:
                return True, query

    # Check for question queries containing search indicators
    search_keywords = [
        "latest release",
        "latest version",
        "current price",
        "stock price",
        "weather in",
        "news today",
        "documentation for",
        "what happened with",
    ]
    if any(kw in lower for kw in search_keywords):
        # Extract query by removing leading conversational filler
        cleaned = re.sub(r"^(?:please\s+|can\s+you\s+|could\s+you\s+|tell\s+me\s+)", "", text, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"[?!.]+$", "", cleaned).strip()
        if len(cleaned) >= 3:
            return True, cleaned

    return False, ""


def _search_ddg_html(query: str, max_results: int = 5, timeout: float = 6.0) -> list[dict[str, Any]]:
    """Query DuckDuckGo's static HTML search interface directly.

    This avoids the Cloudflare bot challenge on DuckDuckGo's internal JSON API
    (which causes HTTP 403 Forbidden on DDGS / news.js), providing reliable,
    unblocked search results across all general topics.
    """
    import urllib.parse
    import urllib.request

    results: list[dict[str, Any]] = []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    data = urllib.parse.urlencode({"q": query, "b": ""}).encode("utf-8")
    req = urllib.request.Request(
        "https://html.duckduckgo.com/html/",
        data=data,
        headers=headers,
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as fetch_err:
        logger.debug("Direct DDG HTML fetch error for '%s': %s", query, fetch_err)
        return []

    # Parse using lxml if available
    try:
        from lxml.html import document_fromstring
        doc = document_fromstring(html)
        items = doc.xpath('//div[contains(@class, "result") and contains(@class, "results_links")]')
        for el in items:
            title = "".join(el.xpath(".//h2//a//text()")).strip()
            raw_href = el.xpath(".//h2//a/@href")
            snippet = "".join(el.xpath(".//a[contains(@class, 'result__snippet')]//text()")).strip()

            href = raw_href[0] if raw_href else ""
            if "uddg=" in href:
                parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                href = parsed.get("uddg", [href])[0]

            if title and href:
                results.append({
                    "title": title,
                    "href": href,
                    "snippet": snippet[:400],
                })
            if len(results) >= max_results:
                break
    except Exception as parse_err:
        logger.debug("lxml HTML parsing failed: %s; attempting regex fallback", parse_err)

    # Fallback to regex parser if lxml produced no results
    if not results:
        try:
            link_pattern = re.compile(
                r'<a[^>]+class="result__url"[^>]*href="(?P<href>[^"]+)"[^>]*>.*?'
                r'<a[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
                re.DOTALL,
            )
            for m in link_pattern.finditer(html):
                href = m.group("href").strip()
                if "uddg=" in href:
                    parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                    href = parsed.get("uddg", [href])[0]
                snippet = re.sub(r"<[^>]+>", "", m.group("snippet")).strip()
                if href and snippet:
                    results.append({
                        "title": href,
                        "href": href,
                        "snippet": snippet[:400],
                    })
                if len(results) >= max_results:
                    break
        except Exception as reg_err:
            logger.debug("Regex search parsing failed: %s", reg_err)

    return results


def _get_exa_client() -> Any:
    """Retrieve an authenticated Exa client instance."""
    if Exa is None:
        return None
    api_key = os.environ.get("EXA_API_KEY")
    if not api_key:
        try:
            from dotenv import load_dotenv
            load_dotenv()
            api_key = os.environ.get("EXA_API_KEY")
        except Exception:
            pass
    if not api_key:
        api_key = "4aa19e7a-3e04-4ac0-b9e0-443ecbcde56f"
    if api_key:
        try:
            return Exa(api_key=api_key)
        except Exception as err:
            logger.warning("Failed to initialize Exa client: %s", err)
            return None
    return None


def _search_exa(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Query Exa API with token-efficient highlights.

    Uses Exa's auto search type and requests content highlights as per the
    official build-with-exa skill recommendations.
    """
    client = _get_exa_client()
    if client is None:
        return []

    results: list[dict[str, Any]] = []
    try:
        response = client.search(
            query,
            type="auto",
            num_results=max_results,
            contents={"highlights": True},
        )
        for item in getattr(response, "results", []):
            title = getattr(item, "title", "") or "Untitled"
            href = getattr(item, "url", "")
            highlights = getattr(item, "highlights", [])
            if highlights and isinstance(highlights, list):
                snippet = " ".join(str(h) for h in highlights).strip()
            else:
                snippet = getattr(item, "text", "") or ""
            if title and href:
                results.append({
                    "title": title.strip(),
                    "href": href.strip(),
                    "snippet": snippet[:600].strip(),
                })
            if len(results) >= max_results:
                break
    except Exception as exc:
        logger.warning("Exa search error for '%s': %s", query, exc)
        return []
    return results


def _get_monid_api_key() -> str:
    """Retrieve Monid API key from environment or default."""
    api_key = os.environ.get("MONID_API_KEY", "").strip()
    if not api_key:
        try:
            from dotenv import load_dotenv
            load_dotenv()
            api_key = os.environ.get("MONID_API_KEY", "").strip()
        except Exception:
            pass
    if not api_key:
        api_key = "monid_live_RqWc1jL2EboTCQdFQVReo6zH"
    return api_key


def _search_monid(query: str, max_results: int = 5, timeout: float = 10.0) -> list[dict[str, Any]]:
    """Query Monid AI Search endpoint (tinyfish /search).

    Uses Monid's 100% free TinyFish search endpoint ($0.00 cost) to perform
    real-time internet search without deducting user credits.
    """
    import json
    import urllib.request

    api_key = _get_monid_api_key()
    if not api_key:
        return []

    req_body = {
        "provider": "tinyfish",
        "endpoint": "/search",
        "input": {
            "queryParams": {
                "query": query,
            }
        },
    }

    req = urllib.request.Request(
        "https://api.monid.ai/v1/run",
        data=json.dumps(req_body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "OmniVLA-Personal-Agent/1.0",
        },
    )

    results: list[dict[str, Any]] = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            output_obj = data.get("output", {})
            if isinstance(output_obj, dict):
                items = output_obj.get("results") or output_obj.get("data", {}).get("results", [])
            else:
                items = []
            for item in items:
                title = str(item.get("title", "")).strip() or "Untitled"
                href = str(item.get("url") or item.get("href") or "").strip()
                snippet = str(item.get("snippet") or item.get("highlight") or "").strip()
                if title and href:
                    results.append({
                        "title": title,
                        "href": href,
                        "snippet": snippet[:600],
                    })
                if len(results) >= max_results:
                    break
    except Exception as exc:
        logger.warning("Monid search error for '%s': %s", query, exc)
        return []

    return results


def search_web(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Execute a general-purpose web search.

    Queries Monid AI (tinyfish/search, 100% free) as the primary engine.
    Seamlessly falls back to direct Exa API, then DuckDuckGo (DDGS / direct HTML)
    if Monid is unavailable or encounters errors.
    """
    clean_query = query.strip()
    if not clean_query:
        return []

    # Clean conversational wrappers to avoid degraded search relevance
    search_term = re.sub(
        r"^(?:what\s+(?:is|are)\s+(?:the\s+)?|tell\s+me\s+(?:about\s+)?(?:the\s+)?|can\s+you\s+(?:tell\s+me\s+)?(?:about\s+)?|please\s+|search\s+(?:for\s+)?|find\s+)",
        "",
        clean_query,
        flags=re.IGNORECASE,
    ).strip()
    search_term = search_term if len(search_term) >= 2 else clean_query

    # 1. Primary: Monid Search Engine
    results = _search_monid(search_term, max_results=max_results)
    if results:
        return results

    # 2. Secondary fallback: Direct Exa Search API
    results = _search_exa(search_term, max_results=max_results)
    if results:
        return results

    # 2. Secondary fallback: DDGS library if available
    if DDGS is not None:
        try:
            with DDGS() as ddgs:
                raw_results = list(ddgs.text(search_term, max_results=max_results))
                for item in raw_results:
                    if isinstance(item, dict):
                        title = str(item.get("title", "")).strip()
                        href = str(item.get("href", "")).strip()
                        snippet = str(item.get("body", "")).strip()
                        if title and href:
                            results.append({
                                "title": title,
                                "href": href,
                                "snippet": snippet[:400],
                            })
                    if len(results) >= max_results:
                        break
        except Exception as exc:
            logger.warning("DDGS text search failed for '%s': %s. Falling back to direct HTML search.", search_term, exc)

    # 3. Tertiary fallback: Direct HTML gateway if DDGS produced no results
    if not results:
        try:
            results = _search_ddg_html(search_term, max_results=max_results)
        except Exception as html_err:
            logger.warning("Direct DDG HTML search failed for '%s': %s", search_term, html_err)

    return results



def format_search_results(results: list[dict[str, Any]], query: str = "") -> str:
    """Format search results into a clean, token-efficient XML block for the planner."""
    if not results:
        return f"<browser_search_results query=\"{query}\">\nNo relevant web results found.\n</browser_search_results>"

    lines = [f"<browser_search_results query=\"{query}\">"]
    for idx, item in enumerate(results, 1):
        title = item.get("title", "Untitled")
        href = item.get("href", "")
        snippet = item.get("snippet", "")
        lines.append(f"[{idx}] {title}")
        if href:
            lines.append(f"    URL: {href}")
        if snippet:
            lines.append(f"    Summary: {snippet}")
    lines.append("</browser_search_results>")
    return "\n".join(lines)


def execute_browser_search(query: str, max_results: int = 5) -> str:
    """Convenience helper to search the web and return formatted results."""
    results = search_web(query, max_results=max_results)
    return format_search_results(results, query=query)
