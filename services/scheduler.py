"""Background scheduler for storage hygiene and other periodic tasks.

Runs storage hygiene (pruning stale outputs/uploads) on a configurable
interval instead of on every request. This removes the per-request
overhead of walking vault directories and running pruning operations.
"""

import logging
import threading
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from services.coderun import prune_build_artifacts
from services.kb_ingest import run_reaper_once
from services.limits import STORAGE_HYGIENE_INTERVAL_SECONDS
from services.secrets import get_secret
from services.storage import data_root

logger = logging.getLogger(__name__)

_scheduler: Optional[BackgroundScheduler] = None
_scheduler_lock = threading.Lock()
_started = False


def _run_all_users_hygiene() -> None:
    """Run storage hygiene for all users with vaults."""
    root = data_root()
    users_dir = root / "users"
    if not users_dir.exists():
        return

    for user_path in users_dir.iterdir():
        if not user_path.is_dir():
            continue
        user_id = user_path.name
        try:
            # Import here to avoid circular imports
            from services.files import FileStore
            from services.storage import UserStore

            user_store = UserStore(user_id, run_migration=False)
            file_store = FileStore(user_id)

            # Prune stale outputs (30 days by default)
            file_store.prune_stale_outputs()

            # Prune stale uploads (7 days, unreferenced)
            from backend.deps import _referenced_upload_ids
            referenced = _referenced_upload_ids(user_store)
            # Fail-closed: skip pruning when chat load failed (None).
            if referenced is not None:
                file_store.prune_stale_uploads(referenced_ids=referenced)

            # Prune orphan files (7 days)
            file_store.prune_orphan_files()

            logger.debug("storage hygiene completed for user=%s", user_id)
        except Exception as e:
            logger.warning("storage hygiene failed for user=%s: %s", user_id, e)


def start_scheduler() -> None:
    """Start the background scheduler (idempotent)."""
    global _scheduler, _started

    # Check if disabled via env
    enabled = (get_secret("PLUTO_SCHEDULER_ENABLED", "true") or "true").lower()
    if enabled in ("0", "false", "no", "off"):
        logger.info("scheduler disabled via PLUTO_SCHEDULER_ENABLED")
        return

    with _scheduler_lock:
        if _started:
            return
        try:
            raw_interval = get_secret("PLUTO_HYGIENE_INTERVAL_SECONDS", str(STORAGE_HYGIENE_INTERVAL_SECONDS)) or str(STORAGE_HYGIENE_INTERVAL_SECONDS)
            interval = max(60.0, float(raw_interval))
        except (ValueError, TypeError):
            logger.warning("bad PLUTO_HYGIENE_INTERVAL_SECONDS; using default %s", STORAGE_HYGIENE_INTERVAL_SECONDS)
            interval = max(60.0, float(STORAGE_HYGIENE_INTERVAL_SECONDS))
        _started = True
        # ±10% jitter avoids thundering herd when N workers/containers
        # restart together (Render redeploy, UVICORN_WORKERS>1).
        try:
            import random as _random

            jitter = float(get_secret("PLUTO_HYGIENE_JITTER_RATIO", "0.10") or "0.10")
            jitter = min(0.5, max(0.0, jitter))
            if jitter:
                # Non-crypto scheduling jitter (thundering-herd avoidance).
                interval = interval * (1.0 + _random.uniform(-jitter, jitter))  # noqa: S311
        except Exception:
            logger.debug("hygiene jitter parse failed; using base interval", exc_info=True)

        try:
            reaper_raw = get_secret("PLUTO_KB_REAPER_INTERVAL_SECONDS", "60") or "60"
            reaper_interval = max(15.0, float(reaper_raw))
        except (ValueError, TypeError):
            logger.warning("bad PLUTO_KB_REAPER_INTERVAL_SECONDS; using 60s")
            reaper_interval = 60.0

        _scheduler = BackgroundScheduler(daemon=True)
        try:
            _scheduler.add_job(
                _run_all_users_hygiene,
                IntervalTrigger(seconds=interval, jitter=int(min(300, interval * 0.1))),
                id="storage_hygiene",
                max_instances=1,
                coalesce=True,
                misfire_grace_time=300,
            )
            _scheduler.add_job(
                _run_kb_reaper,
                IntervalTrigger(seconds=reaper_interval),
                id="kb_ingest_reaper",
                max_instances=1,
                coalesce=True,
                misfire_grace_time=120,
            )
            _scheduler.add_job(
                prune_build_artifacts,
                IntervalTrigger(seconds=3600, jitter=600),  # hourly with 10min jitter
                id="build_artifact_prune",
                max_instances=1,
                coalesce=True,
                misfire_grace_time=600,
            )
            _scheduler.start()
        except Exception:
            logger.warning("background scheduler failed to start", exc_info=True)
            try:
                _scheduler.shutdown(wait=False)
            except Exception:
                logger.debug("scheduler shutdown after failed start failed", exc_info=True)
            _scheduler = None
            _started = False
            return
        logger.info("background scheduler started (hygiene interval=%.0fs)", interval)


def stop_scheduler() -> None:
    """Stop the background scheduler (for tests/shutdown)."""
    global _scheduler, _started
    with _scheduler_lock:
        if _scheduler:
            _scheduler.shutdown(wait=False)
            _scheduler = None
        _started = False


def _run_kb_reaper() -> None:
    """Retry shed KB ingests from disk (never raises; scheduler-safe)."""
    try:
        run_reaper_once()
    except Exception:
        logger.debug("kb ingest reaper job failed", exc_info=True)


if __name__ == "__main__":
    # CLI for manual testing
    logging.basicConfig(level=logging.INFO)
    start_scheduler()
    import time
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        stop_scheduler()
