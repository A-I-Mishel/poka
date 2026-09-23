"""Bounded background KB ingestion (upload fast-path + shed reaper).

Every large upload (>512 KiB) used to spawn its own daemon thread holding
the full file bytes: N concurrent uploads held N x file-size in RAM with
no backpressure. Now at most _KB_INGEST_MAX_INFLIGHT background ingests
run at once; extras are shed into a small bounded backlog that stores
only (user_id, upload_id, display_name) — never bytes — and a scheduler
reaper retries them by re-reading bytes from the vault on disk.

Ingest is best-effort by design (it never fails an upload): a shed entry
whose upload was since deleted is a silent no-op. Daemon threads preserve
the historical shutdown behavior. All failures stay observable via
obs events; nothing here ever raises to request handlers.
"""

import collections
import logging
import threading
from typing import Deque, Optional, Tuple

logger = logging.getLogger(__name__)

# At most this many background ingests run at once (each can hold one
# file up to MAX_UPLOAD_BYTES while embedding takes seconds on free tiers).
_KB_INGEST_MAX_INFLIGHT = 2
_kb_ingest_sema = threading.Semaphore(_KB_INGEST_MAX_INFLIGHT)

# Shed backlog: identity tuples only (~100 bytes each), never file bytes.
# Bounded so visitor-driven upload bursts cannot grow it without bound.
_KB_BACKLOG_MAX = 50
_backlog_lock = threading.Lock()
_backlog: Deque[Tuple[str, str, str]] = collections.deque()


def _obs_event(*args, **kwargs) -> None:
    try:
        from services.obs import event as _event

        _event(*args, **kwargs)
    except Exception:
        logger.debug("kb ingest obs event failed", exc_info=True)


def _ingest_owned(user_id: str, upload_id: str, display_name: str, data: bytes) -> None:
    """Call ingest_document; failures stay observable, never raise."""
    try:
        from services import kb as kb_svc

        kb_svc.ingest_document(user_id, upload_id, display_name, data)
    except Exception as e:
        _obs_event("kb.ingest_error", reason="background-ingest-failed",
                   detail=str(e)[:120])
        logger.warning("background kb ingest failed for upload %s", upload_id)


def _run_owned(user_id: str, upload_id: str, display_name: str, data: bytes) -> None:
    """Blocking slot-owned ingest wrapper: always releases, never raises."""
    try:
        _ingest_owned(user_id, upload_id, display_name, data)
    finally:
        try:
            _kb_ingest_sema.release()
        except Exception:
            logger.debug("kb ingest slot release failed", exc_info=True)


def _enqueue_backlog(user_id: str, upload_id: str, display_name: str) -> None:
    """Queue one shed ingest for the reaper (identity only, bounded)."""
    with _backlog_lock:
        if len(_backlog) >= _KB_BACKLOG_MAX:
            dropped = _backlog.popleft()
            _obs_event("kb.ingest_drop", reason="backlog-full",
                       upload_id=str(getattr(dropped, "__getitem__", lambda _i: "?")(1)))
            logger.warning("kb ingest backlog full; dropping oldest entry")
        _backlog.append((str(user_id), str(upload_id), str(display_name)))


def backlog_depth() -> int:
    """Current shed-backlog length (operator/tests introspection)."""
    with _backlog_lock:
        return len(_backlog)


def schedule_kb_ingest(user_id: str, upload_id: str, display_name: str, data: bytes) -> bool:
    """Queue one background ingest if a slot is free; else shed to backlog.

    Non-blocking: never waits, never raises. Returns True when a worker
    was started, False when shed (upload still succeeds — ingest is
    best-effort; the reaper retries shed entries from disk).
    """
    if not _kb_ingest_sema.acquire(blocking=False):
        _obs_event("kb.ingest_shed", reason="ingest-saturated", upload_id=str(upload_id))
        logger.warning("kb ingest saturated; shed upload %s to backlog", upload_id)
        try:
            _enqueue_backlog(user_id, upload_id, display_name)
        except Exception:
            logger.debug("kb ingest backlog enqueue failed", exc_info=True)
        return False
    try:
        threading.Thread(
            target=_run_owned,
            args=(str(user_id), str(upload_id), str(display_name), data),
            daemon=True,
            name="kb-ingest",
        ).start()
        return True
    except Exception:
        try:
            _kb_ingest_sema.release()
        except Exception:
            logger.debug("kb ingest slot release failed", exc_info=True)
        logger.debug("kb ingest schedule failed", exc_info=True)
        return False


def _reingest_worker(user_id: str, upload_id: str, display_name: str) -> None:
    """Slot-owned reaper worker: re-read bytes from disk, ingest, release."""
    try:
        try:
            from services.files import FileStore

            store = FileStore(user_id)
            try:
                meta = store.get_upload(upload_id)
            except Exception:
                meta = None
            if meta is None:
                _obs_event("kb.ingest_skip", reason="upload-gone", upload_id=str(upload_id))
                return
            try:
                path = store.resolve_upload(upload_id)
            except Exception:
                path = None
            if path is None:
                _obs_event("kb.ingest_skip", reason="upload-unavailable",
                           upload_id=str(upload_id))
                return
            try:
                with open(path, "rb") as f:
                    data = f.read()
            except OSError:
                _obs_event("kb.ingest_skip", reason="upload-unreadable",
                           upload_id=str(upload_id))
                return
            if not data:
                _obs_event("kb.ingest_skip", reason="upload-empty", upload_id=str(upload_id))
                return
            name = str(getattr(meta, "display_name", None) or display_name or "file")
            _ingest_owned(user_id, upload_id, name, data)
        except Exception as e:
            _obs_event("kb.ingest_error", reason="reaper-failed", detail=str(e)[:120])
            logger.debug("kb ingest reaper worker failed", exc_info=True)
    finally:
        try:
            _kb_ingest_sema.release()
        except Exception:
            logger.debug("kb ingest slot release failed", exc_info=True)


def drain_backlog(max_items: Optional[int] = None) -> int:
    """Start reaper workers for queued shed ingests. Returns count started.

    Non-blocking: stops at the first unavailable slot (entries stay queued
    for the next pass). Never raises.
    """
    started = 0
    while True:
        if max_items is not None and started >= max_items:
            break
        with _backlog_lock:
            if not _backlog:
                break
            entry = _backlog.popleft()
        if not _kb_ingest_sema.acquire(blocking=False):
            with _backlog_lock:
                _backlog.appendleft(entry)
            break
        try:
            user_id, upload_id, display_name = entry
            threading.Thread(
                target=_reingest_worker,
                args=(user_id, upload_id, display_name),
                daemon=True,
                name="kb-reaper",
            ).start()
            started += 1
        except Exception:
            try:
                _kb_ingest_sema.release()
            except Exception:
                logger.debug("kb ingest slot release failed", exc_info=True)
            with _backlog_lock:
                _backlog.appendleft(entry)
            logger.debug("kb ingest reaper schedule failed", exc_info=True)
            break
    return started


def run_reaper_once() -> int:
    """Scheduler entry point: one backlog drain pass. Never raises."""
    try:
        return drain_backlog()
    except Exception:
        logger.debug("kb ingest reaper pass failed", exc_info=True)
        return 0


def reset_for_tests() -> None:
    """Clear the backlog (tests only). Slots are owned by workers; not forced."""
    with _backlog_lock:
        _backlog.clear()
