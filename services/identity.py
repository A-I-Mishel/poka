"""User identity abstraction with a replaceable provider model.

Resolution order:
1. POKA_USER_ID environment variable (local dev, tests, operators).
2. Streamlit Cloud logged-in viewer (st.user email, hashed — stable).
3. Browser link token (?uid=...) when present and well-formed.
4. Fresh random token, written back to ?uid= so it survives reloads.

Sources 1-3 are stable across sessions. Source 4 is per-visitor until the
URL is lost. To add a real auth provider later, implement the same
get_current_user() contract and put it first in the chain.
"""

import hashlib
import re
import secrets
from dataclasses import dataclass
from typing import Optional

from services.secrets import get_secret

_UID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


@dataclass(frozen=True)
class UserIdentity:
    """An authenticated-or-anonymous visitor identity."""

    id: str
    email: Optional[str]
    source: str  # "env" | "oidc" | "link" | "ephemeral" | "token"


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


def _oidc_identity() -> Optional[UserIdentity]:
    try:
        import streamlit as st

        user = getattr(st, "user", None)
        if user is None:
            return None
        if not bool(getattr(user, "is_logged_in", False)):
            return None
        email = getattr(user, "email", None)
        if not email or not isinstance(email, str):
            return None
        digest = hashlib.sha256(email.strip().lower().encode()).hexdigest()[:32]
        return UserIdentity(id=f"oidc-{digest}", email=email, source="oidc")
    except Exception:
        return None


def _link_identity() -> Optional[UserIdentity]:
    try:
        import streamlit as st

        uid = st.query_params.get("uid", "")
        if isinstance(uid, str) and _UID_RE.match(uid):
            return UserIdentity(id=uid, email=None, source="link")
    except Exception:
        pass
    return None


def get_current_user() -> UserIdentity:
    """Resolve the current visitor identity (single entry point).

    In private mode only env identity and logged-in OIDC users are
    admitted; link tokens and ephemeral IDs raise AuthRequired.
    In open mode the full chain applies (link/ephemeral allowed).

    Raises:
        AuthRequired: In private mode with no usable credential.
        RuntimeError: Only when running outside any resolvable context
            (no env, no Streamlit runtime at all).
    """
    if auth_mode() == "private":
        for provider in (_env_identity, _oidc_identity):
            identity = provider()
            if identity is not None:
                return identity
        raise AuthRequired(
            "This app is private. Sign in with an access token to continue."
        )
    for provider in (_env_identity, _oidc_identity, _link_identity):
        identity = provider()
        if identity is not None:
            return identity
    token = secrets.token_urlsafe(12)
    try:
        import streamlit as st

        st.query_params["uid"] = token
    except Exception:
        pass
    return UserIdentity(id=token, email=None, source="ephemeral")
