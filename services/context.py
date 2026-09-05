"""Request-scoped current-user context.

The UI sets the user ID once per script run; tools and services read it
to resolve per-user resources. Never trust model-provided paths.
"""

from contextvars import ContextVar
from typing import Optional

_current_user_id: ContextVar[Optional[str]] = ContextVar(
    "poka_user_id", default=None
)


def set_current_user_id(user_id: Optional[str]) -> None:
    """Bind a user ID to the current request context."""
    _current_user_id.set(user_id)


def get_current_user_id() -> Optional[str]:
    """Return the user ID bound to the current request, if any."""
    return _current_user_id.get()
