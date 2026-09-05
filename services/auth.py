"""Authentication modes and access-token gate.

Modes (POKA_AUTH_MODE, default "open"):
- open:    local/dev/trusted use. Identity chain: env -> OIDC -> link token
           -> ephemeral, exactly like Phase 1. Link tokens work here.
- private: public deployment. ONLY env identity, logged-in OIDC users, or
           holders of a configured access token are admitted. Link-token
           identities are NOT accepted as authentication.

Access tokens (POKA_ACCESS_TOKENS, comma-separated, via env or Streamlit
Secrets): shared secrets verified with secrets.compare_digest. A verified
token yields a stable pseudonymous user id (sha256 of the token), so
holders keep their own isolated data and revocation = rotating the secret.
Raw tokens are never logged and never persisted to disk.

To plug a real provider (OAuth/OIDC IdP, DB users): implement
verify_<provider>() returning a stable user id and call it from
authenticate() before the token step. The rest of the app only sees
UserIdentity, so nothing downstream changes.
"""

import hashlib
import secrets
from dataclasses import dataclass
from typing import Optional

from services.identity import AuthRequired, UserIdentity, auth_mode, get_current_user
from services.secrets import get_secret


@dataclass(frozen=True)
class AuthResult:
    """Outcome of authenticating the current visitor."""

    identity: UserIdentity
    authenticated: bool
    method: str  # env | oidc | token | link | ephemeral


def _configured_tokens() -> list:
    """Parse configured access tokens (never logged, never echoed).

    Read through the central secret seam so tokens work identically
    via Streamlit Secrets and environment variables.
    """
    raw = get_secret("POKA_ACCESS_TOKENS", "") or ""
    return [t.strip() for t in raw.split(",") if t.strip()]


def verify_access_token(token: object) -> Optional[str]:
    """Verify a presented token; return its stable user id or None.

    Comparison is constant-time. Returns None for missing/empty tokens
    without revealing whether any tokens are configured.
    """
    if not isinstance(token, str) or not token:
        return None
    for configured in _configured_tokens():
        try:
            if secrets.compare_digest(token, configured):
                digest = hashlib.sha256(configured.encode()).hexdigest()[:32]
                return f"token-{digest}"
        except TypeError:
            # Non-comparable pair (defensive: both sides are str here).
            # Anything else propagates instead of silently skipping.
            continue
    return None


def authenticate() -> AuthResult:
    """Authenticate the current visitor per the configured mode.

    Open mode preserves the full Phase 1 chain (link tokens admitted as
    anonymous). Private mode admits only env identity, logged-in OIDC
    users, verified session holders, or a valid ?token= parameter.

    Raises:
        AuthRequired: In private mode with no usable credential.
    """
    if auth_mode() != "private":
        identity = get_current_user()
        anonymous = identity.source in ("link", "ephemeral")
        return AuthResult(identity=identity, authenticated=not anonymous, method=identity.source)

    try:
        import streamlit as st

        session_uid = st.session_state.get("_auth_user_id")
        if isinstance(session_uid, str) and session_uid:
            return AuthResult(
                identity=UserIdentity(id=session_uid, email=None, source="token"),
                authenticated=True,
                method="token",
            )
        try:
            presented = st.query_params.get("token", "")
        except Exception:
            presented = ""
        verified = verify_access_token(presented)
        if verified:
            try:
                st.session_state["_auth_user_id"] = verified
            except Exception:
                pass
            return AuthResult(
                identity=UserIdentity(id=verified, email=None, source="token"),
                authenticated=True,
                method="token",
            )
    except AuthRequired:
        raise
    except Exception:
        pass

    # Single seam: in private mode this admits env/OIDC only, else raises.
    identity = get_current_user()
    return AuthResult(identity=identity, authenticated=True, method=identity.source)
