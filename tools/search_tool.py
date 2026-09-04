import logging
from langchain.tools import tool

logger: logging.Logger = logging.getLogger(__name__)


@tool
def web_search(query: str) -> str:
    """Search the web using DuckDuckGo. Falls back to knowledge if rate-limited.

    Args:
        query: The search query string.

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
        return result
    except Exception as e:
        logger.warning(f"Search failed: {e}")
        return (
            "Web search is temporarily unavailable (rate-limited). "
            "I will answer from my training knowledge instead. "
            f"Your query was: {query}"
        )
