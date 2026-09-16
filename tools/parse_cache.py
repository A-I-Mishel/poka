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


class ParseCache:
    """Thread-safe bounded FIFO cache keyed by upload identity."""

    def __init__(self, maxsize: int):
        self._max = max(1, int(maxsize))
        self._lock = threading.Lock()
        self._data: dict = {}

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
        """Cached value for key, or None (miss/unusable key)."""
        if not key:
            return None
        with self._lock:
            return self._data.get(key)

    def set(self, key: str, value: Any) -> None:
        """Store value under key, evicting oldest past capacity. Never raises."""
        if not key:
            return
        try:
            with self._lock:
                if len(self._data) >= self._max:
                    self._data.pop(next(iter(self._data)))
                self._data[key] = value
        except Exception:
            pass
