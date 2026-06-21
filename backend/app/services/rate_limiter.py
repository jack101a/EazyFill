"""Distributed rate limiter — Redis-backed with in-memory fallback.

When Redis is enabled, limits are shared across all processes/servers.
When Redis is unavailable, falls back to in-memory (single-process only).
"""

from __future__ import annotations

import time
import threading
import logging
from collections import OrderedDict

from app.core.config import Settings

logger = logging.getLogger(__name__)

_MAX_MEMORY_BUCKETS = 10_000
_MEMORY_CLEANUP_INTERVAL_SECONDS = 60


class RateLimiter:
    """Token-bucket rate limiter with optional Redis backend."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._redis_enabled = settings.redis.enabled
        self._redis = None
        self._prefix = settings.redis.prefix

        # In-memory fallback
        self._buckets: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.RLock()
        self._last_memory_cleanup = 0.0

        if self._redis_enabled:
            self._init_redis()

    def _init_redis(self) -> None:
        try:
            import redis.asyncio as redis
            self._redis = redis.from_url(
                self._settings.redis.url,
                decode_responses=True,
            )
        except Exception:
            self._redis_enabled = False

    def _make_key(self, scope: str, identifier: str, window: str) -> str:
        return f"{self._prefix}rl:{scope}:{identifier}:{window}"

    async def check(
        self,
        scope: str,          # "user", "ip", "device", "global"
        identifier: str,     # user_id, ip, device_id
        max_requests: int,
        window_seconds: int = 60,
    ) -> bool:
        """Check if request is allowed. Returns True if allowed."""
        if self._redis_enabled and self._redis:
            return await self._check_redis(scope, identifier, max_requests, window_seconds)
        return self._check_memory(scope, identifier, max_requests, window_seconds)

    async def health(self) -> dict:
        """Report limiter backend health without mutating request counters."""
        if not self._redis_enabled:
            return {"status": "ok", "critical": False, "backend": "memory"}
        if not self._redis:
            return {"status": "degraded", "critical": False, "backend": "memory_fallback"}
        started = time.time()
        try:
            await self._redis.ping()
            return {
                "status": "ok",
                "critical": False,
                "backend": "redis",
                "latency_ms": int((time.time() - started) * 1000),
            }
        except Exception as exc:
            return {
                "status": "degraded",
                "critical": False,
                "backend": "memory_fallback",
                "error_type": type(exc).__name__,
                "latency_ms": int((time.time() - started) * 1000),
            }

    async def _check_redis(self, scope: str, identifier: str, max_requests: int, window_seconds: int) -> bool:
        key = self._make_key(scope, identifier, str(window_seconds))
        try:
            now = time.time()
            window_start = now - window_seconds

            async with self._redis.pipeline() as pipe:
                pipe.zremrangebyscore(key, 0, window_start)
                pipe.zcard(key)
                pipe.zadd(key, {str(now): now})
                pipe.expire(key, window_seconds + 1)
                _, count, _, _ = await pipe.execute()

            return count < max_requests
        except Exception as exc:
            logger.warning(
                "redis_rate_limiter_failed_fallback_memory",
                extra={"context": {"scope": scope, "identifier": identifier, "error": str(exc)}},
            )
            return self._check_memory(scope, identifier, max_requests, window_seconds)

    def _check_memory(self, scope: str, identifier: str, max_requests: int, window_seconds: int) -> bool:
        key = self._make_key(scope, identifier, str(window_seconds))
        now = time.time()

        with self._lock:
            if (
                now - self._last_memory_cleanup >= _MEMORY_CLEANUP_INTERVAL_SECONDS
                or len(self._buckets) >= _MAX_MEMORY_BUCKETS
            ):
                self._cleanup_memory(now)

            bucket = self._buckets.get(key)
            if bucket is None:
                if len(self._buckets) >= _MAX_MEMORY_BUCKETS:
                    self._buckets.popitem(last=False)
                self._buckets[key] = {"timestamps": [now], "expires": now + window_seconds + 1}
                return True
            self._buckets.move_to_end(key)

            # Prune old timestamps
            cutoff = now - window_seconds
            bucket["timestamps"] = [t for t in bucket["timestamps"] if t > cutoff]
            bucket["expires"] = now + window_seconds + 1

            if len(bucket["timestamps"]) < max_requests:
                bucket["timestamps"].append(now)
                return True

            return False

    def _cleanup_memory(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._lock:
            self._last_memory_cleanup = now
            expired = [k for k, v in self._buckets.items() if v["expires"] < now]
            for k in expired:
                del self._buckets[k]

    async def get_usage(self, scope: str, identifier: str, window_seconds: int = 60) -> int:
        """Get current usage count in the window."""
        if self._redis_enabled and self._redis:
            key = self._make_key(scope, identifier, str(window_seconds))
            try:
                cutoff = time.time() - window_seconds
                await self._redis.zremrangebyscore(key, 0, cutoff)
                return await self._redis.zcard(key)
            except Exception:
                return 0

        key = self._make_key(scope, identifier, str(window_seconds))
        with self._lock:
            bucket = self._buckets.get(key)
            if not bucket:
                return 0
            cutoff = time.time() - window_seconds
            return len([t for t in bucket["timestamps"] if t > cutoff])

    async def reset(self, scope: str, identifier: str) -> None:
        """Reset rate limit for a specific scope+identifier."""
        if self._redis_enabled and self._redis:
            try:
                pattern = f"{self._prefix}rl:{scope}:{identifier}:*"
                keys = await self._redis.keys(pattern)
                if keys:
                    await self._redis.delete(*keys)
            except Exception:
                pass

        with self._lock:
            prefix = f"{self._prefix}rl:{scope}:{identifier}:"
            expired = [k for k in self._buckets if k.startswith(prefix)]
            for k in expired:
                del self._buckets[k]
