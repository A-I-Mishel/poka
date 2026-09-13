"""Request identity and per-user stores for the API.

Every request resolves to exactly one user id, binds it on the calling
thread (agent tool workers re-bind from here explicitly), and points
memory at that user's vault.

Identity resolution lives in services.auth.authenticate() (session →
token → env/ephemeral/open): this dependency only parses transport
(HTTP Bearer + the open-mode visitor header), maps auth failures to
401, and binds the result.
1. ``Authorization: Bearer <token>`` verified via services.auth when the
   caller presents one — account sessions first, then access tokens
   (works in every auth mode; the visitor header is ignored here).
2. Otherwise, in non-private mode, the local identity chain
   (env PLUTO_USER_ID, then the client's stable ``X-Pluto-Visitor``
   id when well-formed, else a per-request ephemeral id). The visitor
   id is what keeps logged-out browsers on one vault (chats, memory)
   across requests; private mode never consults it.
3. Otherwise HTTP 401.
"""

import re
from dataclasses import dataclass
from typing import Optional

from fastapi import Header, HTTPException, Request

from services.auth import AuthResult, authenticate
from services.context import set_current_user_id, set_limit_key
from services.files import FileStore
from services.identity import AuthRequired, UserIdentity
from services.memory import set_memory_dir
from services.ratelimit import extract_client_ip, limit_key_for
from services.storage import UserStore

# Client-minted visitor ids (open mode only): strict shape so the
# header can never smuggle paths or collide with id namespaces by
# accident. Anything else falls back to a per-request ephemeral id.
_VISITOR_RE = re.compile(r"^[A-Za-z0-9_.-]{8,64}$")


def _visitor_id(raw: Optional[str]) -> Optional[str]:
    """Clean an X-Pluto-Visitor header, or None when unusable."""
    text = (raw or "").strip()
    if not _VISITOR_RE.match(text):
        return None
    text = text.strip(" .")
    return text or None


@dataclass
class UserContext:
    """Everything a request needs, bound to the calling thread."""

    user_id: str
    user_store: UserStore
    file_store: FileStore
    limit_key: str = ""
    """Rate-limit identity: the user ID for stable identities, or an
    `ip:<addr>` key for ephemeral open-mode visitors (see
    services.ratelimit.limit_key_for). Use this — never user_id — for
    limiter checks, or limits will not bind across requests."""
    source: str = ""
    """Identity source: "env" | "token" | "account" (stable) or "ephemeral"."""


def _bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


async def current_user(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_pluto_visitor: Optional[str] = Header(default=None),
) -> UserContext:
    """FastAPI dependency: authenticate and bind the request user."""
    try:
        result = authenticate(_bearer_token(authorization))
    except AuthRequired as e:
        raise HTTPException(status_code=401, detail=str(e))
    if result.identity.source == "ephemeral":
        # Open mode without a credential: pin the browser to one vault
        # via its visitor id instead of a fresh random id per request
        # (which orphaned every chat on the very next refresh).
        # Private mode never reaches here without a credential (401
        # above), so the header cannot bypass it.
        visitor = _visitor_id(x_pluto_visitor)
        if visitor is not None:
            result = AuthResult(
                identity=UserIdentity(id=visitor, email=None, source="ephemeral"),
                authenticated=False,
                method="ephemeral",
            )
    user_id = result.identity.id
    source = result.identity.source
    peer = request.client.host if request.client else ""
    limit_key = limit_key_for(
        source, user_id, extract_client_ip(request.headers.get("x-forwarded-for", ""), peer)
    )
    bind_request_user(user_id, limit_key, source)
    user_store = UserStore(user_id, run_migration=source in ("env", "token", "account"))
    return UserContext(
        user_id=user_id,
        user_store=user_store,
        file_store=FileStore(user_id),
        limit_key=limit_key,
        source=source,
    )


def bind_request_user(user_id: str, limit_key: Optional[str] = None, source: str = "") -> None:
    """Bind an already-authenticated user on the calling thread.

    Streaming generators run on a different worker thread than the
    endpoint, so they must re-bind explicitly before touching stores,
    memory, or the agent. Ephemeral visitors skip the legacy migration
    (their vaults are throwaway; migrating would litter the disk).
    """
    set_current_user_id(user_id)
    set_limit_key(limit_key if limit_key else user_id)
    try:
        set_memory_dir(str(UserStore(user_id, run_migration=source in ("env", "token", "account")).root))
    except Exception:
        pass
