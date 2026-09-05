import logging
import re
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse
from langchain.tools import tool

from services.context import get_current_user_id
from services.limits import MAX_QUERY_CHARS, MAX_SEARCH_CHARS
from services.ratelimit import get_rate_limiter

logger: logging.Logger = logging.getLogger(__name__)

MAX_SEARCH_RESULTS: int = 5

_NEWS_HINTS = (
    "news", "latest", "breaking", "today", "election", "match",
    "score", "stock market", "weather",
)


def _domain_of(url: str) -> str:
    """Extract the registrable-looking host from a URL, "" when unparseable."""
    try:
        return urlparse(url).netloc.lower() or "unknown source"
    except Exception:
        return "unknown source"


def _to_sources(raw_items: List[Any]) -> List[Dict[str, str]]:
    """Normalize provider result dicts to source records. Never invents data."""
    sources: List[Dict[str, str]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        url = str(item.get("href", "") or item.get("url", "")).strip()
        snippet = str(item.get("body", "") or item.get("snippet", "")).strip()
        if not title and not url:
            continue
        sources.append({
            "title": title or url,
            "url": url,
            "snippet": snippet,
            "date": str(item.get("date", "") or "").strip(),
            "domain": _domain_of(url),
        })
    return sources


def _format_sources(query: str, sources: List[Dict[str, str]]) -> str:
    """Render sources as numbered, model-readable text with markers."""
    lines: List[str] = [f'Results for "{query}":']
    for i, s in enumerate(sources, start=1):
        if s["domain"] and s["domain"] != "unknown source":
            lines.append(f"[{i}] {s['title']} — {s['domain']}")
        else:
            lines.append(f"[{i}] {s['title']}")
        if s["url"]:
            lines.append(f"URL: {s['url']}")
        if s["date"]:
            lines.append(f"Date: {s['date']}")
        if s["snippet"]:
            lines.append(f"Snippet: {s['snippet']}")
    return "\n".join(lines)


def search_sources(query: str, max_results: int = MAX_SEARCH_RESULTS) -> Tuple[str, List[Dict[str, str]]]:
    """Run a structured web search.

    Returns (formatted_text, sources). Raises on provider failure so the
    caller can emit an explicit structured failure state.
    """
    query = str(query or "")[:MAX_QUERY_CHARS]
    if not query.strip():
        raise ValueError("empty query")
    try:
        from duckduckgo_search import DDGS
    except Exception as e:
        raise RuntimeError(f"search backend unavailable: {e}") from e

    lowered = query.lower()
    raw: List[Any] = []
    try:
        with DDGS() as ddgs:
            if any(h in lowered for h in _NEWS_HINTS):
                try:
                    raw = list(ddgs.news(query, max_results=max_results) or [])
                except Exception:
                    raw = []
            if not raw:
                raw = list(ddgs.text(query, max_results=max_results) or [])
    except Exception as e:
        raise RuntimeError(f"search provider error: {e}") from e

    sources = _to_sources(raw)[:max_results]
    if not sources:
        return "", []
    return _format_sources(query, sources), sources


def extract_cited_sources(text: str) -> List[Dict[str, str]]:
    """Parse [n]/URL blocks back out of formatted search output.

    Only returns sources actually present in the text — nothing invented.
    """
    found: List[Dict[str, str]] = []
    blocks = re.split(r"(?m)^\[(\d+)\]\s+", text)
    # blocks[0] is preamble; then alternating (number, body) pairs.
    it = iter(blocks[1:])
    for number, body in zip(it, it):
        url_match = re.search(r"(?m)^URL:\s*(\S+)", body)
        title_line = body.strip().splitlines()[0] if body.strip() else ""
        title = re.sub(r"\s+—\s+\S+\s*$", "", title_line).strip()
        url = url_match.group(1).strip() if url_match else ""
        if not title and not url:
            continue
        found.append({
            "n": number,
            "title": title or url,
            "url": url,
            "domain": _domain_of(url),
        })
    return found


@tool
def web_search(query: str) -> str:
    """Search the web using DuckDuckGo for current information.

    Use ONLY when the user asks about events after 2024, "latest"/"recent"/
    "current" news or data, verifying an unsure factual claim, or specific
    real-world entities (companies, people, laws). Do NOT use for general
    knowledge, definitions, creative writing, or opinions.

    Args:
        query: Specific search query (5-10 words). Be precise.

    Returns:
        Numbered sources with titles, URLs, and snippets, or a structured
        failure marker (never silent).
    """
    query = str(query or "")[:MAX_QUERY_CHARS]
    if not query.strip():
        return "STATUS=INVALID tool=web_search: empty query."
    user_id = get_current_user_id()
    if user_id:
        verdict = get_rate_limiter().check(user_id, "search")
        if not verdict.allowed:
            return (
                "STATUS=DENIED tool=web_search: search rate limit exceeded, "
                f"retry in {verdict.retry_after:.0f}s."
            )
    try:
        formatted, _sources = search_sources(query)
        if not formatted:
            return "STATUS=EMPTY tool=web_search: no results found. Try rephrasing with more specific keywords."
        if len(formatted) > MAX_SEARCH_CHARS:
            formatted = formatted[:MAX_SEARCH_CHARS] + "\n[Note: results truncated.]"
        return formatted
    except Exception as e:
        logger.warning(f"Search failed: {e}")
        return (
            "STATUS=DEGRADED tool=web_search: web search failed "
            f"({str(e)[:150]}). This answer is NOT verified by the web; "
            "I will answer from my training knowledge instead. "
            f"Your query was: {query}"
        )
