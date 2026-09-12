"""Request identity and per-user stores for the API.

Every request resolves to exactly one user id, binds it on the calling
thread (agent tool workers re-bind from here explicitly), and points
memory at that user's vault.

Identity resolution lives in services.auth.authenticate() (env →
token → ephemeral/open): this dependency only parses transport
(HTTP Bearer), maps auth failures to 401, and binds the result.
1. ``Authorization: Bearer <token>`` verified via services.auth when the
   caller presents one (works in every auth mode).
2. Otherwise, in non-private mode, the local identity chain
   (env PLUTO_USER_ID, ephemeral).
3. Otherwise HTTP 401.
"""

from dataclasses import dataclass
from typing import Optional

from fastapi import Header, HTTPException, Request

from services.auth import authenticate
from services.context import set_current_user_id, set_limit_key
from services.files import FileStore
from services.identity import AuthRequired
from services.memory import set_memory_dir
from services.ratelimit import extract_client_ip, limit_key_for
from services.storage import UserStore


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
    """Identity source: "env" | "token" (stable) or "ephemeral"."""


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
) -> UserContext:
    """FastAPI dependency: authenticate and bind the request user."""
    try:
        result = authenticate(_bearer_token(authorization))
    except AuthRequired as e:
        raise HTTPException(status_code=401, detail=str(e))
    user_id = result.identity.id
    source = result.identity.source
    peer = request.client.host if request.client else ""
    limit_key = limit_key_for(
        source, user_id, extract_client_ip(request.headers.get("x-forwarded-for", ""), peer)
    )
    bind_request_user(user_id, limit_key, source)
    user_store = UserStore(user_id, run_migration=source in ("env", "token"))
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
        set_memory_dir(str(UserStore(user_id, run_migration=source in ("env", "token")).root))
    except Exception:
        pass
