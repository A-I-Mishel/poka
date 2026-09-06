"""Per-user file vault: uploads in, generated outputs out.

Layout per user:
    data/users/<safe-id>/uploads/<upload-id>_<safe-name>
    data/users/<safe-id>/uploads.json          (upload registry)
    data/users/<safe-id>/outputs/<file-id>_<safe-name>
    data/users/<safe-id>/outputs.json          (output registry)

Original filenames are display metadata only — storage names are always
generated. Every resolution re-validates ownership and containment.
"""

import json
import mimetypes
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Collection, Dict, List, Optional

from services.limits import (
    ALLOWED_UPLOAD_EXTS,
    MAX_FILENAME_LEN,
    MAX_OUTPUT_AGE_DAYS,
    MAX_UPLOAD_BYTES,
    MAX_UPLOADS_PER_USER,
    MAX_USER_BYTES,
    UPLOAD_ID_RE,
)
from services.obs import event as obs_event
from services.storage import (
    StorageError,
    atomic_replace,
    clean_generation_spec,
    path_lock,
    user_dir,
)

_ID_RE = re.compile(UPLOAD_ID_RE)
_SAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9._-]+")


class FileValidationError(Exception):
    """Raised when an upload fails validation. Message is user-safe."""


@dataclass(frozen=True)
class UploadMeta:
    """Registry record for one staged upload."""

    id: str
    display_name: str
    stored_name: str
    kind: str
    ext: str
    mime: str
    size: int
    created: float


@dataclass(frozen=True)
class OutputMeta:
    """Registry record for one generated file."""

    id: str
    display_name: str
    stored_name: str
    kind: str
    size: int
    created: float
    spec: Optional[Dict[str, Any]] = None


_WINDOWS_RESERVED = frozenset(
    ["NUL", "CON", "PRN", "AUX"]
    + [f"COM{i}" for i in range(1, 10)]
    + [f"LPT{i}" for i in range(1, 10)]
)


def sanitize_filename(name: Any) -> str:
    """Strip directories/control chars; keep a safe basename or 'file'."""
    text = str(name or "").replace("\x00", "").strip()
    text = os.path.basename(text.replace("\\", "/")).strip()
    text = _SAFE_CHARS_RE.sub("_", text).strip(" .")
    if not text:
        return "file"
    stem = text.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED:
        text = f"_{text}"
    return text[:MAX_FILENAME_LEN]


def kind_for_ext(ext: str) -> str:
    """Map a validated extension to an attachment kind."""
    if ext == "pdf":
        return "pdf"
    if ext == "csv":
        return "csv"
    return "image"


def _sniff_ext(head: bytes) -> Optional[str]:
    """Detect a type from magic bytes when the filename has none/wrong one.

    Same signatures the validator already enforces below, so a
    sniffed type always passes the subsequent content check.
    Returns None when the bytes match no allowed type.
    """
    if head.lstrip().startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    return None


def _atomic_write_bytes(dest: Path, data: bytes) -> None:
    """Write bytes atomically: unique tmp in the same dir, fsync, replace.

    Readers never observe a partially written artifact. The tmp name is
    unique per process+call so concurrent writers cannot collide; it
    lives beside the destination so os.replace() stays atomic (same
    filesystem). Tmp leftovers are removed on failure (and swept by
    FileStore.reconcile() after a crash).
    """
    token = f"{os.getpid()}.{uuid.uuid4().hex[:8]}"
    tmp = dest.with_name(f"{dest.name}.{token}.tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        atomic_replace(tmp, dest)
    except OSError:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


class FileStore:
    """Upload + output vault owned by one user ID."""

    def __init__(self, user_id: str) -> None:
        self.user_id: str = user_id
        self.root: Path = user_dir(user_id)
        self.uploads_dir: Path = self.root / "uploads"
        self.outputs_dir: Path = self.root / "outputs"
        self.uploads_registry: Path = self.root / "uploads.json"
        self.outputs_registry: Path = self.root / "outputs.json"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)

    # -- internals ----------------------------------------------
    def _inside(self, base: Path, candidate: Path) -> bool:
        try:
            resolved = candidate.resolve()
        except OSError:
            return False
        return resolved == base.resolve() or base.resolve() in resolved.parents

    def _load_registry(self, path: Path) -> Dict[str, Any]:
        try:
            with path_lock(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
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
            return {}

    def _update_registry(self, path: Path, mutate: Any) -> None:
        """Atomically read-modify-write a registry under one lock hold."""
        with path_lock(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                registry = data if isinstance(data, dict) else {}
            except FileNotFoundError:
                registry = {}
            except PermissionError as e:
                raise StorageError(f"Cannot read {path.name}: permission denied.") from e
            except OSError as e:
                raise StorageError(f"Cannot read {path.name}: storage failure ({e}).") from e
            except ValueError:
                try:
                    backup = path.with_name(
                        f"{path.stem}.corrupt-{int(time.time())}{path.suffix}"
                    )
                    os.replace(path, backup)
                except OSError:
                    pass
                registry = {}
            mutate(registry)
            token = f"{os.getpid()}.{uuid.uuid4().hex[:8]}"
            tmp_path = path.with_name(f"{path.name}.{token}.tmp")
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(registry, f, ensure_ascii=False)
                atomic_replace(tmp_path, path)
            except OSError as e:
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                except OSError:
                    pass
                obs_event("storage.write", status="error", file=path.name)
                raise StorageError(f"Could not update file registry: {e}") from e

    # -- uploads --------------------------------------------------
    def validate_upload(self, data: bytes, filename: str) -> str:
        """Validate bytes + name. Returns the extension or raises."""
        if not isinstance(data, (bytes, bytearray)) or len(data) == 0:
            raise FileValidationError("Empty file. Please choose a non-empty file.")
        if len(data) > MAX_UPLOAD_BYTES:
            limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
            raise FileValidationError(f"File too large. Maximum is {limit_mb} MB.")
        safe = sanitize_filename(filename)
        ext = safe.rsplit(".", 1)[-1].lower() if "." in safe else ""
        if ext not in ALLOWED_UPLOAD_EXTS:
            # Missing or wrong extension (e.g. extensionless downloads):
            # fall back to magic bytes before rejecting.
            ext = _sniff_ext(bytes(data[:16])) or ""
        if ext not in ALLOWED_UPLOAD_EXTS:
            allowed = ", ".join(sorted(ALLOWED_UPLOAD_EXTS))
            raise FileValidationError(f"Unsupported file type. Allowed: {allowed}.")
        head = bytes(data[:16])
        if ext == "pdf" and not head.lstrip().startswith(b"%PDF"):
            raise FileValidationError("That file is not a valid PDF.")
        if ext == "png" and not head.startswith(b"\x89PNG\r\n\x1a\n"):
            raise FileValidationError("That file is not a valid PNG image.")
        if ext in ("jpg", "jpeg") and not head.startswith(b"\xff\xd8\xff"):
            raise FileValidationError("That file is not a valid JPEG image.")
        if ext == "csv" and b"\x00" in bytes(data[:8192]):
            raise FileValidationError("That file does not look like a CSV.")
        return ext

    def save_upload(self, data: bytes, original_name: str) -> UploadMeta:
        """Validate, store, and register an upload. Returns its metadata."""
        ext = self.validate_upload(data, original_name)
        # Quotas BEFORE any write: count and bytes across staged uploads.
        existing = self.list_uploads()
        if len(existing) >= MAX_UPLOADS_PER_USER:
            raise FileValidationError(
                f"Too many stored uploads (max {MAX_UPLOADS_PER_USER}). "
                "Delete old files or wait for retention cleanup."
            )
        used = sum(m.size for m in existing)
        if used + len(data) > MAX_USER_BYTES:
            raise FileValidationError(
                "Storage quota exceeded. Delete old files or wait for "
                "retention cleanup."
            )
        display = sanitize_filename(original_name)
        upload_id = _new_id()
        stored = f"{upload_id}_{sanitize_filename(display)}"
        dest = self.uploads_dir / stored
        if not self._inside(self.uploads_dir, dest):
            raise FileValidationError("Unsafe filename rejected.")
        try:
            _atomic_write_bytes(dest, bytes(data))
        except OSError as e:
            raise FileValidationError(f"Could not store upload: {e}") from e
        meta = UploadMeta(
            id=upload_id,
            display_name=display,
            stored_name=stored,
            kind=kind_for_ext(ext),
            ext=ext,
            mime=mimetypes.guess_type(display)[0] or "application/octet-stream",
            size=len(data),
            created=time.time(),
        )
        def _add_upload(registry: Dict[str, Any]) -> None:
            registry[upload_id] = asdict(meta)

        self._update_registry(self.uploads_registry, _add_upload)
        return meta

    def get_upload(self, upload_id: Any) -> Optional[UploadMeta]:
        """Return upload metadata owned by this user, else None."""
        if not isinstance(upload_id, str) or not _ID_RE.match(upload_id):
            return None
        registry = self._load_registry(self.uploads_registry)
        record = registry.get(upload_id)
        if not isinstance(record, dict):
            return None
        try:
            return UploadMeta(**{k: record[k] for k in UploadMeta.__dataclass_fields__})
        except (KeyError, TypeError):
            return None

    def resolve_upload(self, upload_id: Any) -> Optional[Path]:
        """Resolve an upload ID to a validated path, or None if unusable."""
        meta = self.get_upload(upload_id)
        if meta is None:
            return None
        candidate = self.uploads_dir / meta.stored_name
        if not self._inside(self.uploads_dir, candidate):
            return None
        if not candidate.is_file():
            return None
        return candidate

    def owns_path(self, value: Any) -> Optional[Path]:
        """Resolve a vault path previously handed out, if owned by this user.

        Accepts absolute or relative paths pointing inside this user's
        uploads directory. Returns the canonical path, else None (never
        raises). Centralizes the containment check so callers never
        reimplement path validation.
        """
        try:
            candidate = Path(str(value))
        except Exception:
            return None
        try:
            resolved = candidate.resolve()
            base = self.uploads_dir.resolve()
        except OSError:
            return None
        if resolved == base or base in resolved.parents:
            if resolved.is_file():
                return resolved
        return None

    # -- outputs ---------------------------------------------------
    def register_output(self, display_name: str, data: bytes, kind: str,
                        spec: Any = None) -> OutputMeta:
        """Store generated bytes and register ownership metadata.

        An optional generation spec (validated, never trusted blindly)
        is stored alongside for future regeneration; invalid specs are
        dropped without failing the registration.
        """
        if not isinstance(data, (bytes, bytearray)) or len(data) == 0:
            raise StorageError("Refusing to register an empty generated file.")
        display = sanitize_filename(display_name)
        file_id = _new_id()
        stored = f"{file_id}_{display}"
        dest = self.outputs_dir / stored
        if not self._inside(self.outputs_dir, dest):
            raise StorageError("Unsafe output filename rejected.")
        try:
            _atomic_write_bytes(dest, bytes(data))
        except OSError as e:
            raise StorageError(f"Could not store generated file: {e}") from e
        meta = OutputMeta(
            id=file_id,
            display_name=display,
            stored_name=stored,
            kind=kind if kind in ("pptx", "docx") else "file",
            size=len(data),
            created=time.time(),
            spec=clean_generation_spec(spec),
        )
        def _add_output(registry: Dict[str, Any]) -> None:
            registry[file_id] = asdict(meta)

        self._update_registry(self.outputs_registry, _add_output)
        return meta

    def _drop_output_record(self, file_id: str) -> None:
        def _drop(registry: Dict[str, Any]) -> None:
            registry.pop(file_id, None)

        self._update_registry(self.outputs_registry, _drop)

    def list_outputs(self) -> List[OutputMeta]:
        """List this user's outputs, newest first."""
        registry = self._load_registry(self.outputs_registry)
        metas: List[OutputMeta] = []
        for record in registry.values():
            if not isinstance(record, dict):
                continue
            try:
                kwargs = {k: record[k]
                          for k in OutputMeta.__dataclass_fields__ if k != "spec"}
                # Legacy records predate specs; stored specs re-validated.
                kwargs["spec"] = clean_generation_spec(record.get("spec"))
                metas.append(OutputMeta(**kwargs))
            except (KeyError, TypeError):
                continue
        metas.sort(key=lambda m: m.created, reverse=True)
        return metas

    def get_output(self, file_id: Any) -> Optional[OutputMeta]:
        """Return output metadata owned by this user, else None."""
        if not isinstance(file_id, str) or not _ID_RE.match(file_id):
            return None
        registry = self._load_registry(self.outputs_registry)
        record = registry.get(file_id)
        if not isinstance(record, dict):
            return None
        try:
            kwargs = {k: record[k]
                      for k in OutputMeta.__dataclass_fields__ if k != "spec"}
            kwargs["spec"] = clean_generation_spec(record.get("spec"))
            return OutputMeta(**kwargs)
        except (KeyError, TypeError):
            return None

    def read_output(self, file_id: Any) -> Optional[bytes]:
        """Read output bytes after ownership + containment checks."""
        meta = self.get_output(file_id)
        if meta is None:
            return None
        candidate = self.outputs_dir / meta.stored_name
        if not self._inside(self.outputs_dir, candidate):
            return None
        try:
            with open(candidate, "rb") as f:
                return f.read()
        except OSError:
            return None

    def delete_output(self, file_id: Any) -> bool:
        """Delete one owned output file + registry record."""
        meta = self.get_output(file_id)
        if meta is None:
            return False
        candidate = self.outputs_dir / meta.stored_name
        if self._inside(self.outputs_dir, candidate):
            try:
                if candidate.is_file():
                    candidate.unlink()
            except OSError:
                return False
        try:
            self._drop_output_record(meta.id)
        except StorageError:
            return False
        return True

    def list_uploads(self) -> List[UploadMeta]:
        """List this user's staged uploads, newest first."""
        registry = self._load_registry(self.uploads_registry)
        metas: List[UploadMeta] = []
        for record in registry.values():
            if not isinstance(record, dict):
                continue
            try:
                metas.append(
                    UploadMeta(**{k: record[k] for k in UploadMeta.__dataclass_fields__})
                )
            except (KeyError, TypeError):
                continue
        metas.sort(key=lambda m: m.created, reverse=True)
        return metas

    def delete_all_outputs(self) -> int:
        """Delete every output owned by this user. Returns count removed."""
        count = 0
        for meta in self.list_outputs():
            if self.delete_output(meta.id):
                count += 1
        return count

    def prune_stale_outputs(self, max_age_days: int = MAX_OUTPUT_AGE_DAYS) -> int:
        """Delete generated outputs older than max_age_days. Idempotent.

        Only this user's vault is touched (per-user registry). Running
        twice is safe: the second pass finds nothing to remove.
        """
        cutoff = time.time() - max_age_days * 86400.0
        removed = 0
        for meta in self.list_outputs():
            if meta.created >= cutoff:
                continue
            if self.delete_output(meta.id):
                removed += 1
        return removed

    def reconcile(self) -> Dict[str, List[str]]:
        """Report vault inconsistencies; remove only unambiguous leftovers.

        Returns a report with:
        - "missing_files": registry IDs whose physical file is gone.
        - "orphan_files": files on disk with no registry entry (kept, not
          deleted: they may be valid data from an interrupted write).
        - "bad_records": registry keys whose metadata is malformed.
        - "removed_tmp": crash-leftover "*.tmp" files that were deleted.

        Conservative by design: ambiguous cases are reported, never
        destroyed. Tmp files are the only safe auto-removal (a complete
        artifact is never stored under a .tmp name). Never touches other
        users (per-user vault throughout).
        """
        report: Dict[str, List[str]] = {
            "missing_files": [],
            "orphan_files": [],
            "bad_records": [],
            "removed_tmp": [],
        }
        pairs = (
            (self.uploads_dir, self.uploads_registry, UploadMeta),
            (self.outputs_dir, self.outputs_registry, OutputMeta),
        )
        for directory, registry_path, model in pairs:
            registry = self._load_registry(registry_path)
            known_names = set()
            for key, record in registry.items():
                try:
                    meta = model(**{k: record[k] for k in model.__dataclass_fields__})
                except (KeyError, TypeError, AttributeError):
                    report["bad_records"].append(str(key))
                    continue
                known_names.add(meta.stored_name)
                candidate = directory / meta.stored_name
                if not self._inside(directory, candidate) or not candidate.is_file():
                    report["missing_files"].append(str(key))
            try:
                on_disk = [p.name for p in directory.iterdir() if p.is_file()]
            except OSError:
                continue
            for name in sorted(on_disk):
                if name.endswith(".tmp"):
                    candidate = directory / name
                    if self._inside(directory, candidate):
                        try:
                            candidate.unlink()
                            report["removed_tmp"].append(name)
                        except OSError:
                            continue
                elif name not in known_names:
                    report["orphan_files"].append(name)
        return report

    def prune_stale_uploads(
        self, max_age_days: int = 7, referenced_ids: Collection[str] = ()
    ) -> int:
        """Delete old, unreferenced staged uploads. Returns count removed.

        Only uploads older than max_age_days AND absent from referenced_ids
        (upload IDs still cited by the user's chats) are removed. The
        per-user registry guarantees other users are never affected.
        """
        cutoff = time.time() - max_age_days * 86400.0
        referenced = set(referenced_ids or ())
        removed = 0
        for meta in self.list_uploads():
            if meta.id in referenced or meta.created >= cutoff:
                continue
            candidate = self.uploads_dir / meta.stored_name
            if self._inside(self.uploads_dir, candidate):
                try:
                    if candidate.is_file():
                        candidate.unlink()
                except OSError:
                    continue
            def _drop(registry: Dict[str, Any], _mid: str = meta.id) -> None:
                registry.pop(_mid, None)

            try:
                self._update_registry(self.uploads_registry, _drop)
                removed += 1
            except StorageError:
                continue
        return removed
