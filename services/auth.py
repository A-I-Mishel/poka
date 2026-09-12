"""Authentication modes and access-token gate.

Modes (PLUTO_AUTH_MODE, default "open"):
- open:    local/dev/trusted use. Identity chain: env identity, else a
           per-request ephemeral id.
- private: public deployment. ONLY the env identity or holders of a
           configured access token are admitted.

Access tokens (PLUTO_ACCESS_TOKENS, comma-separated, via env): shared
secrets verified with secrets.compare_digest. A verified token yields
a stable pseudonymous user id (sha256 of the token), so holders keep
their own isolated data and revocation = rotating the secret. Raw
tokens are never logged and never persisted to disk.

To plug a real provider (OAuth/OIDC IdP, DB users): implement
verify_<provider>() returning a stable user id and call it from
authenticate() before the token step. The rest of the app only sees
UserIdentity, so nothing downstream changes.
"""

import hashlib
import secrets
from dataclasses import dataclass
from typing import Optional

from services.identity import AuthRequired, UserIdentity, get_current_user
from services.secrets import get_secret


@dataclass(frozen=True)
class AuthResult:
    """Outcome of authenticating the current visitor."""

    identity: UserIdentity
    authenticated: bool
    method: str  # env | token | ephemeral


def _configured_tokens() -> list:
    """Parse configured access tokens (never logged, never echoed).

    Read through the central secret seam so tokens work identically
    wherever the app runs.
    """
    raw = get_secret("PLUTO_ACCESS_TOKENS", "") or ""
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


def authenticate(presented_token: Optional[object] = None) -> AuthResult:
    """Authenticate one visitor: the single source of truth for identity.

    Resolution order (the whole app funnels through here):
    1. A presented access token, verified via verify_access_token()
       (works in every auth mode; stable pseudonymous id).
    2. Otherwise the mode chain from get_current_user(): env identity,
       else a per-request ephemeral id in open mode; env-only in
       private mode.

    Raises:
        AuthRequired: Bad presented token ("Invalid access token."),
            or private mode with no usable credential
            ("Authentication required.").
    """
    if presented_token:
        user_id = verify_access_token(presented_token)
        if user_id is None:
            raise AuthRequired("Invalid access token.")
        identity = UserIdentity(id=user_id, email=None, source="token")
        return AuthResult(identity=identity, authenticated=True, method="token")
    try:
        identity = get_current_user()
    except AuthRequired:
        raise AuthRequired("Authentication required.")
    return AuthResult(
        identity=identity,
        authenticated=identity.source != "ephemeral",
        method=identity.source,
    )
