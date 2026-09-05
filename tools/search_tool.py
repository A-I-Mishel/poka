import logging
from langchain.tools import tool

from services.limits import MAX_SEARCH_CHARS

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
            "Web search is temporarily unavailable (rate-limited). "
            "I will answer from my training knowledge instead. "
            f"Your query was: {query}"
        )
