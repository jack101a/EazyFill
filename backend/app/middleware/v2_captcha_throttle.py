"""Authenticated abuse throttling for the v2 CAPTCHA solve endpoint."""

from __future__ import annotations

import hashlib
import logging
import math
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from fastapi import HTTPException, Request

_DEFAULT_REQUESTS_PER_MINUTE = 60
_DEFAULT_BURST = 10
_DEFAULT_WINDOW_SECONDS = 60
_DEFAULT_MAX_MEMORY_BUCKETS = 10_000

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ThrottleDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int
    reset_at_epoch: int


class V2CaptchaThrottle:
    """Plan-aware CAPTCHA limiter with a bounded local fallback."""

    def __init__(
        self,
        *,
        window_seconds: int = _DEFAULT_WINDOW_SECONDS,
        max_memory_buckets: int = _DEFAULT_MAX_MEMORY_BUCKETS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._window_seconds = max(1, int(window_seconds))
        self._max_memory_buckets = max(1, int(max_memory_buckets))
        self._clock = clock
        self._events: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.RLock()
        self._last_prune = 0.0

    async def check(self, request: Request, ctx) -> ThrottleDecision:
        container = getattr(request.app.state, "container", None)
        limit = self._request_limit(container, ctx)
        scope, identifier = self._caller_identity(ctx)
        now = self._clock()

        limiter = getattr(container, "rate_limiter", None) if container is not None else None
        if limiter is not None:
            try:
                allowed = await limiter.check(
                    scope=scope,
                    identifier=identifier,
                    max_requests=limit,
                    window_seconds=self._window_seconds,
                )
                retry_after = 0 if allowed else self._window_seconds
                return ThrottleDecision(
                    allowed=allowed,
                    limit=limit,
                    remaining=max(0, limit - 1) if allowed else 0,
                    retry_after_seconds=retry_after,
                    reset_at_epoch=math.ceil(now + retry_after),
                )
            except Exception as exc:
                logger.warning(
                    "v2_captcha_distributed_throttle_failed_fallback_memory",
                    extra={
                        "context": {
                            "scope": scope,
                            "identifier": identifier,
                            "error": str(exc),
                        },
                    },
                )

        return self._check_memory(f"{scope}:{identifier}", limit, now)

    def _check_memory(self, caller_key: str, limit: int, now: float) -> ThrottleDecision:
        with self._lock:
            self._prune(now)
            events = self._events.get(caller_key)
            if events is None:
                if len(self._events) >= self._max_memory_buckets:
                    self._events.popitem(last=False)
                events = deque()
                self._events[caller_key] = events
            else:
                self._events.move_to_end(caller_key)

            cutoff = now - self._window_seconds
            while events and events[0] <= cutoff:
                events.popleft()

            if len(events) >= limit:
                retry_after = max(1, math.ceil(events[0] + self._window_seconds - now))
                return ThrottleDecision(
                    allowed=False,
                    limit=limit,
                    remaining=0,
                    retry_after_seconds=retry_after,
                    reset_at_epoch=math.ceil(now + retry_after),
                )

            events.append(now)
            return ThrottleDecision(
                allowed=True,
                limit=limit,
                remaining=max(0, limit - len(events)),
                retry_after_seconds=0,
                reset_at_epoch=math.ceil(events[0] + self._window_seconds),
            )

    def _prune(self, now: float) -> None:
        if (
            now - self._last_prune < self._window_seconds
            and len(self._events) < self._max_memory_buckets
        ):
            return
        self._last_prune = now
        cutoff = now - self._window_seconds
        expired = [
            key
            for key, events in self._events.items()
            if not events or events[-1] <= cutoff
        ]
        for key in expired:
            self._events.pop(key, None)

    @staticmethod
    def _caller_identity(ctx) -> tuple[str, str]:
        user_id = getattr(ctx, "user_id", None)
        if user_id:
            return "v2_captcha_user", str(user_id)

        key_id = getattr(ctx, "key_id", None)
        if key_id:
            return "v2_captcha_key", str(key_id)

        device_id = str(getattr(ctx, "device_id", "") or "unknown")
        device_hash = hashlib.sha256(device_id.encode("utf-8")).hexdigest()[:32]
        return "v2_captcha_device", device_hash

    @staticmethod
    def _request_limit(container, ctx) -> int:
        rate_limit = getattr(getattr(container, "settings", None), "rate_limit", None)
        default_rpm = int(
            getattr(rate_limit, "requests_per_minute", _DEFAULT_REQUESTS_PER_MINUTE)
            or _DEFAULT_REQUESTS_PER_MINUTE
        )
        default_burst = int(getattr(rate_limit, "burst", _DEFAULT_BURST) or 0)

        plan = getattr(ctx, "plan", None)
        rpm = int(getattr(plan, "rate_limit_rpm", default_rpm) or default_rpm)
        raw_burst = getattr(plan, "rate_limit_burst", default_burst)
        burst = int(raw_burst if raw_burst is not None else default_burst)
        return max(1, rpm) + max(0, burst)


async def enforce_v2_captcha_throttle(request: Request, ctx) -> None:
    """Reject abusive authenticated solve traffic before quota reservation."""

    throttle = getattr(request.app.state, "v2_captcha_throttle", None)
    if throttle is None:
        throttle = V2CaptchaThrottle()
        request.app.state.v2_captcha_throttle = throttle

    decision = await throttle.check(request, ctx)
    if decision.allowed:
        return

    resets_at = datetime.fromtimestamp(
        decision.reset_at_epoch,
        tz=timezone.utc,
    ).isoformat().replace("+00:00", "Z")
    raise HTTPException(
        status_code=429,
        detail={
            "error": "rate_limit_exceeded",
            "message": "Too many CAPTCHA solve requests. Retry later.",
            "retry_after_seconds": decision.retry_after_seconds,
            "resets_at": resets_at,
        },
        headers={
            "Retry-After": str(decision.retry_after_seconds),
            "X-RateLimit-Limit": str(decision.limit),
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(decision.reset_at_epoch),
        },
    )
