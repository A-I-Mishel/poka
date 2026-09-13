"""Username/password accounts with opaque session tokens.

Each account owns a stable user id (`acct-<hex>`), so chats, memory,
uploads, and document vectors — all keyed by user id in per-user
vaults — isolate automatically per account with no downstream changes.

Storage: one host-level registry (`data/accounts.json`, atomic writes
under per-file locks, same pattern as services.storage). Passwords
use PBKDF2-HMAC-SHA256 (200k iterations, per-user salt); only salt +
hash hex are persisted, never cleartext. Session tokens are 256-bit
random; only their SHA-256 hex is persisted — the raw token is shown
exactly once at signup/login and travels thereafter as a Bearer token
through the existing auth chain (services.auth verifies sessions
first, so accounts work in every auth mode, including private).

All failures raise AccountError subclasses with user-safe messages
(routers map them to status codes). Nothing here logs secrets.
"""

import hashlib
import re
import secrets
import time
from typing import Any, Dict, Optional, Tuple

from services.obs import event as obs_event
from services.storage import _read_json, _write_json, data_root

_ACCOUNTS_FILE = "accounts.json"

# PBKDF2 work factor (stdlib only — no native deps). ~0.1s per
# verify on typical hardware: negligible for logins, expensive for
# offline guessing alongside a strong per-user salt.
_PBKDF2_ITERATIONS = 200_000
_SALT_BYTES = 16

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
_MAX_PASSWORD_CHARS = 128
_MIN_PASSWORD_CHARS = 8


class AccountError(ValueError):
    """Base for user-safe account failures (message is safe to show)."""


class AccountExists(AccountError):
    """Username already taken (signup only)."""


class AccountAuthFailed(AccountError):
    """Bad username or password (login only — never says which)."""


class AccountFull(AccountError):
    """Host account cap reached."""


def _accounts_path():
    return data_root() / _ACCOUNTS_FILE


def _blank_registry() -> Dict[str, Any]:
    return {"version": 1, "users": {}, "sessions": {}}


def _load_registry() -> Dict[str, Any]:
    """Load the registry; blank (never raise) when missing/corrupt."""
    try:
        data, _ = _read_json(_accounts_path())
    except Exception:
        return _blank_registry()
    if not isinstance(data, dict):
        return _blank_registry()
    users = data.get("users")
    sessions = data.get("sessions")
    if not isinstance(users, dict) or not isinstance(sessions, dict):
        return _blank_registry()
    return {"version": 1, "users": users, "sessions": sessions}


def _save_registry(reg: Dict[str, Any]) -> None:
    _write_json(_accounts_path(), reg)


def _normalize_username(raw: Any) -> str:
    """Validate a username; return its canonical key or raise."""
    text = str(raw or "").strip()
    if not _USERNAME_RE.match(text):
        raise AccountError(
            "Username must be 3-32 characters: letters, digits, _, ., -."
        )
    return text.lower()


def _check_password(raw: Any) -> str:
    """Validate a password; return it or raise (never stored)."""
    text = str(raw or "")
    if not (_MIN_PASSWORD_CHARS <= len(text) <= _MAX_PASSWORD_CHARS):
        raise AccountError(
            "Password must be %d-%d characters."
            % (_MIN_PASSWORD_CHARS, _MAX_PASSWORD_CHARS)
        )
    return text


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    ).hex()


def _user_id_for(key: str) -> str:
    """Stable vault id for an account (deterministic across restarts)."""
    return "acct-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def _mint_session(reg: Dict[str, Any], user_id: str) -> str:
    """Create a session; return the raw token (shown once, never stored)."""
    raw = secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    reg["sessions"][digest] = {"user_id": user_id, "created": time.time()}
    return raw


def signup(username: Any, password: Any) -> Tuple[str, Dict[str, str]]:
    """Create an account and open its first session.

    Returns (raw_token, {"username", "user_id"}). Raises AccountExists
    when taken, AccountError for bad shapes, AccountFull at the cap.
    """
    from services.limits import MAX_ACCOUNTS_PER_HOST

    key = _normalize_username(username)
    secret = _check_password(password)
    reg = _load_registry()
    users = reg["users"]
    if key in users:
        raise AccountExists("Username is taken.")
    if len(users) >= MAX_ACCOUNTS_PER_HOST:
        obs_event("auth.signup", status="full")
        raise AccountFull("Account registration is full on this server.")
    salt = secrets.token_bytes(_SALT_BYTES)
    user_id = _user_id_for(key)
    users[key] = {
        "username": str(username).strip(),
        "salt": salt.hex(),
        "hash": _hash_password(secret, salt),
        "user_id": user_id,
        "created": time.time(),
    }
    token = _mint_session(reg, user_id)
    try:
        _save_registry(reg)
    except Exception as e:
        obs_event("auth.signup", status="error", reason="store-failed")
        raise AccountError("Could not create the account. Try again.") from e
    obs_event("auth.signup", status="ok")
    return token, {"username": users[key]["username"], "user_id": user_id}


def login(username: Any, password: Any) -> Tuple[str, Dict[str, str]]:
    """Verify credentials and open a session.

    Returns (raw_token, {"username", "user_id"}). Raises
    AccountAuthFailed for unknown users AND wrong passwords alike
    (never reveals which half failed).
    """
    key = str(username or "").strip().lower()
    secret = str(password or "")
    reg = _load_registry()
    record = reg["users"].get(key)
    if not isinstance(record, dict):
        obs_event("auth.login", status="denied")
        raise AccountAuthFailed("Invalid username or password.")
    try:
        salt = bytes.fromhex(str(record.get("salt") or ""))
        expected = str(record.get("hash") or "")
        candidate = _hash_password(secret, salt)
    except (ValueError, TypeError):
        obs_event("auth.login", status="denied")
        raise AccountAuthFailed("Invalid username or password.")
    if not expected or not secrets.compare_digest(candidate, expected):
        obs_event("auth.login", status="denied")
        raise AccountAuthFailed("Invalid username or password.")
    user_id = str(record.get("user_id") or _user_id_for(key))
    token = _mint_session(reg, user_id)
    try:
        _save_registry(reg)
    except Exception as e:
        obs_event("auth.login", status="error", reason="store-failed")
        raise AccountError("Could not start the session. Try again.") from e
    obs_event("auth.login", status="ok")
    return token, {
        "username": str(record.get("username") or username),
        "user_id": user_id,
    }


def verify_session(token: Any) -> Optional[str]:
    """Return the owning user id for a session token, or None."""
    if not isinstance(token, str) or not token:
        return None
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    try:
        reg = _load_registry()
    except Exception:
        return None
    entry = reg["sessions"].get(digest)
    if not isinstance(entry, dict):
        return None
    user_id = entry.get("user_id")
    return str(user_id) if user_id else None


def logout(token: Any) -> bool:
    """Revoke one session token. True when anything was revoked."""
    if not isinstance(token, str) or not token:
        return False
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    try:
        reg = _load_registry()
    except Exception:
        return False
    if digest not in reg["sessions"]:
        return False
    del reg["sessions"][digest]
    try:
        _save_registry(reg)
    except Exception:
        return False
    return True


def username_for_user(user_id: Any) -> Optional[str]:
    """Display username owning a user id, or None (token/env users)."""
    target = str(user_id or "")
    if not target:
        return None
    try:
        reg = _load_registry()
    except Exception:
        return None
    for record in reg["users"].values():
        if isinstance(record, dict) and record.get("user_id") == target:
            name = record.get("username")
            return str(name) if name else None
    return None
