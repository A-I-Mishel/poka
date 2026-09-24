"""Atomic file IO: per-file locks, tmp+replace writes, guarded JSON reads."""

import contextlib
import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple

from services.obs import event as obs_event
from services.storage.ids import StorageError

logger = logging.getLogger(__name__)


def _tmp_path(path: Path) -> Path:
    """Unique tmp sibling so concurrent writers never share one file."""
    token = f"{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex[:8]}"
    return path.with_name(f"{path.name}.{token}.tmp")


_locks_guard = threading.Lock()
_locks: Dict[str, threading.RLock] = {}
# Bound the lock table so ephemeral-user vaults cannot grow it forever;
# eviction is safe: a missing entry is recreated on next use (only the
# mutex identity changes, never correctness).
_LOCKS_MAX = 2048
_thread_depth = threading.local()


def _lock_dir_for(path: Path) -> Path:
    """Sidecar lock dir for one file (mkdir is atomic cross-process)."""
    try:
        return path.parent / (path.name + ".lockdir")
    except Exception:
        return Path(str(path) + ".lockdir")


def _acquire_interprocess(lock_dir: Path, timeout_s: float = 5.0) -> bool:
    """Best-effort cross-process mutex. True when held (or when locking
    is unavailable and we must proceed anyway). Stale dirs (>30s) are
    broken so a crashed worker cannot wedge writers forever."""
    deadline = time.time() + timeout_s
    while True:
        try:
            # parents=False: acquiring a read lock must never create
            # vault directories as a side effect (ephemeral reads stay
            # disk-clean; writers ensure parents before locking).
            lock_dir.mkdir(parents=False, exist_ok=False)
            return True
        except FileNotFoundError:
            # Parent vault doesn't exist yet — nothing to coordinate
            # with; proceed without inter-process locking.
            return False
        except FileExistsError:
            pass
        except OSError:
            # Unwritable/missing parent: cannot lock — proceed (writes
            # stay atomic via tmp+replace; races degrade to last-writer).
            return False
        try:
            age = time.time() - lock_dir.stat().st_mtime
            if age > 30:
                try:
                    lock_dir.rmdir()
                    continue
                except OSError:
                    pass
        except OSError:
            pass
        if time.time() >= deadline:
            return False
        time.sleep(0.02)


def _release_interprocess(lock_dir: Path) -> None:
    try:
        lock_dir.rmdir()
    except OSError:
        pass


@contextlib.contextmanager
def path_lock(path: Path) -> Iterator[None]:
    """Per-file mutex: thread RLock + best-effort inter-process lockdir.

    Reentrant per thread (mutate helpers hold it across read-modify-write
    while _read_json/_write_json re-acquire). Single-process correctness
    is hard; multi-process races degrade to last-writer-wins instead of
    torn reads (writes remain atomic via tmp+replace).
    """
    try:
        key = str(path.resolve())
    except OSError:
        key = str(path.absolute())
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            if len(_locks) >= _LOCKS_MAX:
                # Drop an arbitrary old entry; recreation is safe.
                _locks.pop(next(iter(_locks)))
            lock = threading.RLock()
            _locks[key] = lock
    depth = getattr(_thread_depth, "depth", 0)
    with lock:
        if depth == 0:
            lock_dir = _lock_dir_for(path)
            held = _acquire_interprocess(lock_dir)
            _thread_depth.depth = 1
            try:
                yield
            finally:
                _thread_depth.depth = 0
                if held:
                    _release_interprocess(lock_dir)
        else:
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
            stamp = "%d-%d-%d" % (int(time.time() * 1000), os.getpid(), threading.get_ident() % 100000)
            backup = path.with_name(f"{path.stem}.corrupt-{stamp}{path.suffix}")
            with path_lock(path):
                if path.exists():
                    os.replace(path, backup)
        except OSError:
            pass
        obs_event("storage.quarantine", file=path.name)
        return None, True


def _write_json(path: Path, payload: Any) -> None:
    """Write JSON atomically via unique-tmp + fsync + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _tmp_path(path)
    try:
        with path_lock(path):
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
                # Durability: flush + fsync before the atomic replace so a
                # crash/power loss cannot lose the just-written payload
                # (old file stays intact either way; without fsync only the
                # last write is at risk, never corruption).
                try:
                    f.flush()
                    os.fsync(f.fileno())
                except OSError:
                    logger.debug("fsync failed for %s", path.name, exc_info=True)
            atomic_replace(tmp_path, path)
            # Free-tier durability: queue an R2 snapshot (no-op when
            # unconfigured; never raises into the write path).
            try:
                from services.snapshots import notify as _snapshots_notify

                _snapshots_notify()
            except Exception:
                logger.debug("snapshot notify failed", exc_info=True)
    except OSError as e:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        obs_event("storage.write", status="error", file=path.name)
        raise StorageError(f"Could not persist {path.name}: {e}") from e
    except Exception as e:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        obs_event("storage.write", status="error", file=path.name)
        raise StorageError(f"Could not persist {path.name}: {e}") from e
