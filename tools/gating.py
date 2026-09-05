"""Shared pre-generation gate for expensive file-building tools.

Every file-generating tool must call claim_generation_slot() BEFORE
doing expensive work: it verifies user context (authorization to store
the artifact) and checks the generate quota. A denied request performs
no generation and persists nothing.
"""

from typing import Optional, Tuple

from services.context import get_current_user_id
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
    verdict = get_rate_limiter().check(user_id, "generate")
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
