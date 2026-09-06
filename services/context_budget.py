"""Token-aware context budgeting.

Priority order (highest first):
1. system instructions, 2. current request, 3. required tool state,
4. relevant memory, 5. recent conversation, 6. summary, 7. external content.

The current user request is NEVER truncated. History is trimmed
oldest-first (always keeping at least the newest message). Token counts
are approximations (see services.tokens), so budgets stay conservative.
"""

from typing import Dict, List, Sequence, Tuple

from langchain_core.messages import BaseMessage

from services.tokens import count_tokens, truncate_tokens

CONTEXT_MAX_TOKENS: int = 24000
CTX_SYSTEM_TOKENS: int = 4000
CTX_CURRENT_TOKENS: int = 6000
CTX_HISTORY_TOKENS: int = 6000
CTX_MEMORY_TOKENS: int = 2000
CTX_SUMMARY_TOKENS: int = 2000
CTX_EXTERNAL_TOKENS: int = 4000


def _message_tokens(message: BaseMessage) -> int:
    """Count tokens for one message (content only)."""
    content = getattr(message, "content", "")
    if isinstance(content, list):
        text = "".join(
            b if isinstance(b, str) else str(b.get("text", "")) if isinstance(b, dict) else str(b)
            for b in content
        )
    else:
        text = str(content)
    return count_tokens(text)


def fit_history(
    history: Sequence[BaseMessage], budget_tokens: int = CTX_HISTORY_TOKENS
) -> Tuple[List[BaseMessage], Dict[str, int]]:
    """Trim history oldest-first to a token budget, keeping newest 1+.

    Returns (kept_messages, {"kept": n, "dropped": m, "tokens": t}).
    """
    items = list(history)
    if not items:
        return [], {"kept": 0, "dropped": 0, "tokens": 0}
    kept: List[BaseMessage] = []
    used = 0
    for message in reversed(items):
        cost = _message_tokens(message)
        if kept and used + cost > budget_tokens:
            break
        kept.append(message)
        used += cost
    kept.reverse()
    if not kept:
        kept = [items[-1]]
        used = _message_tokens(items[-1])
    return kept, {"kept": len(kept), "dropped": len(items) - len(kept), "tokens": used}


def fit_text(text: str, budget_tokens: int) -> str:
    """Cap a context chunk (memory/summary/external) to a token budget."""
    return truncate_tokens(text, budget_tokens)
