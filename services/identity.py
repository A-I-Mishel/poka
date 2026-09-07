"""User identity abstraction with a replaceable provider model.

Resolution order:
1. POKA_USER_ID environment variable (local dev, tests, operators).
2. Fresh random token (per-request ephemeral identity).

Source 1 is stable across sessions. Source 2 is per-visitor until the
client presents a stable credential (e.g. an access token). To add a
real auth provider later, implement the same get_current_user()
contract and put it first in the chain.
"""

import re
import secrets
from dataclasses import dataclass
from typing import Optional

from services.secrets import get_secret


@dataclass(frozen=True)
class UserIdentity:
    """An authenticated-or-anonymous visitor identity."""

    id: str
    email: Optional[str]
    source: str  # "env" | "ephemeral" | "token"


class AuthRequired(Exception):
    """Raised when private mode has no usable credential for the visitor."""


def auth_mode() -> str:
    """Return 'private' only when explicitly configured, else 'open'."""
    mode = get_secret("POKA_AUTH_MODE", "open") or "open"
    return "private" if mode.strip().lower() == "private" else "open"


def _env_identity() -> Optional[UserIdentity]:
    raw = (get_secret("POKA_USER_ID", "") or "").strip()
    if not raw:
        return None
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", raw).strip(" .")[:64]
    if not safe:
        return None
    return UserIdentity(id=safe, email=None, source="env")


def get_current_user() -> UserIdentity:
    """Resolve the current visitor identity (single entry point).

    In private mode only the env identity is admitted; anything else
    raises AuthRequired. In open mode the env identity applies when
    configured, otherwise a fresh ephemeral id is minted.

    Raises:
        AuthRequired: In private mode with no usable credential.
    """
    if auth_mode() == "private":
        identity = _env_identity()
        if identity is not None:
            return identity
        raise AuthRequired(
            "This app is private. Sign in with an access token to continue."
        )
    identity = _env_identity()
    if identity is not None:
        return identity
    token = secrets.token_urlsafe(12)
    return UserIdentity(id=token, email=None, source="ephemeral")
