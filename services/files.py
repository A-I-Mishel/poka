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
from typing import Any, Dict, List, Optional

from services.limits import ALLOWED_UPLOAD_EXTS, MAX_FILENAME_LEN, MAX_UPLOAD_BYTES, UPLOAD_ID_RE
from services.storage import StorageError, user_dir

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


def sanitize_filename(name: Any) -> str:
    """Strip directories/control chars; keep a safe basename or 'file'."""
    text = str(name or "").replace("\x00", "").strip()
    text = os.path.basename(text.replace("\\", "/")).strip()
    text = _SAFE_CHARS_RE.sub("_", text).strip(" .")
    if not text:
        return "file"
    return text[:MAX_FILENAME_LEN]


def kind_for_ext(ext: str) -> str:
    """Map a validated extension to an attachment kind."""
    if ext == "pdf":
        return "pdf"
    if ext == "csv":
        return "csv"
    return "image"


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
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            try:
                backup = path.with_name(f"{path.stem}.corrupt-{int(time.time())}{path.suffix}")
                os.replace(path, backup)
            except OSError:
                pass
            return {}

    def _save_registry(self, path: Path, payload: Dict[str, Any]) -> None:
        tmp_path = path.with_name(path.name + ".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp_path, path)
        except OSError as e:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
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
        display = sanitize_filename(original_name)
        upload_id = _new_id()
        stored = f"{upload_id}_{sanitize_filename(display)}"
        dest = self.uploads_dir / stored
        if not self._inside(self.uploads_dir, dest):
            raise FileValidationError("Unsafe filename rejected.")
        try:
            with open(dest, "wb") as f:
                f.write(data)
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
        registry = self._load_registry(self.uploads_registry)
        registry[upload_id] = asdict(meta)
        self._save_registry(self.uploads_registry, registry)
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

    # -- outputs ---------------------------------------------------
    def register_output(self, display_name: str, data: bytes, kind: str) -> OutputMeta:
        """Store generated bytes and register ownership metadata."""
        if not isinstance(data, (bytes, bytearray)) or len(data) == 0:
            raise StorageError("Refusing to register an empty generated file.")
        display = sanitize_filename(display_name)
        file_id = _new_id()
        stored = f"{file_id}_{display}"
        dest = self.outputs_dir / stored
        if not self._inside(self.outputs_dir, dest):
            raise StorageError("Unsafe output filename rejected.")
        try:
            with open(dest, "wb") as f:
                f.write(data)
        except OSError as e:
            raise StorageError(f"Could not store generated file: {e}") from e
        meta = OutputMeta(
            id=file_id,
            display_name=display,
            stored_name=stored,
            kind=kind if kind in ("pptx", "docx") else "file",
            size=len(data),
            created=time.time(),
        )
        registry = self._load_registry(self.outputs_registry)
        registry[file_id] = asdict(meta)
        self._save_registry(self.outputs_registry, registry)
        return meta

    def list_outputs(self) -> List[OutputMeta]:
        """List this user's outputs, newest first."""
        registry = self._load_registry(self.outputs_registry)
        metas: List[OutputMeta] = []
        for record in registry.values():
            if not isinstance(record, dict):
                continue
            try:
                metas.append(
                    OutputMeta(**{k: record[k] for k in OutputMeta.__dataclass_fields__})
                )
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
            return OutputMeta(**{k: record[k] for k in OutputMeta.__dataclass_fields__})
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
        registry = self._load_registry(self.outputs_registry)
        registry.pop(meta.id, None)
        try:
            self._save_registry(self.outputs_registry, registry)
        except StorageError:
            return False
        return True

    def delete_all_outputs(self) -> int:
        """Delete every output owned by this user. Returns count removed."""
        count = 0
        for meta in self.list_outputs():
            if self.delete_output(meta.id):
                count += 1
        return count
