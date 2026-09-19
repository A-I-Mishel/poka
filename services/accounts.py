"""Username/password accounts with opaque session tokens.

Each account owns a stable user id (`acct-<hex>`), so chats, memory,
uploads, and document vectors — all keyed by user id in per-user
vaults — isolate automatically per account with no downstream changes.

Storage: one host-level registry (`data/accounts.json`, atomic writes
under per-file locks, same pattern as services.storage). Passwords
use PBKDF2-HMAC-SHA256 (200k iterations, per-user salt); only salt +
hash hex are persisted, never cleartext. Session tokens are 256-bit
random (`pluto_`-prefixed; legacy unprefixed tokens still verify) and
only their SHA-256 hex is persisted — the raw token is shown
exactly once at signup/login and travels thereafter as a Bearer token
through the existing auth chain (services.auth verifies sessions
first, so accounts work in every auth mode, including private).

Hardening: new passwords must pass a strength check (length, not the
username, not a common password, 3-of-4 character classes); repeated
failed logins lock the account briefly (429); password change rotates
the credential and revokes every session.

All failures raise AccountError subclasses with user-safe messages
(routers map them to status codes). Nothing here logs secrets.
"""

import hashlib
import re
import secrets
import time
from typing import Any, Dict, List, Optional, Tuple

from services.obs import event as obs_event
from services.storage import _read_json, _write_json, data_root, path_lock

_ACCOUNTS_FILE = "accounts.json"

# Session lifetime: 30 days. verify_session() rejects expired entries
# and load paths prune them best-effort so the registry cannot grow
# forever from login churn.
_SESSION_TTL_SECONDS = 30 * 86400.0

# Brute-force lockout: 5 failures inside a 15-minute window locks the
# account for 15 minutes (429). Counters live on the user record and
# reset on success. Unknown usernames never lock (that would oracle
# existence) — they burn a dummy PBKDF2 and return the generic 401.
# Trade-off: the 429 "Too many … Try again in Xs" confirms that the
# username exists (vs 401 for unknown). Accepted for brute-force friction;
# the alternative (always 401) would hide existence but let attackers
# hammer without back-off.
_LOCKOUT_MAX_FAILS = 5
_LOCKOUT_WINDOW_SECONDS = 15 * 60.0
_LOCKOUT_DURATION_SECONDS = 15 * 60.0

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


class AccountLocked(AccountError):
    """Too many failed logins; retry after the told delay (maps to 429)."""


class AccountWeakPassword(AccountError):
    """New password fails the strength check (signup/change only)."""


class AccountUnavailable(AccountError):
    """Storage/infra failure (maps to 503, never to blank state)."""


def _accounts_path():
    return data_root() / _ACCOUNTS_FILE


def _blank_registry() -> Dict[str, Any]:
    return {"version": 1, "users": {}, "sessions": {}}


def _prune_expired_sessions(reg: Dict[str, Any], now: Optional[float] = None) -> bool:
    """Drop sessions older than the TTL. Returns True when anything changed."""
    try:
        sessions = reg.get("sessions")
        if not isinstance(sessions, dict):
            return False
        cutoff = (now if now is not None else time.time()) - _SESSION_TTL_SECONDS
        expired = [
            digest for digest, entry in sessions.items()
            if not isinstance(entry, dict)
            or not isinstance(entry.get("created"), (int, float))
            or float(entry["created"]) < cutoff
        ]
        for digest in expired:
            sessions.pop(digest, None)
        return bool(expired)
    except Exception:
        return False


def _load_registry() -> Dict[str, Any]:
    """Load the registry; blank on missing/corrupt, raise on infra failure.

    Malformed JSON is already quarantined by storage._read_json
    (returns was_corrupt=True). Structurally invalid payloads
    (wrong shape) are quarantined here the same way instead of
    silently wiping all accounts. Permission/IO errors propagate
    as AccountUnavailable and must surface as 503, never as empty state.
    """
    from services.storage import StorageError
    try:
        data, was_corrupt = _read_json(_accounts_path())
    except StorageError as e:
        raise AccountUnavailable("Account storage unavailable. Try again.") from e
    if data is None:
        # Missing -> blank; corrupt -> blank (file already quarantined).
        return _blank_registry()
    if not isinstance(data, dict):
        _quarantine_registry("not-a-dict")
        return _blank_registry()
    users = data.get("users")
    sessions = data.get("sessions")
    if not isinstance(users, dict) or not isinstance(sessions, dict):
        _quarantine_registry("bad-shape")
        return _blank_registry()
    return {"version": 1, "users": users, "sessions": sessions}


def _quarantine_registry(reason: str) -> None:
    """Move a structurally invalid accounts.json aside (best-effort)."""
    import os
    import time
    from services.storage import path_lock
    try:
        path = _accounts_path()
        stamp = "%d-%d-%s" % (int(time.time() * 1000), os.getpid(), reason)
        backup = path.with_name(f"{path.stem}.corrupt-{stamp}{path.suffix}")
        with path_lock(path):
            if path.exists():
                os.replace(path, backup)
        obs_event("accounts.quarantine", reason=reason)
    except Exception:
        pass


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


# Small denylist of the most-guessed passwords (compared case-insensitively,
# with trailing digits stripped so "password1"/"qwerty123" also fail).
_COMMON_PASSWORDS = frozenset({
    "password", "passw0rd", "qwerty", "letmein", "welcome", "monkey",
    "dragon", "master", "sunshine", "princess", "football", "charlie",
    "superman", "michael", "shadow", "jesus", "iloveyou", "trustno1",
    "admin", "pluto", "poka", "changeme", "secret", "12345678", "87654321",
})


def password_strength(password: str, username_key: str = "") -> Optional[str]:
    """Return None when strong, else a user-safe reason string.

    Pure function (no I/O) so the frontend and tests can share it:
    length, not the username, not a common password, and 3 of 4
    character classes (lower/upper/digit/symbol).
    """
    text = str(password or "")
    if not (_MIN_PASSWORD_CHARS <= len(text) <= _MAX_PASSWORD_CHARS):
        return "Password must be %d-%d characters." % (
            _MIN_PASSWORD_CHARS, _MAX_PASSWORD_CHARS)
    lowered = text.lower()
    if username_key and (lowered == username_key or username_key in lowered
                         or lowered in username_key):
        return "Password must not contain your username."
    stripped = lowered.rstrip("0123456789!@#$%^&*")
    if lowered in _COMMON_PASSWORDS or stripped in _COMMON_PASSWORDS:
        return "That password is too common. Pick something less guessable."
    classes = sum((
        bool(re.search(r"[a-z]", text)),
        bool(re.search(r"[A-Z]", text)),
        bool(re.search(r"[0-9]", text)),
        bool(re.search(r"[^A-Za-z0-9]", text)),
    ))
    if classes < 3:
        return ("Password needs characters from 3 of these 4 groups: "
                "a-z, A-Z, 0-9, symbols.")
    return None


def _check_new_password(raw: Any, username_key: str = "") -> str:
    """Validate a new password (signup/change); raise AccountWeakPassword."""
    text = str(raw or "")
    reason = password_strength(text, username_key)
    if reason is not None:
        raise AccountWeakPassword(reason)
    return text


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    ).hex()


def _user_id_for(key: str) -> str:
    """Stable vault id for an account (deterministic across restarts)."""
    return "acct-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def _mint_session(reg: Dict[str, Any], user_id: str, agent: str = "") -> str:
    """Create a session; return the raw token (shown once, never stored).

    Tokens carry a `pluto_` prefix so users/support can recognize them;
    verification hashes the whole string, so legacy unprefixed tokens
    keep working. Only the digest + metadata persist.
    """
    raw = "pluto_" + secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    reg["sessions"][digest] = {
        "user_id": user_id,
        "created": time.time(),
        "agent": str(agent or "")[:120],
    }
    return raw


def _dummy_verify() -> None:
    """Burn PBKDF2 time for unknown users so login timing leaks less."""
    try:
        _hash_password(secrets.token_urlsafe(12), secrets.token_bytes(_SALT_BYTES))
    except Exception:
        pass


def _lockout_remaining(record: Dict[str, Any], now: float) -> float:
    """Seconds left on the account lockout, or 0 when not locked."""
    try:
        locked_until = float(record.get("locked_until") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, locked_until - now)


def _register_fail(record: Dict[str, Any], now: float) -> float:
    """Count one failed login; return lockout seconds imposed (0 or more)."""
    try:
        first = float(record.get("failed_first") or 0.0)
        count = int(record.get("failed_count") or 0)
    except (TypeError, ValueError):
        first, count = 0.0, 0
    if first <= 0 or (now - first) > _LOCKOUT_WINDOW_SECONDS:
        first, count = now, 0
    count += 1
    record["failed_first"] = first
    record["failed_count"] = count
    if count >= _LOCKOUT_MAX_FAILS:
        record["locked_until"] = now + _LOCKOUT_DURATION_SECONDS
        record["failed_first"] = 0.0
        record["failed_count"] = 0
        return _LOCKOUT_DURATION_SECONDS
    return 0.0


def _reset_fail(record: Dict[str, Any]) -> None:
    """Clear failure counters after a successful login/password change."""
    record.pop("failed_count", None)
    record.pop("failed_first", None)
    record.pop("locked_until", None)


def _user_key_for_id(reg: Dict[str, Any], user_id: str) -> Optional[str]:
    """Registry username key owning a user id, or None."""
    for key, record in (reg.get("users") or {}).items():
        if isinstance(record, dict) and record.get("user_id") == user_id:
            return str(key)
    return None


def _revoke_user_sessions(reg: Dict[str, Any], user_id: str,
                          except_digest: Optional[str] = None) -> int:
    """Delete sessions owned by user_id (optionally keeping one)."""
    sessions = reg.get("sessions")
    if not isinstance(sessions, dict):
        return 0
    doomed = [
        digest for digest, entry in sessions.items()
        if isinstance(entry, dict) and entry.get("user_id") == user_id
        and digest != except_digest
    ]
    for digest in doomed:
        sessions.pop(digest, None)
    return len(doomed)


def signup(username: Any, password: Any, agent: str = "") -> Tuple[str, Dict[str, str]]:
    """Create an account and open its first session.

    Returns (raw_token, {"username", "user_id"}). Raises AccountExists
    when taken, AccountWeakPassword for guessable passwords,
    AccountError for bad shapes, AccountFull at the cap.
    Read-modify-write holds the registry file lock so concurrent
    signups cannot clobber each other.
    """
    from services.limits import MAX_ACCOUNTS_PER_HOST

    key = _normalize_username(username)
    secret = _check_new_password(password, key)
    path = _accounts_path()
    with path_lock(path):
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
        _prune_expired_sessions(reg)
        token = _mint_session(reg, user_id, agent)
        try:
            _save_registry(reg)
        except Exception as e:
            obs_event("auth.signup", status="error", reason="store-failed")
            raise AccountError("Could not create the account. Try again.") from e
    obs_event("auth.signup", status="ok")
    return token, {"username": str(username).strip(), "user_id": user_id}


def login(username: Any, password: Any, agent: str = "") -> Tuple[str, Dict[str, str]]:
    """Verify credentials and open a session.

    Returns (raw_token, {"username", "user_id"}). Raises
    AccountAuthFailed for unknown users AND wrong passwords alike
    (never reveals which half failed; unknown users still burn a
    dummy PBKDF2 so timing leaks less). Raises AccountLocked (429)
    while a brute-force lockout is active.
    """
    key = str(username or "").strip().lower()
    secret = str(password or "")
    path = _accounts_path()
    with path_lock(path):
        reg = _load_registry()
        record = reg["users"].get(key)
        if not isinstance(record, dict):
            _dummy_verify()
            obs_event("auth.login", status="denied")
            raise AccountAuthFailed("Invalid username or password.")
        now = time.time()
        remaining = _lockout_remaining(record, now)
        if remaining > 0:
            try:
                _save_registry(reg)
            except Exception:
                pass
            obs_event("auth.login", status="locked")
            raise AccountLocked(
                "Too many failed attempts. Try again in %ds."
                % int(remaining + 0.5))
        try:
            salt = bytes.fromhex(str(record.get("salt") or ""))
            expected = str(record.get("hash") or "")
            candidate = _hash_password(secret, salt)
        except (ValueError, TypeError):
            obs_event("auth.login", status="denied")
            raise AccountAuthFailed("Invalid username or password.")
        if not expected or not secrets.compare_digest(candidate, expected):
            imposed = _register_fail(record, now)
            try:
                _save_registry(reg)
            except Exception:
                pass
            if imposed > 0:
                obs_event("auth.login", status="locked")
                raise AccountLocked(
                    "Too many failed attempts. Try again in %ds."
                    % int(imposed + 0.5))
            obs_event("auth.login", status="denied")
            raise AccountAuthFailed("Invalid username or password.")
        _reset_fail(record)
        user_id = str(record.get("user_id") or _user_id_for(key))
        _prune_expired_sessions(reg)
        token = _mint_session(reg, user_id, agent)
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


def change_password(user_id: Any, current_password: Any,
                    new_password: Any, agent: str = "") -> Tuple[str, Dict[str, str]]:
    """Rotate an account's password; revoke every session; open a fresh one.

    Verifies the current password (generic AccountAuthFailed on mismatch
    so a stolen session alone cannot probe), strength-checks the new one,
    then returns (raw_token, info) for the caller's new session. The
    caller must replace its stored token — all old ones are dead.
    The new session preserves the device `agent` label (User-Agent).
    """
    target = str(user_id or "")
    path = _accounts_path()
    with path_lock(path):
        reg = _load_registry()
        key = _user_key_for_id(reg, target)
        if key is None:
            raise AccountAuthFailed("Invalid username or password.")
        record = reg["users"].get(key)
        if not isinstance(record, dict):
            raise AccountAuthFailed("Invalid username or password.")
        try:
            salt = bytes.fromhex(str(record.get("salt") or ""))
            expected = str(record.get("hash") or "")
            candidate = _hash_password(str(current_password or ""), salt)
        except (ValueError, TypeError):
            raise AccountAuthFailed("Invalid username or password.")
        if not expected or not secrets.compare_digest(candidate, expected):
            obs_event("auth.change_password", status="denied")
            raise AccountAuthFailed("Invalid username or password.")
        new_secret = _check_new_password(new_password, key)
        new_salt = secrets.token_bytes(_SALT_BYTES)
        record["salt"] = new_salt.hex()
        record["hash"] = _hash_password(new_secret, new_salt)
        _reset_fail(record)
        _revoke_user_sessions(reg, target)
        token = _mint_session(reg, target, agent)
        try:
            _save_registry(reg)
        except Exception as e:
            obs_event("auth.change_password", status="error")
            raise AccountError("Could not change the password. Try again.") from e
    obs_event("auth.change_password", status="ok")
    return token, {"username": str(record.get("username") or key),
                   "user_id": target}


def list_sessions(user_id: Any, current_token: Any = None) -> List[Dict[str, Any]]:
    """Live sessions for one user, newest first (never raises).

    Each entry: {"created": ts, "current": bool, "agent": str}. The raw
    token never leaves the digest comparison — only the flag does.
    """
    target = str(user_id or "")
    if not target:
        return []
    try:
        digest = (hashlib.sha256(str(current_token).encode("utf-8")).hexdigest()
                  if isinstance(current_token, str) and current_token else "")
    except Exception:
        digest = ""
    try:
        reg = _load_registry()
    except AccountUnavailable:
        raise
    except Exception:
        return []
    now = time.time()
    out: List[Dict[str, Any]] = []
    sessions = reg.get("sessions")
    if not isinstance(sessions, dict):
        return []
    for key, entry in sessions.items():
        if not isinstance(entry, dict) or entry.get("user_id") != target:
            continue
        try:
            created = float(entry.get("created") or 0.0)
        except (TypeError, ValueError):
            continue
        if created <= 0 or (now - created) > _SESSION_TTL_SECONDS:
            continue
        out.append({
            "created": created,
            "current": bool(digest) and secrets.compare_digest(str(key), digest),
            "agent": str(entry.get("agent") or ""),
        })
    out.sort(key=lambda e: e["created"], reverse=True)
    return out


def logout_all(user_id: Any) -> int:
    """Revoke every session owned by user_id. Returns count revoked."""
    target = str(user_id or "")
    if not target:
        return 0
    path = _accounts_path()
    try:
        with path_lock(path):
            reg = _load_registry()
            revoked = _revoke_user_sessions(reg, target)
            if revoked:
                try:
                    _save_registry(reg)
                except Exception:
                    return 0
            return revoked
    except AccountUnavailable:
        raise
    except Exception:
        return 0


def verify_session(token: Any) -> Optional[str]:
    """Return the owning user id for a live session token, or None."""
    if not isinstance(token, str) or not token:
        return None
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    try:
        reg = _load_registry()
    except AccountUnavailable:
        raise
    except Exception:
        return None
    entry = reg["sessions"].get(digest)
    if not isinstance(entry, dict):
        return None
    try:
        created = float(entry.get("created") or 0.0)
    except (TypeError, ValueError):
        return None
    if created <= 0 or (time.time() - created) > _SESSION_TTL_SECONDS:
        return None
    user_id = entry.get("user_id")
    return str(user_id) if user_id else None


def logout(token: Any) -> bool:
    """Revoke one session token. True when anything was revoked."""
    if not isinstance(token, str) or not token:
        return False
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    path = _accounts_path()
    try:
        with path_lock(path):
            reg = _load_registry()
            if digest not in reg["sessions"]:
                # Still prune occasionally so expired entries don't pile.
                if _prune_expired_sessions(reg):
                    try:
                        _save_registry(reg)
                    except Exception:
                        pass
                return False
            del reg["sessions"][digest]
            _prune_expired_sessions(reg)
            try:
                _save_registry(reg)
            except Exception:
                return False
    except AccountUnavailable:
        raise
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
    except AccountUnavailable:
        raise
    except Exception:
        return None
    for record in reg["users"].values():
        if isinstance(record, dict) and record.get("user_id") == target:
            name = record.get("username")
            return str(name) if name else None
    return None
