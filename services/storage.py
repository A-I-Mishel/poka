"""Per-user persistent storage (chats, notes, structured memory).

Layout:
    data/users/<safe-user-id>/chats.json
    data/users/<safe-user-id>/memory.md
    data/users/<safe-user-id>/structured.json

DATA_ROOT defaults to ./data and can be overridden with POKA_DATA_DIR
(useful for tests). All writes are atomic (tmp + os.replace). Corrupt
files are quarantined next to the original and reported as warnings
instead of silently resetting user data.
"""

import contextlib
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from services.obs import event as obs_event

MAX_STORED_CHATS: int = 20
MAX_MSGS_PER_CHAT: int = 100
ATTACH_KINDS = ("pdf", "csv", "image")


class StorageError(Exception):
    """Raised when a storage path or operation is unsafe or fails."""


def data_root() -> Path:
    """Return the configured data root directory."""
    return Path(os.getenv("POKA_DATA_DIR", "data"))


def sanitize_user_key(raw: Any) -> str:
    """Make a user ID safe for use as a single directory name."""
    text = str(raw or "").strip()
    if not text or ".." in text or "/" in text or "\\" in text:
        raise StorageError("Refusing to resolve storage for a path-like user ID.")
    text = re.sub(r"[^A-Za-z0-9_.-]", "_", text).strip(" .")
    if not text:
        raise StorageError("Refusing to resolve storage for an empty user ID.")
    return text[:64]


def user_dir(user_id: str) -> Path:
    """Resolve a user's directory, rejecting any traversal outside users/."""
    key = sanitize_user_key(user_id)
    base = (data_root() / "users").resolve()
    base.mkdir(parents=True, exist_ok=True)
    candidate = (base / key).resolve()
    if candidate != base and base not in candidate.parents:
        raise StorageError("User storage path escapes the users directory.")
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def _tmp_path(path: Path) -> Path:
    """Unique tmp sibling so concurrent writers never share one file."""
    token = f"{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex[:8]}"
    return path.with_name(f"{path.name}.{token}.tmp")


_locks_guard = threading.Lock()
_locks: Dict[str, threading.Lock] = {}


@contextlib.contextmanager
def path_lock(path: Path) -> Iterator[None]:
    """Per-file mutex so concurrent readers/writers never race on Windows."""
    try:
        key = str(path.resolve())
    except OSError:
        key = str(path.absolute())
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _locks[key] = lock
    with lock:
        yield


def atomic_replace(src: Path, dst: Path, attempts: int = 5) -> None:
    """os.replace with retries: Windows AV/indexer locks briefly race us."""
    last: Optional[Exception] = None
    for _ in range(attempts):
        try:
            os.replace(src, dst)
            return
        except OSError as e:
            last = e
            time.sleep(0.05)
    assert last is not None
    raise last


def _read_json(path: Path) -> Tuple[Any, bool]:
    """Read JSON, returning (data, was_corrupt). Missing file -> (None, False).

    Error classes are strictly separated:
    - FileNotFoundError -> missing state, (None, False).
    - JSON malformation (ValueError) -> corruption: the file is
      quarantined next to the original and (None, True) is returned.
    - PermissionError / other OSError -> infrastructure failure: raised
      as StorageError (never quarantined, never converted to empty
      state). Callers must surface this instead of silently resetting.
    """
    try:
        with path_lock(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f), False
    except FileNotFoundError:
        return None, False
    except PermissionError as e:
        obs_event("storage.read", status="error", reason="permission", file=path.name)
        raise StorageError(f"Cannot read {path.name}: permission denied.") from e
    except OSError as e:
        obs_event("storage.read", status="error", reason="io", file=path.name)
        raise StorageError(f"Cannot read {path.name}: storage failure ({e}).") from e
    except ValueError:
        try:
            backup = path.with_name(f"{path.stem}.corrupt-{int(time.time())}{path.suffix}")
            os.replace(path, backup)
        except OSError:
            pass
        obs_event("storage.quarantine", file=path.name)
        return None, True


def _write_json(path: Path, payload: Any) -> None:
    """Write JSON atomically via unique-tmp + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _tmp_path(path)
    try:
        with path_lock(path):
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            atomic_replace(tmp_path, path)
    except OSError as e:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        obs_event("storage.write", status="error", file=path.name)
        raise StorageError(f"Could not persist {path.name}: {e}") from e


def _clean_attachment(value: Any) -> Optional[Dict[str, str]]:
    if not isinstance(value, dict):
        return None
    upload_id = value.get("id")
    kind = value.get("kind")
    name = value.get("name", "")
    if not isinstance(upload_id, str) or not upload_id:
        return None
    if kind not in ATTACH_KINDS:
        return None
    if not isinstance(name, str):
        return None
    return {"id": upload_id, "kind": kind, "name": name[:120]}


def clean_messages(messages: Any) -> List[Dict[str, Any]]:
    """Validate/trim a message list, preserving role/content/time/attachments."""
    cleaned: List[Dict[str, Any]] = []
    if isinstance(messages, list):
        for m in messages:
            if (
                not isinstance(m, dict)
                or m.get("role") not in ("user", "assistant")
                or not isinstance(m.get("content"), str)
            ):
                continue
            entry: Dict[str, Any] = {"role": m["role"], "content": m["content"]}
            if isinstance(m.get("time"), str):
                entry["time"] = m["time"]
            if isinstance(m.get("image"), str):
                entry["image"] = m["image"]
            if isinstance(m.get("images"), list):
                images = [str(p) for p in m["images"] if isinstance(p, str)]
                if images:
                    entry["images"] = images[:8]
            if isinstance(m.get("attachments"), list):
                atts = [_clean_attachment(a) for a in m["attachments"]]
                atts = [a for a in atts if a is not None]
                if atts:
                    entry["attachments"] = atts[:8]
            cleaned.append(entry)
    return cleaned[-MAX_MSGS_PER_CHAT:]


def _clean_chat_record(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    return {
        "title": str(value.get("title", "Untitled"))[:60],
        "messages": clean_messages(value.get("messages", [])),
    }


class UserStore:
    """All persistent state owned by one user ID."""

    def __init__(self, user_id: str) -> None:
        self.user_id: str = sanitize_user_key(user_id)
        self.root: Path = user_dir(self.user_id)
        self.chats_path: Path = self.root / "chats.json"
        self.memory_path: Path = self.root / "memory.md"
        self.structured_path: Path = self.root / "structured.json"
        self.migrate_legacy()

    # -- chats -------------------------------------------------
    def load_chats(self) -> Tuple[Dict[str, Any], List[str]]:
        """Return ({"chats": [...], "current": [...]}, warnings)."""
        warnings: List[str] = []
        try:
            data, corrupt = _read_json(self.chats_path)
        except StorageError as e:
            # Infrastructure failure (e.g. permissions): report it, keep
            # the stored data untouched, and run an empty session.
            return {"chats": [], "current": []}, [f"Chat history unavailable ({e})"]
        if corrupt:
            warnings.append("Chat history was corrupted; a backup copy was kept and history was reset.")
        if not isinstance(data, dict):
            return {"chats": [], "current": []}, warnings
        chats: List[Dict[str, Any]] = []
        raw = data.get("chats", [])
        if isinstance(raw, list):
            for c in raw[:MAX_STORED_CHATS]:
                record = _clean_chat_record(c)
                if record is not None:
                    chats.append(record)
        return {"chats": chats, "current": clean_messages(data.get("current", []))}, warnings

    def save_chats(self, chats: Any, current: Any) -> None:
        """Persist chats + open conversation. Raises StorageError on failure."""
        stored: List[Dict[str, Any]] = []
        if isinstance(chats, list):
            for c in chats[:MAX_STORED_CHATS]:
                record = _clean_chat_record(c)
                if record is not None:
                    stored.append(record)
        _write_json(self.chats_path, {"chats": stored, "current": clean_messages(current)})

    # -- memory notes ------------------------------------------
    def load_notes(self) -> str:
        try:
            with open(self.memory_path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return ""
        except PermissionError as e:
            raise StorageError(f"Cannot read memory notes: permission denied.") from e
        except OSError as e:
            raise StorageError(f"Cannot read memory notes: storage failure ({e}).") from e

    def save_notes(self, text: str) -> None:
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = _tmp_path(self.memory_path)
        try:
            with path_lock(self.memory_path):
                with open(tmp_path, "w", encoding="utf-8") as f:
                    f.write(text)
                atomic_replace(tmp_path, self.memory_path)
        except OSError as e:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            raise StorageError(f"Could not save memory notes: {e}") from e

    # -- structured memory --------------------------------------
    def load_structured(self) -> Tuple[Dict[str, Any], List[str]]:
        """Return (memory dict, warnings) with guaranteed default keys."""
        try:
            data, corrupt = _read_json(self.structured_path)
        except StorageError as e:
            return (
                {"preferences": {}, "facts": [], "past_tasks": [], "user_name": None},
                [f"Structured memory unavailable ({e})"],
            )
        warnings = (
            ["Structured memory was corrupted; a backup copy was kept."] if corrupt else []
        )
        blank: Dict[str, Any] = {"preferences": {}, "facts": [], "past_tasks": [], "user_name": None}
        if not isinstance(data, dict):
            return blank, warnings
        for key, default in blank.items():
            data.setdefault(key, default)
        if not isinstance(data.get("facts"), list):
            data["facts"] = []
        return data, warnings

    def save_structured(self, mem: Dict[str, Any]) -> None:
        if not isinstance(mem, dict):
            raise StorageError("Refusing to save non-dict structured memory.")
        _write_json(self.structured_path, mem)

    # -- legacy migration ----------------------------------------
    def migrate_legacy(self) -> bool:
        """One-time import from pre-isolation global files. Returns True if moved."""
        if self.chats_path.exists() or self.memory_path.exists() or self.structured_path.exists():
            return False
        moved = False
        legacy_chats = Path("memory") / "chats.json"
        if legacy_chats.exists():
            try:
                data, _ = _read_json(legacy_chats)
            except StorageError:
                data = None
            if isinstance(data, dict) and (data.get("chats") or data.get("current")):
                try:
                    self.save_chats(data.get("chats", []), data.get("current", []))
                    moved = True
                except StorageError:
                    pass
        legacy_notes = Path("memory") / "memory.md"
        if legacy_notes.exists():
            try:
                self.save_notes(legacy_notes.read_text(encoding="utf-8"))
                moved = True
            except OSError:
                pass
        legacy_structured = Path("structured_memory.json")
        if legacy_structured.exists():
            try:
                data, _ = _read_json(legacy_structured)
            except StorageError:
                data = None
            if isinstance(data, dict) and data:
                try:
                    self.save_structured(data)
                    moved = True
                except StorageError:
                    pass
        return moved
