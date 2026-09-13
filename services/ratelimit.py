"""Rate limiting behind a swappable backend interface.

Checks are keyed by a limiting identity, not necessarily a user ID:
stable identities (env/token) use their user ID, while ephemeral
open-mode visitors share their client IP so limits actually bind
(a fresh random ID per request would never hit any limit).
Default backend is in-process memory (correct per process, documented
limitation for multi-process deploys). To scale out, implement
RateLimiter against Redis (INCR + EXPIRE per key:action window) and
swap it via configure_rate_limiter(). Limits live in services.limits.
"""

import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional, Tuple

from services.limits import RATE_LIMITS


@dataclass(frozen=True)
class RateLimitResult:
    """Structured outcome of one rate-limit check."""

    allowed: bool
    retry_after: float = 0.0
    reason: str = ""
    limit: int = 0
    remaining: int = 0
    window: float = 60.0


def _trust_proxy() -> bool:
    """Whether X-Forwarded-For can be trusted (behind a known proxy)."""
    raw = os.getenv("PLUTO_TRUST_PROXY", "false") or "false"
    return raw.strip().lower() in ("1", "true", "yes", "on")


def extract_client_ip(x_forwarded_for: Optional[str], peer: Optional[str]) -> str:
    """Best-effort client IP for rate limiting.

    When PLUTO_TRUST_PROXY=true, prefers the last X-Forwarded-For entry
    (appended by the closest trusted proxy). Otherwise returns peer
    directly — XFF is client-controlled without a trusted proxy and
    must not be used for limit keys.
    """
    peer_ip = (str(peer or "").strip() or "unknown")[:45]
    if not _trust_proxy():
        return peer_ip
    if x_forwarded_for:
        entries = [p.strip() for p in str(x_forwarded_for).split(",") if p.strip()]
        if entries:
            return entries[-1][:45]
    return peer_ip


def rate_limit_headers(result: RateLimitResult, action: str) -> dict:
    """Headers for rate-limit responses (never includes client identity)."""
    h: dict = {}
    if result.limit:
        h["X-RateLimit-Limit"] = str(result.limit)
        h["X-RateLimit-Remaining"] = str(max(0, result.remaining))
        h["X-RateLimit-Window"] = str(int(result.window))
    if not result.allowed and result.retry_after > 0:
        h["Retry-After"] = str(int(result.retry_after + 0.9))
    return h


def limit_key_for(source: str, user_id: Optional[str], client_ip_addr: Optional[str]) -> str:
    """Stable limiter identity for one request.

    Stable sources ("env", "token", "account") key on the user ID;
    anything else (ephemeral open-mode visitors) keys on the client IP
    so repeated requests from the same visitor share one bucket.
    """
    if source in ("env", "token", "account") and (user_id or "").strip():
        return (user_id or "").strip()
    ip = (client_ip_addr or "").strip() or "unknown"
    return f"ip:{ip}"


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

    Correct for single-process deployments. For
    multi-process setups each process enforces independently, which is
    fail-open on counts — documented, acceptable for abuse friction,
    not for hard billing.
    """

    def __init__(self, limits: Optional[Dict[str, Tuple[int, float]]] = None) -> None:
        self._limits: Dict[str, Tuple[int, float]] = dict(limits or RATE_LIMITS)
        self._lock = threading.Lock()
        self._hits: Dict[Tuple[str, str], Deque[float]] = {}

    def check(self, user_id: str, action: str) -> RateLimitResult:
        """Allow/deny one action unit for a limiting identity in its window.

        `user_id` is an opaque limiting identity: a stable user ID, or an
        `ip:<addr>` key for ephemeral visitors (see limit_key_for).
        Entries whose newest hit predates their window are evicted on
        every check, so one-shot identities cannot accumulate forever.
        """
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
                    limit=max_calls,
                    remaining=0,
                    window=window,
                )
            queue.append(now)
            self._prune_locked(now)
            remaining = max(0, max_calls - len(queue))
            return RateLimitResult(allowed=True, limit=max_calls, remaining=remaining, window=window)

    def _prune_locked(self, now: float) -> None:
        """Evict identities with no hits inside their window (caller holds the lock)."""
        dead = [
            key for key, queue in self._hits.items()
            if not queue or queue[-1] <= now - self._limits.get(key[1], (10**9, 60.0))[1]
        ]
        for key in dead:
            del self._hits[key]

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
