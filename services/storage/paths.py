"""Vault path resolution (data root, per-user dirs, traversal guards)."""

import re
from pathlib import Path
from typing import Any

from services.storage.ids import StorageError


def data_root() -> Path:
    """Return the configured data root directory."""
    from services.secrets import get_secret

    return Path(get_secret("PLUTO_DATA_DIR", "data") or "data")


def sanitize_user_key(raw: Any) -> str:
    """Make a user ID safe for use as a single directory name."""
    text = str(raw or "").strip()
    if not text or ".." in text or "/" in text or "\\" in text:
        raise StorageError("Refusing to resolve storage for a path-like user ID.")
    text = re.sub(r"[^A-Za-z0-9_.-]", "_", text).strip(" .")
    if not text:
        raise StorageError("Refusing to resolve storage for an empty user ID.")
    return text[:64]


def user_dir(user_id: str, create: bool = True) -> Path:
    """Resolve a user's directory, rejecting any traversal outside users/.

    Directories are created only when `create` is true: stores resolve
    paths on every request but must not litter the disk for visitors
    who never persist anything (e.g. ephemeral open-mode identities).
    All write helpers ensure parents before writing; all reads tolerate
    missing files.
    """
    key = sanitize_user_key(user_id)
    base = (data_root() / "users").resolve()
    if create:
        base.mkdir(parents=True, exist_ok=True)
    else:
        base = data_root() / "users"
    candidate = (base / key).resolve()
    if candidate != base.resolve() and base.resolve() not in candidate.parents:
        raise StorageError("User storage path escapes the users directory.")
    if create:
        candidate.mkdir(parents=True, exist_ok=True)
    return candidate
