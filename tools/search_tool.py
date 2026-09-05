import logging
from langchain.tools import tool

from services.context import get_current_user_id
from services.limits import MAX_QUERY_CHARS, MAX_SEARCH_CHARS
from services.ratelimit import get_rate_limiter

logger: logging.Logger = logging.getLogger(__name__)


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
        Search results text, or a graceful fallback message.
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
        from langchain_community.tools import DuckDuckGoSearchRun

        search = DuckDuckGoSearchRun()
        try:
            result: str = search.invoke(query)  # type: ignore[assignment]
        except Exception:
            result = search.run(query)
        if not result or result.strip() == "":
            return "No search results found. Try rephrasing your query."
        if len(result) > MAX_SEARCH_CHARS:
            result = result[:MAX_SEARCH_CHARS] + "\n[Note: results truncated.]"
        return result
    except Exception as e:
        logger.warning(f"Search failed: {e}")
        return (
            "STATUS=DEGRADED tool=web_search: web search is temporarily "
            "unavailable (rate-limited). "
            "I will answer from my training knowledge instead. "
            f"Your query was: {query}"
        )
