"""Request identity and per-user stores for the API.

Every request resolves to exactly one user id, binds it on the calling
thread (agent tool workers re-bind from here explicitly), and points
memory at that user's vault — the same binding app.py performs per run.

Identity resolution (no Streamlit involved):
1. ``Authorization: Bearer <token>`` verified via services.auth when the
   caller presents one (works in every auth mode).
2. Otherwise, in non-private mode, the local identity chain
   (env POKA_USER_ID, OIDC, ephemeral) — same as the desktop app.
3. Otherwise HTTP 401.
"""

from dataclasses import dataclass
from typing import Optional

from fastapi import Header, HTTPException

from services.auth import verify_access_token
from services.context import set_current_user_id
from services.files import FileStore
from services.identity import auth_mode, get_current_user
from services.memory import set_memory_dir
from services.storage import UserStore


@dataclass
class UserContext:
    """Everything a request needs, bound to one user."""

    user_id: str
    user_store: UserStore
    file_store: FileStore


def _bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


async def current_user(
    authorization: Optional[str] = Header(default=None),
) -> UserContext:
    """FastAPI dependency: authenticate and bind the request user."""
    presented = _bearer_token(authorization)
    user_id: Optional[str] = None
    if presented:
        user_id = verify_access_token(presented)
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid access token.")
    elif auth_mode() != "private":
        try:
            user_id = get_current_user().id
        except Exception:
            user_id = None
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    bind_request_user(user_id)
    user_store = UserStore(user_id)
    return UserContext(
        user_id=user_id,
        user_store=user_store,
        file_store=FileStore(user_id),
    )


def bind_request_user(user_id: str) -> None:
    """Bind an already-authenticated user on the calling thread.

    Streaming generators run on a different worker thread than the
    endpoint, so they must re-bind explicitly before touching stores,
    memory, or the agent.
    """
    set_current_user_id(user_id)
    try:
        set_memory_dir(str(UserStore(user_id).root))
    except Exception:
        pass
