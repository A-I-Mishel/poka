"""Per-user code workspace: isolated file area for coding tasks.

Layout per user:
    data/users/<safe-id>/workspace/<relpath>

Unlike uploads/ (opaque IDs, staged reads) the workspace is a real
small filesystem the model can list/read/write/delete via tools, and
run_code executes inside it. Every path is validated as a relative
path and containment-checked after resolve() — absolute paths,
drive letters, `..`, symlinks escaping the root are all rejected.

Quotas (services.limits) are checked BEFORE writes.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List

from services.limits import (
    MAX_WORKSPACE_BYTES,
    MAX_WORKSPACE_FILE_BYTES,
    MAX_WORKSPACE_FILES,
    MAX_WORKSPACE_PATH_CHARS,
    MAX_WORKSPACE_READ_CHARS,
    MAX_WORKSPACE_WRITE_CHARS,
)
from services.storage import StorageError, atomic_replace, path_lock, user_dir

WORKSPACE_DIRNAME = "workspace"

_WINDOWS_RESERVED = frozenset(
    ["NUL", "CON", "PRN", "AUX", "COM1", "COM2", "COM3", "COM4", "COM5",
     "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4",
     "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"]
)

_PART_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\- ]{0,99}$")

# Code + text files the workspace accepts. Binaries, archives and
# office docs stay in uploads/outputs — the workspace is for source.
WORKSPACE_ALLOWED_EXTS = frozenset({
    "py", "pyi", "js", "mjs", "cjs", "jsx", "ts", "mts", "tsx",
    "json", "txt", "md", "markdown", "html", "htm", "css",
    "sql", "sh", "java", "c", "h", "cpp", "hpp", "cc",
    "cs", "go", "rs", "php", "rb", "swift", "kt", "kts",
    "toml", "yaml", "yml", "ini", "cfg", "conf", "xml", "vue",
})


def workspace_root(user_id: str, create: bool = False) -> Path:
    """Resolve the user's workspace root, optionally creating it."""
    base = user_dir(user_id, create=True)
    root = base / WORKSPACE_DIRNAME
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def clean_relpath(raw: Any) -> str:
    """Validate a workspace-relative path. Returns normalized posix path.

    Raises StorageError on absolute paths, drive letters, traversal,
    hidden parts, reserved names, bad characters, depth or length abuse.
    """
    text = str(raw or "").replace("\x00", "").strip().replace("\\", "/").strip()
    if not text:
        raise StorageError("Workspace path must not be empty.")
    if len(text) > MAX_WORKSPACE_PATH_CHARS:
        raise StorageError(
            f"Workspace path too long (limit {MAX_WORKSPACE_PATH_CHARS})."
        )
    if text.startswith("/") or text.startswith("~"):
        raise StorageError("Workspace path must be relative, not absolute.")
    if re.match(r"^[A-Za-z]:", text):
        raise StorageError("Workspace path must not contain a drive letter.")
    parts = [p for p in text.split("/") if p not in ("", ".")]
    if not parts or len(parts) > 8:
        raise StorageError("Workspace path is empty or too deep (max 8 levels).")
    for part in parts:
        if part in ("..", "", "."):
            raise StorageError("Workspace path must not contain '..'.")
        if part.startswith("."):
            raise StorageError("Hidden files/dirs are not allowed in the workspace.")
        if len(part) > 100:
            raise StorageError("Workspace path segment too long.")
        stem = part.split(".", 1)[0].upper()
        if stem in _WINDOWS_RESERVED:
            raise StorageError(f"Reserved filename {part!r} is not allowed.")
        if not _PART_RE.match(part):
            raise StorageError(
                f"Unsafe path segment {part!r}: use letters, digits, _ . - and spaces."
            )
    return "/".join(parts)


def resolve_in_workspace(user_id: str, relpath: str) -> Path:
    """Resolve a validated relpath to a contained absolute path.

    Never raises for missing files — returns the canonical resolved path
    after containment check. Symlinks are denied (TOCTOU escape).
    Raises StorageError on escape.
    """
    cleaned = clean_relpath(relpath)
    root = workspace_root(user_id, create=False)
    candidate = root / Path(*cleaned.split("/"))
    try:
        resolved = candidate.resolve()
        base = root.resolve()
    except OSError as e:
        raise StorageError(f"Cannot resolve workspace path ({e}).") from e
    # Root may not exist yet: resolve() on missing leaf still gives a
    # path under base; compare string-wise when base is missing.
    try:
        base_resolved = base
        if not base.exists():
            base_resolved = Path(os.path.abspath(str(root)))
            resolved_cmp = Path(os.path.abspath(str(candidate)))
            if resolved_cmp != base_resolved and base_resolved not in resolved_cmp.parents:
                raise StorageError("Workspace path escapes the workspace.")
            return resolved_cmp
    except StorageError:
        raise
    except Exception as e:
        raise StorageError(f"Cannot resolve workspace path ({e}).") from e
    if resolved != base_resolved and base_resolved not in resolved.parents:
        raise StorageError("Workspace path escapes the workspace.")
    # Deny symlinks (TOCTOU): validated path must not traverse a link.
    try:
        cur = candidate
        for _ in range(10):
            try:
                if cur.is_symlink():
                    raise StorageError("Symlinks are not allowed in the workspace.")
            except OSError:
                break
            if cur == root or cur.parent == cur:
                break
            cur = cur.parent
    except StorageError:
        raise
    except OSError:
        pass
    return resolved


def _workspace_usage(root: Path) -> tuple[int, int]:
    """Return (file_count, total_bytes) for the workspace tree."""
    count = 0
    total = 0
    if not root.exists():
        return 0, 0
    for p in root.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                count += 1
                total += p.stat().st_size
        except OSError:
            continue
    return count, total


def list_workspace(user_id: str) -> List[Dict[str, Any]]:
    """List workspace files (relative posix paths, newest first not needed)."""
    root = workspace_root(user_id, create=False)
    out: List[Dict[str, Any]] = []
    if not root.exists():
        return out
    for p in sorted(root.rglob("*")):
        try:
            if not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            try:
                st = p.stat()
            except OSError:
                continue
            out.append({"path": rel, "size": int(st.st_size),
                        "modified": float(st.st_mtime)})
        except (OSError, ValueError):
            continue
        if len(out) >= MAX_WORKSPACE_FILES:
            break
    return out


def read_workspace_file(user_id: str, relpath: str) -> str:
    """Read a workspace text file, capped. Raises StorageError/FileNotFoundError."""
    path = resolve_in_workspace(user_id, relpath)
    try:
        if not path.is_file():
            raise FileNotFoundError(f"Workspace file not found: {clean_relpath(relpath)}")
        if path.stat().st_size > MAX_WORKSPACE_FILE_BYTES:
            raise StorageError(
                f"File too large to read (limit {MAX_WORKSPACE_FILE_BYTES} bytes)."
            )
        raw = path.read_bytes()
    except FileNotFoundError:
        raise
    except StorageError:
        raise
    except OSError as e:
        raise StorageError(f"Cannot read workspace file ({e}).") from e
    if b"\x00" in raw[:8192]:
        raise StorageError("Binary files cannot be read as workspace text.")
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    if len(text) > MAX_WORKSPACE_READ_CHARS:
        text = text[:MAX_WORKSPACE_READ_CHARS] + "\n[Note: file truncated to workspace read cap.]"
    return text


def write_workspace_file(user_id: str, relpath: str, content: str) -> Dict[str, Any]:
    """Write (create/overwrite) a workspace text file atomically.

    Validates extension, size and quotas BEFORE writing. Returns
    {"path": rel, "size": bytes}.
    """
    cleaned = clean_relpath(relpath)
    text = str(content or "")
    if len(text) > MAX_WORKSPACE_WRITE_CHARS:
        raise StorageError(
            f"Content too large (limit {MAX_WORKSPACE_WRITE_CHARS} chars)."
        )
    ext = cleaned.rsplit(".", 1)[-1].lower() if "." in cleaned else ""
    if ext not in WORKSPACE_ALLOWED_EXTS:
        allowed = ", ".join(sorted(WORKSPACE_ALLOWED_EXTS))
        raise StorageError(f"Unsupported workspace type .{ext or '?'}. Allowed: {allowed}.")
    data = text.encode("utf-8")
    if len(data) > MAX_WORKSPACE_FILE_BYTES:
        raise StorageError(
            f"File too large (limit {MAX_WORKSPACE_FILE_BYTES} bytes)."
        )
    root = workspace_root(user_id, create=True)
    dest = resolve_in_workspace(user_id, cleaned)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f"{dest.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with path_lock(dest):
            # Re-check quotas INSIDE the lock (TOCTOU: concurrent writes
            # could otherwise exceed caps between check and write).
            count, total = _workspace_usage(root)
            try:
                existing = dest.stat().st_size if dest.is_file() else 0
            except OSError:
                existing = 0
            is_new = not dest.exists()
            if is_new and count >= MAX_WORKSPACE_FILES:
                raise StorageError(
                    f"Too many workspace files (max {MAX_WORKSPACE_FILES}). Delete one first."
                )
            if total - existing + len(data) > MAX_WORKSPACE_BYTES:
                raise StorageError("Workspace quota exceeded. Delete old files first.")
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            atomic_replace(tmp, dest)
    except StorageError:
        raise
    except OSError as e:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise StorageError(f"Could not write workspace file ({e}).") from e
    return {"path": cleaned, "size": len(data)}


def delete_workspace_file(user_id: str, relpath: str) -> bool:
    """Delete one workspace file. Returns False when missing."""
    path = resolve_in_workspace(user_id, relpath)
    try:
        if not path.is_file():
            return False
        with path_lock(path):
            path.unlink()
        # Prune newly-empty parent dirs up to the root (never the root).
        root = workspace_root(user_id, create=False)
        parent = path.parent
        while parent != root and root in parent.parents:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
        return True
    except OSError:
        return False
