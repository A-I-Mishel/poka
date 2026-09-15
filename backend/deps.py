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
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional, Set

from fastapi import Header, HTTPException, Request

from services.auth import AuthResult, authenticate
from services.context import set_current_user_id, set_limit_key
from services.files import FileStore
from services.identity import AuthRequired, UserIdentity
from services.limits import STORAGE_HYGIENE_INTERVAL_SECONDS
from services.memory import set_memory_dir
from services.ratelimit import extract_client_ip, limit_key_for
from services.storage import UserStore

# Client-minted visitor ids (open mode only): strict shape so the
# header can never smuggle paths or collide with id namespaces by
# accident. Anything else falls back to a per-request ephemeral id.
# Raw ids are capped at 56 chars so the namespaced vault id
# ("visitor-<raw>") stays within the 64-char storage bound without
# truncation collisions.
_VISITOR_RE = re.compile(r"^[A-Za-z0-9_.-]{8,56}$")

# Prefix isolating visitor vaults from stable namespaces (env ids,
# "token-<hex>", "acct-<hex>"). Without it a visitor could set
# X-Pluto-Visitor to another user's account id and read their vault.
_VISITOR_PREFIX = "visitor-"

# Storage-hygiene throttle: last run per user id (per process). The pass
# itself is cheap (one chats JSON + two registries) but pointless more
# than a few times a day given day-scale retention thresholds.
_hygiene_lock = threading.Lock()
_last_hygiene: Dict[str, float] = {}

# Store caching: reuse UserStore/FileStore instances per user within a
# process. Invalidated on explicit write operations (not on reads).
# TTL fallback (5 min) handles external mutations (manual vault edits).
# Cache key includes data root path to support tests with tmp dirs.
_user_store_cache: Dict[str, tuple[float, UserStore]] = {}
_file_store_cache: Dict[str, tuple[float, FileStore]] = {}
_STORE_CACHE_TTL = 300.0  # 5 minutes


def _cache_key(user_id: str, run_migration: bool = False) -> str:
    """Generate cache key including data root path."""
    from services.storage import data_root
    root = str(data_root())
    return f"{user_id}:{root}:{run_migration}"


def _get_user_store(user_id: str, run_migration: bool) -> UserStore:
    """Get cached UserStore or create new one with migration flag."""
    now = time.time()
    key = _cache_key(user_id, run_migration)
    cached = _user_store_cache.get(key)
    if cached and now - cached[0] < _STORE_CACHE_TTL:
        return cached[1]
    store = UserStore(user_id, run_migration=run_migration)
    _user_store_cache[key] = (now, store)
    return store


def _get_file_store(user_id: str) -> FileStore:
    """Get cached FileStore or create new one."""
    now = time.time()
    key = _cache_key(user_id)
    cached = _file_store_cache.get(key)
    if cached and now - cached[0] < _STORE_CACHE_TTL:
        return cached[1]
    store = FileStore(user_id)
    _file_store_cache[key] = (now, store)
    return store


def invalidate_store_caches(user_id: str) -> None:
    """Invalidate cached stores for a user (call after write operations)."""
    # Remove all cache entries for this user_id (across all data roots)
    for key in list(_user_store_cache.keys()):
        if key.startswith(f"{user_id}:"):
            _user_store_cache.pop(key, None)
    for key in list(_file_store_cache.keys()):
        if key.startswith(f"{user_id}:"):
            _file_store_cache.pop(key, None)


def clear_all_store_caches() -> None:
    """Clear all store caches (for testing)."""
    _user_store_cache.clear()
    _file_store_cache.clear()


def _referenced_upload_ids(user_store: UserStore) -> Set[str]:
    """Upload IDs still cited by the user's chats (never raises)."""
    found: Set[str] = set()
    try:
        stored, _warnings = user_store.load_chats()
    except Exception:
        return found
    try:
        blobs = []
        if isinstance(stored, dict):
            current = stored.get("current", [])
            if isinstance(current, list):
                blobs.extend(current)
            for chat in stored.get("chats", []) or []:
                if isinstance(chat, dict) and isinstance(chat.get("messages"), list):
                    blobs.extend(chat["messages"])
        for msg in blobs:
            if not isinstance(msg, dict):
                continue
            atts = msg.get("attachments")
            if isinstance(atts, list):
                for entry in atts:
                    if isinstance(entry, dict) and entry.get("id"):
                        found.add(str(entry["id"]))
            legacy_image = msg.get("image")
            if legacy_image:
                found.add(str(legacy_image))
    except Exception:
        pass
    return found


def _run_storage_hygiene(user_store: UserStore, file_store: FileStore) -> None:
    """Prune expired outputs + stale unreferenced uploads (never raises).

    Throttled per user per process (STORAGE_HYGIENE_INTERVAL_SECONDS).
    Best-effort by design: hygiene must never fail or slow a request —
    failures degrade to "try again next interval".
    """
    user_id = str(getattr(file_store, "user_id", "") or "")
    if not user_id:
        return
    now = time.time()
    with _hygiene_lock:
        last = _last_hygiene.get(user_id, 0.0)
        if now - last < STORAGE_HYGIENE_INTERVAL_SECONDS:
            return
        _last_hygiene[user_id] = now
    try:
        try:
            file_store.prune_stale_outputs()
        except Exception:
            pass
        try:
            file_store.prune_stale_uploads(referenced_ids=_referenced_upload_ids(user_store))
        except Exception:
            pass
        try:
            file_store.prune_orphan_files()
        except Exception:
            pass
    except Exception:
        pass


def _visitor_id(raw: Optional[str]) -> Optional[str]:
    """Clean an X-Pluto-Visitor header, or None when unusable."""
    text = (raw or "").strip()
    if not _VISITOR_RE.match(text):
        return None
    text = text.strip(" .")
    return text or None


def visitor_vault_id(raw_visitor: str) -> str:
    """Namespace a raw visitor id into its vault id (never collides).

    Raw header values are client-minted bearer secrets; the vault id
    is always prefixed so it can never equal an env/token/account id.
    """
    return f"{_VISITOR_PREFIX}{raw_visitor}"


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
        # above), so the header cannot bypass it. The vault id is
        # namespaced ("visitor-<raw>") so a visitor can never squat on
        # an env/token/account vault by guessing its id.
        visitor = _visitor_id(x_pluto_visitor)
        if visitor is not None:
            result = AuthResult(
                identity=UserIdentity(id=visitor_vault_id(visitor), email=None, source="ephemeral"),
                authenticated=False,
                method="ephemeral",
            )
    user_id = result.identity.id
    source = result.identity.source
    peer = request.client.host if request.client else ""
    limit_key = limit_key_for(
        source, user_id, extract_client_ip(request.headers.get("x-forwarded-for", ""), peer)
    )
    run_migration = source in ("env", "token", "account")
    user_store = _get_user_store(user_id, run_migration)
    file_store = _get_file_store(user_id)
    bind_request_user(user_id, limit_key, source, root=user_store.root)
    # Hygiene moved to background scheduler (services/scheduler.py)
    return UserContext(
        user_id=user_id,
        user_store=user_store,
        file_store=file_store,
        limit_key=limit_key,
        source=source,
    )


def bind_request_user(user_id: str, limit_key: Optional[str] = None, source: str = "", root: Optional[object] = None) -> None:
    """Bind an already-authenticated user on the calling thread.

    Streaming generators run on a different worker thread than the
    endpoint, so they must re-bind explicitly before touching stores,
    memory, or the agent. Ephemeral visitors skip the legacy migration
    (their vaults are throwaway; migrating would litter the disk).
    Reuses the caller's UserStore.root when provided to avoid a second
    UserStore construction per request.
    """
    set_current_user_id(user_id)
    set_limit_key(limit_key if limit_key else user_id)
    try:
        if root is not None:
            set_memory_dir(str(root))
        else:
            set_memory_dir(str(_get_user_store(user_id, source in ("env", "token", "account")).root))
    except Exception:
        pass
