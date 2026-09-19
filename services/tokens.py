"""Token counting for context budgets.

Uses tiktoken (cl100k_base) when importable, otherwise a documented
characters/4 approximation. The encoder instance is cached globally —
it holds no user data, so sharing it is safe.
"""

import functools
import logging
from typing import Optional

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def _encoder() -> Optional[object]:
    """Return a tiktoken encoder or None when unavailable."""
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


@functools.lru_cache(maxsize=1024)
def _count_tokens_small(text: str) -> int:
    encoder = _encoder()
    if encoder is not None:
        try:
            return len(encoder.encode(text))
        except Exception:
            logger.debug("tiktoken encode failed; using approximation", exc_info=True)
    return max(1, len(text) // 4)


def count_tokens(text: str) -> int:
    """Approximate token count for budgeting (never exact billing)."""
    if not text:
        return 0
    # Don't cache huge documents verbatim (MBs x1024 RAM). Only small
    # inputs go through the LRU; large ones are computed directly.
    if len(text) > 8000:
        encoder = _encoder()
        if encoder is not None:
            try:
                return len(encoder.encode(text))
            except Exception:
                logger.debug("tiktoken encode failed; using approximation", exc_info=True)
        # Char fallback overcounts CJK (1 char ~= 1+ tokens); use 3 for safety.
        try:
            cjk = sum(1 for ch in text[:8000] if ord(ch) > 0x2E7F)
            if cjk > len(text[:8000]) // 2:
                return max(1, len(text) // 3)
        except Exception:
            logger.debug("cjk heuristic failed", exc_info=True)
        return max(1, len(text) // 4)
    return _count_tokens_small(text)


def prewarm_tokenizer() -> None:
    """Pre-warm tiktoken encoder and token counting cache."""
    _encoder()
    # Prime the cache with common strings
    count_tokens("Hello, world!")
    count_tokens("")  # empty string
    count_tokens("a" * 1000)  # long text


def truncate_tokens(text: str, max_tokens: int, marker: str = "\n[Note: truncated to fit context.]") -> str:
    """Hard-truncate text to a token budget, keeping the head."""
    if max_tokens <= 0:
        return ""
    if count_tokens(text) <= max_tokens:
        return text
    marker_tokens = count_tokens(marker)
    budget = max(1, max_tokens - marker_tokens)
    encoder = _encoder()
    if encoder is not None:
        try:
            clipped = encoder.decode(encoder.encode(text)[:budget])
            return clipped + marker
        except Exception:
            logger.debug("tiktoken clip failed; using char approximation", exc_info=True)
    approx_chars = budget * 4
    return text[:approx_chars] + marker
