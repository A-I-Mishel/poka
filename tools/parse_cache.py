"""Shared bounded FIFO parse cache for tool file reads (pdf/document/csv).

Second read of the same upload in one chat is RAM, not re-parse. Keys
are user:upload:mtime:size (a rewrite busts the entry); values are
opaque to the cache (rendered text, or (frame, truncated) tuples for
CSV — copy-on-read stays at that call site). All operations are
best-effort and never raise into tools.
"""

import threading
from typing import Any, Optional

from services.files import FileStore

import logging

logger: logging.Logger = logging.getLogger(__name__)


class ParseCache:
    """Thread-safe bounded FIFO cache with TTL, keyed by upload identity."""

    def __init__(self, maxsize: int, ttl: float = 600.0):
        self._max = max(1, int(maxsize))
        self._ttl = max(60.0, float(ttl))
        self._lock = threading.Lock()
        self._data: dict = {}
        self._when: dict = {}

    def key_for(self, user_id: Any, upload_id: Any) -> str:
        """Cache key for one upload, or "" when unresolvable (skip caching)."""
        try:
            uid = str(upload_id or "").strip()
            user = str(user_id or "").strip()
            if not uid or not user:
                return ""
            path = FileStore(user).resolve_upload(uid)
            if path is None:
                return ""
            stat = path.stat()
            return f"{user}:{uid}:{stat.st_mtime}:{stat.st_size}"
        except Exception:
            return ""

    def get(self, key: str) -> Optional[Any]:
        """Cached value for key, or None (miss/expired/unusable key)."""
        if not key:
            return None
        import copy as _copy
        import time as _time

        with self._lock:
            if key not in self._data:
                return None
            if _time.time() - self._when.get(key, 0.0) > self._ttl:
                self._data.pop(key, None)
                self._when.pop(key, None)
                return None
            val = self._data.get(key)
            try:
                return _copy.deepcopy(val)
            except Exception:
                return val

    def set(self, key: str, value: Any) -> None:
        """Store value under key, evicting oldest past capacity. Never raises."""
        if not key:
            return
        try:
            import copy as _copy
            import time as _time

            try:
                val = _copy.deepcopy(value)
            except Exception:
                # Bound memory: don't cache huge frames as live refs.
                try:
                    size = len(str(value))
                except Exception:
                    size = 0
                if size > 200000:
                    return
                val = value
            with self._lock:
                if len(self._data) >= self._max:
                    old = next(iter(self._data))
                    self._data.pop(old, None)
                    self._when.pop(old, None)
                self._data[key] = val
                self._when[key] = _time.time()
        except Exception:
            logger.debug("parse cache set failed", exc_info=True)
