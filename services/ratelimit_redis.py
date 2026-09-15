"""Redis-backed rate limiter for distributed deployments.

Uses Redis sorted sets for sliding-window rate limiting.
Key format: "rl:{action}:{identity}" with scores as timestamps.
"""

import os
import time
from typing import Dict, Optional, Tuple

import redis

from services.limits import RATE_LIMITS
from services.ratelimit import RateLimitResult, RateLimiter


class RedisRateLimiter(RateLimiter):
    """Sliding-window rate limiter using Redis sorted sets.

    Each identity+action gets a Redis key "rl:{action}:{identity}".
    Members are timestamps (float), scores are the same timestamp.
    Window cleanup: ZREMRANGEBYSCORE removes old entries.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        limits: Optional[Dict[str, Tuple[int, float]]] = None,
        key_prefix: str = "rl",
    ) -> None:
        self._limits = dict(limits or RATE_LIMITS)
        self._key_prefix = key_prefix
        self._redis = redis.from_url(redis_url, decode_responses=True)

    def _key(self, user_id: str, action: str) -> str:
        return f"{self._key_prefix}:{action}:{user_id}"

    def check(self, user_id: str, action: str) -> RateLimitResult:
        max_calls, window = self._limits.get(action, (10**9, 60.0))
        now = time.time()
        key = self._key(user_id, action)
        window_start = now - window

        # Use pipeline for atomic operations
        pipe = self._redis.pipeline()
        # Remove expired entries
        pipe.zremrangebyscore(key, 0, window_start)
        # Count current entries
        pipe.zcard(key)
        # Add new entry (timestamp as both member and score)
        pipe.zadd(key, {str(now): now})
        # Set expiry on the key (window + 1 second buffer)
        pipe.expire(key, int(window) + 1)
        results = pipe.execute()

        current_count = results[1]

        if current_count >= max_calls:
            # Get oldest entry to calculate retry-after
            oldest = self._redis.zrange(key, 0, 0, withscores=True)
            if oldest:
                retry = max(0.0, oldest[0][1] + window - now)
            else:
                retry = window
            return RateLimitResult(
                allowed=False,
                retry_after=retry,
                reason=f"Rate limit exceeded for {action} ({max_calls}/{int(window)}s).",
                limit=max_calls,
                remaining=0,
                window=window,
            )

        remaining = max(0, max_calls - current_count - 1)
        return RateLimitResult(
            allowed=True,
            limit=max_calls,
            remaining=remaining,
            window=window,
        )

    def reset(self, user_id: Optional[str] = None) -> None:
        """Clear counters, optionally scoped to one user."""
        if user_id is None:
            # Scan and delete all rate limit keys
            pattern = f"{self._key_prefix}:*"
            cursor = 0
            while True:
                cursor, keys = self._redis.scan(cursor, match=pattern, count=100)
                if keys:
                    self._redis.delete(*keys)
                if cursor == 0:
                    break
        else:
            # Delete all actions for this user
            # We need to find all action keys for this user
            pattern = f"{self._key_prefix}:*:{user_id}"
            cursor = 0
            while True:
                cursor, keys = self._redis.scan(cursor, match=pattern, count=100)
                if keys:
                    self._redis.delete(*keys)
                if cursor == 0:
                    break


def create_redis_limiter() -> Optional[RateLimiter]:
    """Create RedisRateLimiter if REDIS_URL is configured, else None."""
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return None
    try:
        return RedisRateLimiter(redis_url=redis_url)
    except Exception as e:
        # Log warning but don't crash — fallback to MemoryRateLimiter
        import logging
        logging.getLogger(__name__).warning("Redis rate limiter init failed: %s", e)
        return None


if __name__ == "__main__":
    # Quick manual test
    import sys
    limiter = create_redis_limiter()
    if not limiter:
        print("REDIS_URL not set, skipping test")
        sys.exit(0)
    print("Testing Redis rate limiter...")
    for i in range(5):
        result = limiter.check("test-user", "chat")
        print(f"  Attempt {i+1}: allowed={result.allowed}, remaining={result.remaining}")
    limiter.reset("test-user")
    print("Reset, next should be allowed:")
    result = limiter.check("test-user", "chat")
    print(f"  After reset: allowed={result.allowed}, remaining={result.remaining}")
