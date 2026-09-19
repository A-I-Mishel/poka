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
import logging
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

logger = logging.getLogger(__name__)

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


def sanitize_download_filename(name: Any, fallback: str = "file") -> str:
    """Sanitize a name for Content-Disposition (RFC 6266/5987).

    Strips NUL/controls, quotes, semicolons, path separators, and
    truncates (preserving the extension) — defense-in-depth even though
    display names were sanitized at write time (legacy rows bypass).
    """
    tmp = str(name or fallback).replace("\x00", "").replace("\\", "_").replace("/", "_")
    tmp = re.sub(r'[\x00-\x1f\x7f]', '', tmp)
    tmp = tmp.replace('"', '').replace(";", "_").replace("\r", "").replace("\n", "").strip(" .")
    if not tmp:
        tmp = fallback
    if len(tmp) > MAX_FILENAME_LEN:
        if "." in tmp:
            base, ext = tmp.rsplit(".", 1)
            ext = ext[:10]
            tmp = base[: MAX_FILENAME_LEN - len(ext) - 1] + "." + ext
        else:
            tmp = tmp[:MAX_FILENAME_LEN]
    return tmp


def kind_for_ext(ext: str) -> str:
    """Map a validated extension to an attachment kind."""
    if ext == "pdf":
        return "pdf"
    if ext in ("csv", "tsv"):
        return "csv"
    if ext in ("png", "jpg", "jpeg", "webp", "gif", "bmp"):
        return "image"
    return "document"


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
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if head.startswith(b"BM"):
        return "bmp"
    if head.startswith(b"RIFF") and b"WEBP" in head[:16]:
        return "webp"
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        # OLE2 compound (legacy .doc/.ppt/.xls share this magic).
        # Readers share a strings fallback, so "doc" is a safe generic.
        return "doc"
    if head.lstrip().lower().startswith(b"{\\rtf"):
        return "rtf"
    return None


def _sniff_zip_kind(data: bytes) -> str:
    """Distinguish office/odf from generic zip via central-directory names.

    All of docx/pptx/xlsx/odt/ods/odp/zip start with PK\\x03\\x04, so
    magic bytes alone cannot tell them apart. Inspecting the member
    list (bounded, header-only — no extraction) identifies office
    documents confidently; anything else stays a generic "zip".
    Never raises: unreadable archives report "zip" and fail later
    at the validity check with a user-safe message.
    """
    try:
        import io
        import zipfile

        with zipfile.ZipFile(io.BytesIO(data)) as z:
            try:
                names = set(z.namelist()[:400])
            except Exception:
                return "zip"
            if "word/document.xml" in names:
                return "docx"
            if "ppt/presentation.xml" in names:
                return "pptx"
            if "xl/workbook.xml" in names:
                return "xlsx"
            if "content.xml" in names:
                try:
                    mime = z.read("mimetype", pwd=None)[:120].decode(
                        "ascii", errors="ignore").strip().lower()
                except Exception:
                    mime = ""
                if "spreadsheet" in mime or "ods" in mime:
                    return "ods"
                if "presentation" in mime or "odp" in mime:
                    return "odp"
                return "odt"
            return "zip"
    except Exception:
        return "zip"


_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

_ZIP_BASED_EXTS = frozenset({
    "docx", "pptx", "xlsx", "odt", "ods", "odp", "zip",
})


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
        # Free-tier durability: queue an R2 snapshot (no-op when
        # unconfigured; never raises into the write path).
        try:
            from services.snapshots import notify as _snapshots_notify

            _snapshots_notify()
        except Exception:
            logger.debug("snapshot notify failed", exc_info=True)
    except OSError:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            logger.debug("tmp cleanup failed", exc_info=True)
        raise


def _check_disk_space(needed_bytes: int) -> None:
    """Raise FileValidationError if host disk has < needed + 100 MB free.

    Checks the filesystem backing the data root (PLUTO_DATA_DIR or ./data).
    Best-effort: if stat fails, allow the write (fail at actual write instead
    of blocking uploads due to transient OS error).
    """
    try:
        import shutil

        from services.storage import data_root

        root = data_root()
        # ensure parent exists for disk_usage check
        try:
            root.mkdir(parents=True, exist_ok=True)
        except Exception:
            logger.debug("data root mkdir failed", exc_info=True)
        usage = shutil.disk_usage(str(root))
        # keep 100 MB headroom so OS / other users aren't starved
        headroom = 100 * 1024 * 1024
        if usage.free < needed_bytes + headroom:
            raise FileValidationError(
                "Server storage is full. Delete old files or try again later."
            )
    except FileValidationError:
        raise
    except Exception:
        logger.debug("disk space check failed; allowing write", exc_info=True)
        pass


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


class FileStore:
    """Upload + output vault owned by one user ID."""

    def __init__(self, user_id: str) -> None:
        self.user_id: str = user_id
        self.root: Path = user_dir(user_id, create=False)
        self.uploads_dir: Path = self.root / "uploads"
        self.outputs_dir: Path = self.root / "outputs"
        self.uploads_registry: Path = self.root / "uploads.json"
        self.outputs_registry: Path = self.root / "outputs.json"

    def _ensure_dirs(self) -> None:
        """Create the vault directories on first actual write.

        Construction must stay side-effect free: stores are built on
        every request (including read-only ones), and ephemeral
        open-mode visitors must not litter the disk.
        """
        self.root.mkdir(parents=True, exist_ok=True)
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
                stamp = "%d-%s" % (int(time.time() * 1000), uuid.uuid4().hex[:8])
                backup = path.with_name(f"{path.stem}.corrupt-{stamp}{path.suffix}")
                with path_lock(path):
                    if path.exists():
                        os.replace(path, backup)
            except OSError:
                pass
            obs_event("storage.quarantine", file=path.name)
            return {}

    def _update_registry(self, path: Path, mutate: Any) -> None:
        """Atomically read-modify-write a registry under one lock hold."""
        self._ensure_dirs()
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
                    stamp = "%d-%s" % (int(time.time() * 1000), uuid.uuid4().hex[:8])
                    backup = path.with_name(
                        f"{path.stem}.corrupt-{stamp}{path.suffix}"
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
        _sniffed = _sniff_ext(bytes(data[:16]))
        if ext not in ALLOWED_UPLOAD_EXTS:
            # Missing or wrong extension (e.g. extensionless downloads):
            # fall back to magic bytes, then to zip-kind inspection
            # (PK magic covers zip/office/odf — indistinguishable at
            # 16 bytes) before rejecting.
            ext = _sniffed or ""
            if not ext and bytes(data[:4]) == b"PK\x03\x04":
                ext = _sniff_zip_kind(bytes(data))
        elif _sniffed and _sniffed != ext:
            # Content says otherwise (e.g. .txt holding a PDF): trust the
            # magic bytes over the filename so misnamed files still read.
            ext = _sniffed
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
        if ext == "gif" and not head.startswith((b"GIF87a", b"GIF89a")):
            raise FileValidationError("That file is not a valid GIF image.")
        if ext == "bmp" and not head.startswith(b"BM"):
            raise FileValidationError("That file is not a valid BMP image.")
        if ext == "webp" and not (
            head.startswith(b"RIFF") and b"WEBP" in bytes(data[:32])
        ):
            raise FileValidationError("That file is not a valid WEBP image.")
        if ext in ("csv", "tsv") and b"\x00" in bytes(data[:8192]):
            raise FileValidationError("That file does not look like a CSV.")
        # Any other non-binary upload (txt/md/html/xml/rtf/code/...)
        # must be plain text: reject NUL bytes which signal binary
        # masquerade. Binary types below carry their own magic-byte
        # checks, so everything else here is expected to decode as text.
        _BINARY_EXTS = frozenset({
            "pdf", "png", "jpg", "jpeg", "gif", "bmp", "webp",
            "docx", "pptx", "xlsx", "odt", "ods", "odp", "zip",
            "doc", "ppt", "xls",
        })
        if ext not in _BINARY_EXTS and ext not in ("csv", "tsv") \
                and b"\x00" in bytes(data[:8192]):
            raise FileValidationError("That file does not look like a text document.")
        if ext in ("docx", "pptx", "xlsx", "odt", "ods", "odp", "zip") \
                and not head.startswith(b"PK\x03\x04"):
            raise FileValidationError(f"That file is not a valid .{ext} (ZIP-based).")
        if ext in ("doc", "ppt", "xls") and not head.startswith(_OLE_MAGIC):
            raise FileValidationError(f"That file is not a valid .{ext} (OLE compound).")
        if ext == "rtf" and not head.lstrip().lower().startswith(b"{\\rtf"):
            raise FileValidationError("That file is not a valid RTF document.")
        if ext in ("zip", "odt", "ods", "odp"):
            # Validity + bomb pre-check BEFORE storage: malformed
            # archives fail here, oversized ones also fail early.
            try:
                import io
                import zipfile

                from services.limits import (
                    MAX_ZIP_FILE_BYTES,
                    MAX_ZIP_FILES,
                    MAX_ZIP_UNCOMPRESSED_BYTES,
                )

                with zipfile.ZipFile(io.BytesIO(bytes(data))) as _z:
                    _infos = _z.infolist()
                    if len(_infos) > MAX_ZIP_FILES:
                        raise FileValidationError(
                            "That archive lists too many files to read safely "
                            f"(max {MAX_ZIP_FILES}).")
                    total = 0
                    for _info in _infos:
                        try:
                            sz = int(getattr(_info, "file_size", 0) or 0)
                        except Exception:
                            sz = 0
                        if sz > MAX_ZIP_FILE_BYTES:
                            raise FileValidationError(
                                "That archive contains a file too large to read safely.")
                        total += max(0, sz)
                        if total > MAX_ZIP_UNCOMPRESSED_BYTES:
                            raise FileValidationError(
                                "That archive is too large to read safely.")
            except FileValidationError:
                raise
            except Exception:
                raise FileValidationError(f"That file is not a valid .{ext} archive.")
        return ext

    def save_upload(self, data: bytes, original_name: str) -> UploadMeta:
        """Validate, store, and register an upload. Returns its metadata."""
        ext = self.validate_upload(data, original_name)
        # Disk-space guard BEFORE quotas — host full takes precedence
        _check_disk_space(len(data))
        display = sanitize_filename(original_name)
        upload_id = _new_id()
        stored = f"{upload_id}_{sanitize_filename(display)}"
        dest = self.uploads_dir / stored
        if not self._inside(self.uploads_dir, dest):
            raise FileValidationError("Unsafe filename rejected.")
        self._ensure_dirs()
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
        # Quotas and registry update atomically under the registry lock.
        # This prevents TOCTOU race where concurrent uploads could exceed
        # quotas between the check and the registry write.
        def _add_upload(registry: Dict[str, Any]) -> None:
            existing = list(registry.values())
            if len(existing) >= MAX_UPLOADS_PER_USER:
                raise FileValidationError(
                    f"Too many stored uploads (max {MAX_UPLOADS_PER_USER}). "
                    "Delete old files or wait for retention cleanup."
                )
            used = sum(m.get("size", 0) for m in existing)
            if used + len(data) > MAX_USER_BYTES:
                raise FileValidationError(
                    "Storage quota exceeded. Delete old files or wait for "
                    "retention cleanup."
                )
            registry[upload_id] = asdict(meta)

        self._update_registry(self.uploads_registry, _add_upload)
        # Invalidate store caches for this user
        from backend.deps import invalidate_store_caches
        invalidate_store_caches(self.user_id)
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
        _check_disk_space(len(data))
        display = sanitize_filename(display_name)
        file_id = _new_id()
        stored = f"{file_id}_{display}"
        dest = self.outputs_dir / stored
        if not self._inside(self.outputs_dir, dest):
            raise StorageError("Unsafe output filename rejected.")
        self._ensure_dirs()
        try:
            _atomic_write_bytes(dest, bytes(data))
        except OSError as e:
            raise StorageError(f"Could not store generated file: {e}") from e
        meta = OutputMeta(
            id=file_id,
            display_name=display,
            stored_name=stored,
            kind=kind if kind in ("pptx", "docx", "pdf", "md", "doc", "html") else "file",
            size=len(data),
            created=time.time(),
            spec=clean_generation_spec(spec),
        )
        def _add_output(registry: Dict[str, Any]) -> None:
            registry[file_id] = asdict(meta)

        self._update_registry(self.outputs_registry, _add_output)
        # Invalidate store caches for this user
        from backend.deps import invalidate_store_caches
        invalidate_store_caches(self.user_id)
        return meta

    def _drop_output_record(self, file_id: str) -> None:
        def _drop(registry: Dict[str, Any]) -> None:
            registry.pop(file_id, None)

        self._update_registry(self.outputs_registry, _drop)

    def _drop_upload_record(self, upload_id: str) -> None:
        def _drop(registry: Dict[str, Any]) -> None:
            registry.pop(upload_id, None)

        self._update_registry(self.uploads_registry, _drop)

    def delete_upload(self, upload_id: Any) -> bool:
        """Delete one owned upload file + registry record.

        Explicit user intent wins over retention: even chat-referenced
        uploads are removed (old message chips then 404 gracefully;
        regenerating those turns fails loudly, never silently).
        Returns False when unknown/unowned (never raises for that).
        """
        meta = self.get_upload(upload_id)
        if meta is None:
            return False
        candidate = self.uploads_dir / meta.stored_name
        if self._inside(self.uploads_dir, candidate):
            try:
                if candidate.is_file():
                    candidate.unlink()
            except OSError:
                return False
        try:
            self._drop_upload_record(meta.id)
        except StorageError:
            return False
        # Invalidate store caches for this user
        from backend.deps import invalidate_store_caches
        invalidate_store_caches(self.user_id)
        return True

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
        # Invalidate store caches for this user
        from backend.deps import invalidate_store_caches
        invalidate_store_caches(self.user_id)
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

    def prune_orphan_files(self, max_age_days: int = 7) -> int:
        """Delete orphan files (on disk without registry entry) older than cutoff.

        Returns count removed. Recent orphans (< max_age_days) are kept
        because they may be in-flight writes. Tmp files are also swept
        here (conservative age check prevents racing a concurrent writer).
        """
        cutoff = time.time() - max_age_days * 86400.0
        removed = 0
        for directory, registry_path, model in (
            (self.uploads_dir, self.uploads_registry, UploadMeta),
            (self.outputs_dir, self.outputs_registry, OutputMeta),
        ):
            registry = self._load_registry(registry_path)
            known = set()
            for rec in registry.values():
                if not isinstance(rec, dict):
                    continue
                try:
                    meta = model(**{k: rec[k] for k in model.__dataclass_fields__})
                    known.add(meta.stored_name)
                except Exception:
                    logger.debug("registry record rebuild failed; skipping entry", exc_info=True)
                    continue
            try:
                on_disk = list(directory.iterdir())
            except OSError:
                continue
            for p in on_disk:
                if not p.is_file():
                    continue
                name = p.name
                if name in known:
                    continue
                # keep recent orphans; only delete old ones + always delete .tmp older than cutoff
                try:
                    mtime = p.stat().st_mtime
                except OSError:
                    continue
                if mtime >= cutoff and not name.endswith(".tmp"):
                    continue
                if not self._inside(directory, p):
                    continue
                try:
                    p.unlink()
                    removed += 1
                except OSError:
                    continue
        return removed
