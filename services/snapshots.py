"""Free-tier durability: mirror the file data root to object storage.

Render's free tier (and any ephemeral host) wipes the local filesystem on
every redeploy/restart/spin-down, deleting data/accounts.json and
data/users/*/ — forcing every user to sign up again with empty history. A
persistent disk needs a paid instance, so on the free tier Pluto instead
mirrors the whole data root as one tar.gz archive in S3-compatible object
storage and restores it on boot when the local disk is empty.

Supported backends (any S3-compatible store):
    Cloudflare R2 (10 GB free, free egress; needs a card on file):
        R2_ACCOUNT_ID, R2_BUCKET, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY
    Supabase Storage (1 GB free, no card; enable the S3 protocol in the
    Storage settings, create a private bucket, generate S3 access keys):
        R2_BUCKET, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY,
        SNAPSHOT_ENDPOINT_URL=https://<ref>.storage.supabase.co/storage/v1/s3,
        SNAPSHOT_REGION=<project region from the S3 settings page>

Write path: services.storage._write_json and services.files
._atomic_write_bytes call notify() after every successful write. A
debounced daemon thread uploads at most once per
SNAPSHOT_INTERVAL_SECONDS and skips the upload when a fingerprint
(mtime+size walk) shows nothing changed.

Inactive when the backend vars are unset: notify()/flush()/maybe_restore()
are no-ops and no thread ever starts, so local dev and paid-disk deploys
behave exactly as before. Failures never raise to callers — a dead backend
must never block a chat save or server startup. Secret values are never
logged.

Env:
    R2_ACCOUNT_ID (only needed to build the default R2 endpoint),
    R2_BUCKET, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY,
    SNAPSHOT_ENDPOINT_URL (optional override for Supabase/B2/MinIO),
    SNAPSHOT_REGION (default auto; required by some backends),
    SNAPSHOT_INTERVAL_SECONDS (default 10), SNAPSHOT_KEY (default
    pluto-data-latest.tar.gz), SNAPSHOT_TIMEOUT_SECONDS (default 20),
    SNAPSHOT_ENABLED (default true; 0/false/no disables despite vars).
"""

import hashlib
import io
import logging
import os
import tarfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from services.secrets import get_secret

logger = logging.getLogger(__name__)

_ARCHIVE_KEY_DEFAULT = "pluto-data-latest.tar.gz"
_MISSING_CODES = frozenset({"NoSuchKey", "NoSuchBucket", "NotFound", "404"})


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    return get_secret(name, default)


def _interval_seconds() -> float:
    try:
        return max(1.0, float(_env("SNAPSHOT_INTERVAL_SECONDS", "10") or "10"))
    except (TypeError, ValueError):
        return 10.0


def _timeout_seconds() -> float:
    try:
        return max(2.0, float(_env("SNAPSHOT_TIMEOUT_SECONDS", "20") or "20"))
    except (TypeError, ValueError):
        return 20.0


def _snapshot_key() -> str:
    return (_env("SNAPSHOT_KEY", _ARCHIVE_KEY_DEFAULT) or _ARCHIVE_KEY_DEFAULT).strip()


def _backend_config() -> Optional[Dict[str, Any]]:
    """Return snapshot backend config, or None when snapshots are disabled."""
    enabled = (_env("SNAPSHOT_ENABLED", "true") or "true").strip().lower()
    if enabled in ("0", "false", "no", "off"):
        return None
    bucket = _env("R2_BUCKET")
    key_id = _env("R2_ACCESS_KEY_ID")
    secret = _env("R2_SECRET_ACCESS_KEY")
    if not bucket or not key_id or not secret:
        return None
    endpoint_override = (_env("SNAPSHOT_ENDPOINT_URL") or "").strip()
    if endpoint_override:
        endpoint = endpoint_override
        # Non-R2 S3 implementations (Supabase) expect path-style addressing.
        path_style = True
    else:
        account = _env("R2_ACCOUNT_ID")
        if not account:
            return None
        endpoint = f"https://{account.strip()}.r2.cloudflarestorage.com"
        path_style = False
    region = (_env("SNAPSHOT_REGION", "auto") or "auto").strip()
    return {
        "bucket": bucket.strip(),
        "key_id": key_id.strip(),
        "secret": secret,
        "key": _snapshot_key(),
        "endpoint": endpoint,
        "region": region,
        "path_style": path_style,
    }


# Kept for backward compatibility (same shape for R2 configs).
def _r2_config() -> Optional[Dict[str, Any]]:
    return _backend_config()


def configured() -> bool:
    """True when snapshot backend settings are present and enabled."""
    try:
        return _backend_config() is not None
    except Exception:
        return False


def _get_client() -> Any:
    """Build an S3-compatible client (boto3 imported lazily)."""
    import boto3
    from botocore.config import Config

    cfg = _backend_config()
    if cfg is None:
        raise RuntimeError("snapshots not configured")
    timeout = _timeout_seconds()
    extra: Dict[str, Any] = {}
    if cfg["path_style"]:
        extra["s3"] = {"addressing_style": "path"}
    boto_cfg = Config(
        connect_timeout=timeout,
        read_timeout=timeout,
        retries={"max_attempts": 2},
        **extra,
    )
    return boto3.client(
        "s3",
        endpoint_url=cfg["endpoint"],
        aws_access_key_id=cfg["key_id"],
        aws_secret_access_key=cfg["secret"],
        config=boto_cfg,
        region_name=cfg["region"],
    )


def _data_root() -> Path:
    from services.storage import data_root

    return data_root()


def _local_data_present(root: Optional[Path] = None) -> bool:
    """True when the local data root holds anything worth keeping."""
    base = root or _data_root()
    try:
        if (base / "accounts.json").exists():
            return True
        users = base / "users"
        if users.is_dir():
            return any(users.iterdir())
        return False
    except OSError:
        return False


def _local_data_partial(root: Optional[Path] = None) -> bool:
    """True when the auth registry survived but its user data vanished.

    The unambiguous partial-wipe signal: `accounts.json` still exists but
    says users should be here, while data/users/ is missing or empty. The
    inverse (users present, no accounts.json) is the *normal* open-mode
    layout, so it is never treated as partial — otherwise open-mode
    installs could never upload a snapshot.
    """
    base = root or _data_root()
    try:
        if not (base / "accounts.json").exists():
            return False
        users = base / "users"
        if not users.is_dir():
            return True
        try:
            return not any(users.iterdir())
        except OSError:
            return True
    except OSError:
        return False


def _iter_data_files(root: Path) -> List[Tuple[str, Path]]:
    """Sorted (relpath, path) for every file, skipping in-flight tmp files."""
    found: List[Tuple[str, Path]] = []
    if not root.is_dir():
        return found
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name.endswith(".tmp"):
                continue  # half-written atomic-write temp; never archive
            full = Path(dirpath) / name
            try:
                rel = str(full.relative_to(root))
            except ValueError:
                continue
            found.append((rel, full))
    found.sort(key=lambda item: item[0])
    return found


def _fingerprint(root: Optional[Path] = None) -> str:
    """Cheap change detector: sha256 over relpath+size+mtime of data files."""
    base = root or _data_root()
    digest = hashlib.sha256()
    try:
        for rel, full in _iter_data_files(base):
            try:
                stat = full.stat()
            except OSError:
                continue
            digest.update(f"{rel}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode("utf-8"))
    except OSError:
        pass
    return digest.hexdigest()


def _build_archive(root: Optional[Path] = None) -> bytes:
    """Tar.gz the data root (rel paths). Raises on I/O errors."""
    base = root or _data_root()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel, full in _iter_data_files(base):
            tar.add(str(full), arcname=rel, recursive=False)
    return buf.getvalue()


def _safe_extract(payload: bytes, root: Optional[Path] = None) -> int:
    """Extract an archive into the data root, refusing path escapes.

    Returns the number of members applied. Raises on corrupt archives.
    """
    base = (root or _data_root()).resolve()
    base.mkdir(parents=True, exist_ok=True)
    applied = 0
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            target = (base / member.name).resolve()
            if target != base and base not in target.parents:
                logger.warning("snapshot member escapes data root; skipping")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            with open(target, "wb") as f:
                f.write(extracted.read())
            applied += 1
    return applied


def _is_missing_error(err: BaseException) -> bool:
    resp = getattr(err, "response", None)
    if isinstance(resp, dict):
        code = str(resp.get("Error", {}).get("Code", ""))
        if code in _MISSING_CODES:
            return True
    return "NoSuchKey" in type(err).__name__


# --- debounced background uploader -------------------------------------

_lock = threading.Lock()
_thread: Optional[threading.Thread] = None
_stop = threading.Event()
_dirty = False
_last_upload = 0.0
_last_fingerprint: Optional[str] = None


def _upload_now(client: Any = None, force: bool = False) -> bool:
    """Upload immediately if data changed. Returns True on success/skip."""
    global _dirty, _last_upload, _last_fingerprint
    try:
        cfg = _backend_config()
        if cfg is None:
            return False
        root = _data_root()
        if not force and (not _local_data_present(root) or _local_data_partial(root)):
            with _lock:
                _dirty = False
            return False  # never overwrite a good remote with an empty or half-wiped disk
        fp = _fingerprint(root)
        with _lock:
            if not force and fp == _last_fingerprint:
                _dirty = False
                return True  # unchanged — skip the network round trip
        payload = _build_archive(root)
        own_client = client if client is not None else _get_client()
        own_client.put_object(Bucket=cfg["bucket"], Key=cfg["key"], Body=payload)
        with _lock:
            _dirty = False
            _last_upload = time.time()
            _last_fingerprint = fp
        logger.info("snapshot uploaded (%d bytes)", len(payload))
        return True
    except ImportError:
        logger.warning("snapshots need boto3 (pip install boto3); backup skipped")
        return False
    except Exception:
        logger.warning("snapshot upload failed", exc_info=True)
        return False


def _worker() -> None:
    while not _stop.is_set():
        _stop.wait(_interval_seconds())
        if _stop.is_set():
            break
        try:
            with _lock:
                dirty = _dirty
            if dirty:
                with _lock:
                    due = (time.time() - _last_upload) >= _interval_seconds()
                if due:
                    _upload_now()
        except Exception:
            logger.debug("snapshot worker failed", exc_info=True)


def _ensure_worker() -> None:
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(target=_worker, name="pluto-snapshots", daemon=True)
        _thread.start()


def notify() -> None:
    """Record that data changed; the debounced worker uploads shortly.

    Never raises and never blocks the caller.
    """
    try:
        if not configured():
            return
        with _lock:
            global _dirty
            _dirty = True
        _ensure_worker()
    except Exception:
        pass


def flush() -> bool:
    """Upload now if dirty. Safe to call on shutdown; never raises."""
    try:
        if not configured():
            return False
        with _lock:
            dirty = _dirty
        if not dirty:
            return True
        return _upload_now()
    except Exception:
        return False


def _download_now(client: Any = None) -> Optional[bytes]:
    """Fetch the remote archive bytes, or None when absent/failed."""
    try:
        cfg = _backend_config()
        if cfg is None:
            return None
        own_client = client if client is not None else _get_client()
        resp = own_client.get_object(Bucket=cfg["bucket"], Key=cfg["key"])
        body = resp.get("Body")
        data = body.read() if hasattr(body, "read") else bytes(body or b"")
        return data or None
    except ImportError:
        logger.warning("snapshots need boto3 (pip install boto3); restore skipped")
        return None
    except Exception as e:
        if _is_missing_error(e):
            logger.info("no remote snapshot yet; starting with empty data")
        else:
            logger.warning("snapshot download failed", exc_info=True)
        return None


def maybe_restore(client: Any = None) -> bool:
    """Restore data/ from R2 when the local disk is empty or half-wiped. Never raises."""
    try:
        if not configured():
            return False
        root = _data_root()
        if _local_data_present(root) and not _local_data_partial(root):
            return False  # full local data wins; never clobber
        payload = _download_now(client)
        if not payload:
            return False
        applied = _safe_extract(payload, root)
        global _last_fingerprint
        with _lock:
            _last_fingerprint = _fingerprint(root)
        logger.info("snapshot restored (%d files)", applied)
        return True
    except Exception:
        logger.warning("snapshot restore failed", exc_info=True)
        return False


def status() -> Dict[str, Any]:
    """Operator-visible snapshot state (no secrets)."""
    with _lock:
        dirty = _dirty
        last_upload = _last_upload
        worker_alive = _thread is not None and _thread.is_alive()
    return {
        "configured": configured(),
        "local_data_present": _local_data_present(),
        "dirty": dirty,
        "worker_alive": worker_alive,
        "last_upload_age_s": (time.time() - last_upload) if last_upload else None,
        "interval_s": _interval_seconds(),
        "key": _snapshot_key(),
    }


def _reset_for_tests() -> None:
    """Stop the worker and clear state (tests only)."""
    global _thread, _dirty, _last_upload, _last_fingerprint
    _stop.set()
    thread, _thread = _thread, None
    if thread is not None and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=5)
    _stop.clear()
    with _lock:
        _dirty = False
        _last_upload = 0.0
        _last_fingerprint = None


def main(argv: Optional[List[str]] = None) -> int:
    """CLI: python -m services.snapshots [--status|--upload|--download]."""
    import argparse

    parser = argparse.ArgumentParser(description="Pluto R2 data snapshot tool")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--status", action="store_true", help="print snapshot state")
    group.add_argument("--upload", action="store_true", help="upload data/ now")
    group.add_argument("--download", action="store_true", help="restore when local empty")
    parser.add_argument("--force", action="store_true", help="with --upload/--download, ignore guards")
    args = parser.parse_args(argv)

    if args.upload:
        if not configured():
            print("snapshots not configured (set the backend env vars, see module docstring)")
            return 2
        ok = _upload_now(force=args.force)
        print("upload ok" if ok else "upload failed (see logs)")
        return 0 if ok else 1
    if args.download:
        if not configured():
            print("snapshots not configured (set the backend env vars, see module docstring)")
            return 2
        if args.force:
            payload = _download_now()
            if not payload:
                print("no remote snapshot")
                return 1
            try:
                applied = _safe_extract(payload)
            except Exception:
                print("remote snapshot is corrupt")
                return 1
            print(f"restored {applied} files")
            return 0
        print("restored" if maybe_restore() else "nothing restored")
        return 0
    st = status()
    for key in ("configured", "local_data_present", "dirty", "worker_alive",
                "last_upload_age_s", "interval_s", "key"):
        print(f"{key}={st[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
