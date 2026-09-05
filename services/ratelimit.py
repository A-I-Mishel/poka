"""Per-user rate limiting behind an swappable backend interface.

Default backend is in-process memory (correct per process, documented
limitation for multi-process deploys). To scale out, implement
RateLimiter against Redis (INCR + EXPIRE per user:action window) and
swap it via configure_rate_limiter(). Limits live in services.limits.
"""

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional, Tuple

from services.limits import RATE_LIMITS


@dataclass(frozen=True)
class RateLimitResult:
    """Structured outcome of one rate-limit check."""

    allowed: bool
    retry_after: float = 0.0
    reason: str = ""


class RateLimiter:
    """Backend interface. Subclass for Redis/distributed deployments."""

    def check(self, user_id: str, action: str) -> RateLimitResult:
        """Return whether one unit of `action` is allowed for `user_id`."""
        raise NotImplementedError

    def reset(self, user_id: Optional[str] = None) -> None:
        """Clear counters (tests/ops)."""
        raise NotImplementedError


class MemoryRateLimiter(RateLimiter):
    """Sliding-window limiter kept in process memory.

    Correct for single-process deployments (Streamlit default). For
    multi-process setups each process enforces independently, which is
    fail-open on counts — documented, acceptable for abuse friction,
    not for hard billing.
    """

    def __init__(self, limits: Optional[Dict[str, Tuple[int, float]]] = None) -> None:
        self._limits: Dict[str, Tuple[int, float]] = dict(limits or RATE_LIMITS)
        self._lock = threading.Lock()
        self._hits: Dict[Tuple[str, str], Deque[float]] = {}

    def check(self, user_id: str, action: str) -> RateLimitResult:
        """Allow/deny one action unit for a user in its sliding window."""
        max_calls, window = self._limits.get(action, (10**9, 60.0))
        now = time.time()
        key = (user_id or "anonymous", action)
        with self._lock:
            queue = self._hits.setdefault(key, deque())
            while queue and queue[0] <= now - window:
                queue.popleft()
            if len(queue) >= max_calls:
                retry = max(0.0, queue[0] + window - now) if queue else window
                return RateLimitResult(
                    allowed=False,
                    retry_after=retry,
                    reason=f"Rate limit exceeded for {action} ({max_calls}/{int(window)}s).",
                )
            queue.append(now)
            return RateLimitResult(allowed=True)

    def reset(self, user_id: Optional[str] = None) -> None:
        """Clear counters, optionally scoped to one user."""
        with self._lock:
            if user_id is None:
                self._hits.clear()
            else:
                for key in [k for k in self._hits if k[0] == user_id]:
                    del self._hits[key]


_limiter: RateLimiter = MemoryRateLimiter()


def get_rate_limiter() -> RateLimiter:
    """Return the active limiter (swap via configure_rate_limiter)."""
    return _limiter


def configure_rate_limiter(limiter: RateLimiter) -> None:
    """Install a custom limiter backend (e.g. Redis)."""
    global _limiter
    _limiter = limiter
