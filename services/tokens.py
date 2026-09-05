"""Token counting for context budgets.

Uses tiktoken (cl100k_base) when importable, otherwise a documented
characters/4 approximation. The encoder instance is cached globally —
it holds no user data, so sharing it is safe.
"""

import functools
from typing import Optional


@functools.lru_cache(maxsize=1)
def _encoder() -> Optional[object]:
    """Return a tiktoken encoder or None when unavailable."""
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


def count_tokens(text: str) -> int:
    """Approximate token count for budgeting (never exact billing)."""
    if not text:
        return 0
    encoder = _encoder()
    if encoder is not None:
        try:
            return len(encoder.encode(text))
        except Exception:
            pass
    return max(1, len(text) // 4)


def truncate_tokens(text: str, max_tokens: int, marker: str = "\n[Note: truncated to fit context.]") -> str:
    """Hard-truncate text to a token budget, keeping the head."""
    if max_tokens <= 0:
        return ""
    if count_tokens(text) <= max_tokens:
        return text
    encoder = _encoder()
    if encoder is not None:
        try:
            clipped = encoder.decode(encoder.encode(text)[:max_tokens])
            return clipped + marker
        except Exception:
            pass
    approx_chars = max_tokens * 4
    return text[:approx_chars] + marker
