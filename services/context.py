"""Request-scoped current-user context.

The UI sets the user ID once per script run; tools and services read it
to resolve per-user resources. Never trust model-provided paths.
"""

from contextvars import ContextVar
from typing import Optional

_current_user_id: ContextVar[Optional[str]] = ContextVar(
    "pluto_user_id", default=None
)

_limit_key: ContextVar[Optional[str]] = ContextVar(
    "pluto_limit_key", default=None
)

_preferred_vision_tier: ContextVar[Optional[str]] = ContextVar(
    "pluto_preferred_vision_tier", default=None
)


def set_current_user_id(user_id: Optional[str]) -> None:
    """Bind a user ID to the current request context."""
    _current_user_id.set(user_id)


def get_current_user_id() -> Optional[str]:
    """Return the user ID bound to the current request, if any."""
    return _current_user_id.get()


def set_limit_key(key: Optional[str]) -> None:
    """Bind a rate-limit identity for the current request context.

    Stable for logged-in/pinned users (their user ID); client-IP based
    for ephemeral open-mode visitors so limits actually bind.
    """
    _limit_key.set(key)


def get_limit_key() -> Optional[str]:
    """Return the rate-limit identity bound to the current request, if any."""
    return _limit_key.get()


def set_preferred_vision_tier(tier: Optional[str]) -> None:
    """Bind the request's pinned tier for vision-OCR preference.

    Document picture transcription (pdf_tool/document_tool) runs inside
    pool-worker threads that never inherit this binding — callers must
    re-bind it there like the user ID (see _run_tool_with_context).
    Vision helpers only honor it when the tier is vision-capable;
    otherwise cascade order applies unchanged.
    """
    _preferred_vision_tier.set(tier)


def get_preferred_vision_tier() -> Optional[str]:
    """Return the pinned tier bound for vision-OCR preference, if any."""
    return _preferred_vision_tier.get()
