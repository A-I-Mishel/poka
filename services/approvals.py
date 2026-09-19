"""Human approvals for irreversible tool actions.

Model-supplied confirmation flags are forgeable (prompt injection can set
confirm=true), so destructive tools never trust them. Instead a tool call
without a valid approval mints a PENDING approval and refuses; the user
approves through the authenticated UI, which presents a server-minted,
single-use token. Approval tokens are never logged, never persisted in
chat history, and never visible to the model — the model only ever sees
the approval id.

Storage: per-user approvals.json (atomic writes under per-file locks),
same pattern as the KB vault. All failures degrade to closed (deny).
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from services.limits import APPROVAL_MAX_PENDING, APPROVAL_TTL_SECONDS
from services.obs import event as obs_event
from services.storage import _read_json, _write_json, path_lock, user_dir

logger = logging.getLogger(__name__)


def _approvals_path(user_id: Any):
    return user_dir(str(user_id or ""), create=True) / "approvals.json"


def _blank() -> Dict[str, Any]:
    return {"version": 1, "approvals": []}


def _load(user_id: Any) -> Dict[str, Any]:
    try:
        data, _ = _read_json(_approvals_path(user_id))
    except Exception:
        return _blank()
    if not isinstance(data, dict) or not isinstance(data.get("approvals"), list):
        return _blank()
    return data


def _save(user_id: Any, vault: Dict[str, Any]) -> None:
    _write_json(_approvals_path(user_id), vault)


def _now() -> float:
    return time.time()


def _prune(vault: Dict[str, Any], now: float) -> bool:
    """Drop consumed/rejected/expired records. Returns True when changed."""
    kept = []
    for a in vault.get("approvals", []):
        try:
            if not isinstance(a, dict) or a.get("status") != "pending":
                continue
            if float(a.get("expires", 0) or 0) <= now:
                continue
            kept.append(a)
        except (ValueError, TypeError):
            # Malformed entry: drop it rather than aborting whole vault op.
            continue
    changed = len(kept) != len(vault.get("approvals", []))
    vault["approvals"] = kept
    return changed


def _canonical_args(args: Dict[str, Any]) -> str:
    try:
        canon = {str(k): (v.strip() if isinstance(v, str) else v)
                 for k, v in (args or {}).items()}
        return json.dumps(canon, sort_keys=True, default=str)
    except Exception:
        return json.dumps({"_unserializable": True})


def _hash_token(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def request_approval(user_id: Any, tool: str, args: Dict[str, Any],
                     summary: str) -> Tuple[str, str, bool]:
    """Mint (or reuse) a pending approval. Returns (id, token, created).

    Identical pending actions dedupe to one approval id (token rotates).
    The token is returned to the caller for UI delivery only — never log
    it, never persist it in chat history. Never raises: failures deny.
    """
    now = _now()
    path = _approvals_path(user_id)
    try:
        with path_lock(path):
            vault = _load(user_id)
            _prune(vault, now)
            key = _canonical_args(args)
            for entry in vault.get("approvals", []):
                if (entry.get("tool") == tool
                        and entry.get("args_key") == key):
                    token = secrets.token_urlsafe(32)
                    entry["token_hash"] = _hash_token(token)
                    _save(user_id, vault)
                    try:
                        obs_event("approval.request", tool=tool,
                                  approval_id=str(entry.get("id", "")),
                                  deduped=True)
                    except Exception:
                        logger.debug("approval request event failed", exc_info=True)
                    return str(entry["id"]), token, False
            pending = [a for a in vault.get("approvals", []) if a.get("status") == "pending"]
            if len(pending) >= max(1, int(APPROVAL_MAX_PENDING)):
                # Evict the oldest pending approval rather than growing
                # without bound or failing the legitimate request.
                pending.sort(key=lambda a: float(a.get("created", 0) or 0))
                vault["approvals"] = [a for a in vault.get("approvals", [])
                                      if a.get("id") != pending[0].get("id")]
            approval_id = uuid.uuid4().hex[:16]
            token = secrets.token_urlsafe(32)
            vault.setdefault("approvals", []).append({
                "id": approval_id,
                "tool": str(tool or ""),
                "args": {str(k): v for k, v in (args or {}).items()
                         if isinstance(v, (str, int, float, bool)) or v is None},
                "args_key": key,
                "summary": str(summary or "")[:300],
                "status": "pending",
                "token_hash": _hash_token(token),
                "created": now,
                "expires": now + float(APPROVAL_TTL_SECONDS),
            })
            _save(user_id, vault)
            try:
                obs_event("approval.request", tool=tool, approval_id=approval_id)
            except Exception:
                logger.debug("approval request event failed", exc_info=True)
            return approval_id, token, True
    except Exception:
        # Storage failure: closed (the tool reports DENIED without an id).
        return "", "", False


def consume_approval(user_id: Any, tool: str, args: Dict[str, Any],
                     token: str) -> Tuple[bool, Any]:
    """Atomically validate + single-use-consume a token.

    Returns (True, stored_args) on success; (False, error_detail) with
    detail in {"unknown", "expired", "used", "mismatch"} otherwise.
    The stored (server-side) args are returned so execution never trusts
    caller-supplied values alongside a token.
    """
    now = _now()
    path = _approvals_path(user_id)
    try:
        with path_lock(path):
            vault = _load(user_id)
            want = _hash_token(token)
            key = _canonical_args(args)
            for entry in vault.get("approvals", []):
                if not isinstance(entry, dict) or not entry.get("id"):
                    continue
                if entry.get("status") != "pending":
                    continue
                # Match token first so an expired unrelated entry never
                # shadows a valid token for a different entry.
                if entry.get("token_hash") != want:
                    continue
                try:
                    expired = float(entry.get("expires", 0) or 0) <= now
                except (ValueError, TypeError):
                    expired = True
                if expired:
                    entry["status"] = "expired"
                    _save(user_id, vault)
                    return False, "expired"
                if entry.get("tool") != tool or entry.get("args_key") != key:
                    return False, "mismatch"
                entry["status"] = "consumed"
                _save(user_id, vault)
                try:
                    obs_event("approval.consumed", tool=tool,
                              approval_id=str(entry.get("id", "")))
                except Exception:
                    logger.debug("approval consumed event failed", exc_info=True)
                stored = entry.get("args")
                return True, dict(stored) if isinstance(stored, dict) else {}
            _prune(vault, now)
            try:
                _save(user_id, vault)
            except Exception:
                logger.debug("approval vault save failed", exc_info=True)
            return False, "unknown"
    except Exception:
        return False, "unknown"


def get_pending(user_id: Any, approval_id: str) -> Optional[Dict[str, Any]]:
    """Fetch one pending unexpired approval (metadata only, no token)."""
    try:
        vault = _load(user_id)
        now = _now()
        for entry in vault.get("approvals", []):
            try:
                if (isinstance(entry, dict) and entry.get("id") == approval_id
                        and entry.get("status") == "pending"
                        and float(entry.get("expires", 0) or 0) > now):
                    return {"id": entry["id"], "tool": entry.get("tool", ""),
                            "summary": entry.get("summary", ""),
                            "created": entry.get("created", 0),
                            "expires": entry.get("expires", 0)}
            except (ValueError, TypeError):
                continue
        return None
    except Exception:
        return None


def list_pending(user_id: Any, rotate_tokens: bool = False) -> List[Dict[str, Any]]:
    """List pending approvals. Tokens included ONLY when rotate_tokens is
    true (owner UI delivery) — each listed token is freshly minted and the
    previous one invalidated (single live token invariant)."""
    now = _now()
    path = _approvals_path(user_id)
    try:
        if not rotate_tokens:
            vault = _load(user_id)
            out: List[Dict[str, Any]] = []
            for a in vault.get("approvals", []):
                try:
                    if (isinstance(a, dict) and a.get("status") == "pending"
                            and float(a.get("expires", 0) or 0) > now and a.get("id")):
                        out.append({"id": a["id"], "tool": a.get("tool", ""),
                                    "summary": a.get("summary", ""),
                                    "created": a.get("created", 0),
                                    "expires": a.get("expires", 0)})
                except (ValueError, TypeError):
                    continue
            return out
        with path_lock(path):
            vault = _load(user_id)
            _prune(vault, now)
            out = []
            for entry in vault.get("approvals", []):
                if not isinstance(entry, dict) or entry.get("status") != "pending":
                    continue
                token = secrets.token_urlsafe(32)
                entry["token_hash"] = _hash_token(token)
                out.append({"id": entry["id"], "tool": entry.get("tool", ""),
                            "summary": entry.get("summary", ""),
                            "created": entry.get("created", 0),
                            "expires": entry.get("expires", 0),
                            "token": token})
            _save(user_id, vault)
            return out
    except Exception:
        return []


def pending_since(user_id: Any, since: float,
                  rotate_tokens: bool = False) -> List[Dict[str, Any]]:
    """Approvals created at/after `since` (per-turn surfacing)."""
    try:
        return [a for a in list_pending(user_id, rotate_tokens=rotate_tokens)
                if float(a.get("created", 0) or 0) >= float(since or 0)]
    except Exception:
        return []


def peek_args(user_id: Any, approval_id: str) -> Dict[str, Any]:
    """Return a pending approval's stored args for server-side execution.

    Internal use only (approve endpoint): args may contain user content,
    so they are never included in list responses or logs.
    """
    try:
        vault = _load(user_id)
        now = _now()
        for entry in vault.get("approvals", []):
            try:
                if (isinstance(entry, dict) and entry.get("id") == approval_id
                        and entry.get("status") == "pending"
                        and float(entry.get("expires", 0) or 0) > now):
                    stored = entry.get("args")
                    return dict(stored) if isinstance(stored, dict) else {}
            except (ValueError, TypeError):
                continue
        return {}
    except Exception:
        return {}


def reject_approval(user_id: Any, approval_id: str) -> bool:
    """Discard a pending approval. True when anything was removed."""
    path = _approvals_path(user_id)
    try:
        with path_lock(path):
            vault = _load(user_id)
            before = len(vault.get("approvals", []))
            vault["approvals"] = [
                a for a in vault.get("approvals", [])
                if not (isinstance(a, dict) and a.get("id") == approval_id)
            ]
            if len(vault["approvals"]) == before:
                return False
            _save(user_id, vault)
            try:
                obs_event("approval.rejected", approval_id=str(approval_id))
            except Exception:
                logger.debug("approval rejected event failed", exc_info=True)
            return True
    except Exception:
        return False
