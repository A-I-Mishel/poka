"""Shared pre-generation gate for expensive file-building tools.

Every file-generating tool must call claim_generation_slot() BEFORE
doing expensive work: it verifies user context (authorization to store
the artifact) and checks the generate quota. A denied request performs
no generation and persists nothing.

claim_tool_slot() is the same shape for non-generating tools: user
context + per-action rate check, or (None, STATUS=DENIED error).
Private-mode and service-availability checks stay at the call site
(their messages are tool-specific).
"""

from typing import Optional, Tuple

from services.context import get_current_user_id, get_limit_key
from services.obs import event as obs_event
from services.ratelimit import get_rate_limiter


def claim_generation_slot(tool_name: str) -> Tuple[Optional[str], Optional[str]]:
    """Authorize + rate-check one generation. Returns (user_id, None) or
    (None, STATUS=DENIED error). No expensive work may precede this call.
    """
    user_id = get_current_user_id()
    if not user_id:
        obs_event("ratelimit.deny", action="generate", tool=tool_name, reason="no_user")
        return None, (
            f"STATUS=DENIED tool={tool_name}: no user context, "
            "cannot store generated files."
        )
    verdict = get_rate_limiter().check(get_limit_key() or user_id, "generate")
    if not verdict.allowed:
        obs_event(
            "ratelimit.deny", action="generate", tool=tool_name,
            reason="quota", user=user_id, retry_after_s=round(verdict.retry_after, 1),
        )
        return None, (
            f"STATUS=DENIED tool={tool_name}: generation rate limit "
            f"exceeded, retry in {verdict.retry_after:.0f}s."
        )
    return user_id, None


def claim_tool_slot(tool_name: str, action: str, limit_noun: str) -> Tuple[Optional[str], Optional[str]]:
    """User context + rate check for one tool call.

    Returns (user_id, None) or (None, STATUS=DENIED error). limit_noun
    is the human noun in the rate message ("Gmail", "code-execution").
    """
    user_id = get_current_user_id()
    if not user_id:
        return None, f"STATUS=DENIED tool={tool_name}: no user context."
    verdict = get_rate_limiter().check(get_limit_key() or user_id, action)
    if not verdict.allowed:
        obs_event(
            "ratelimit.deny", action=action, tool=tool_name, user=user_id,
            retry_after_s=round(verdict.retry_after, 1),
        )
        return None, (
            f"STATUS=DENIED tool={tool_name}: {limit_noun} rate limit "
            f"exceeded, retry in {verdict.retry_after:.0f}s."
        )
    return user_id, None
