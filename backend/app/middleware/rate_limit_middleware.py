"""Per-key rate limiting for heavy API actions."""

from __future__ import annotations

import time
from collections import defaultdict, deque
import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import Settings

logger = logging.getLogger(__name__)

# How often (seconds) to sweep stale buckets from the event dict.
_BUCKET_PRUNE_INTERVAL = 120
_RATE_LIMITED_PATHS = {
    "/v1/solve",
    "/v1/autofill/fill",
    "/v1/report",
    "/v1/autofill/proposals",
    "/v1/field-mappings/propose",
}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate-limit expensive authenticated actions by API key.

    Lightweight sync/config endpoints intentionally bypass this middleware so
    extension refreshes do not consume captcha/automation quota.
    """

    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self._rpm = settings.rate_limit.requests_per_minute
        self._burst = max(0, int(settings.rate_limit.burst))
        self._window_seconds = 60
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._last_prune: float = 0.0

    def _prune_buckets(self, now: float) -> None:
        """Remove empty or fully-expired deques to prevent memory leaks."""
        if now - self._last_prune < _BUCKET_PRUNE_INTERVAL:
            return
        self._last_prune = now
        dead = [
            k for k, q in self._events.items()
            if not q or (now - q[-1]) > self._window_seconds
        ]
        for k in dead:
            del self._events[k]

    def _memory_allowed(self, scope: str, key_id: int, max_requests: int, now: float) -> bool:
        self._prune_buckets(now)
        key_queue = self._events[f"{scope}:{key_id}"]
        while key_queue and (now - key_queue[0]) > self._window_seconds:
            key_queue.popleft()
        if len(key_queue) >= max_requests:
            return False
        key_queue.append(now)
        return True

    async def _rate_limit_allowed(self, container, scope: str, key_id: int, max_requests: int, now: float) -> bool:
        limiter = getattr(container, "rate_limiter", None) if container is not None else None
        if limiter is not None:
            try:
                return await limiter.check(
                    scope=scope,
                    identifier=str(key_id),
                    max_requests=max_requests,
                    window_seconds=self._window_seconds,
                )
            except Exception as exc:
                logger.warning(
                    "distributed_rate_limiter_failed_fallback_memory",
                    extra={"context": {"scope": scope, "key_id": key_id, "error": str(exc)}},
                )
        return self._memory_allowed(scope, key_id, max_requests, now)

    async def dispatch(self, request: Request, call_next):
        """Reject requests that exceed window quota."""

        if request.url.path not in _RATE_LIMITED_PATHS:
            return await call_next(request)

        key_record = getattr(request.state, "api_key_record", None)
        key_id = int(key_record.get("id")) if key_record else None
        if key_id is None:
            return await call_next(request)
        now = time.time()

        # Per-key limiter with optional DB override
        key_rpm = self._rpm
        key_burst = self._burst
        container = getattr(request.app.state, "container", None)
        if key_id is not None and container is not None:
            if getattr(request.state, "is_user_key", False) and key_record:
                custom = self._get_user_plan_rate_limit(key_record)
            else:
                custom = container.db.get_api_key_rate_limit(key_id)
            if custom:
                key_rpm = int(custom.get("requests_per_minute", key_rpm))
                key_burst = int(custom.get("burst", key_burst))

        scope = "user_key" if getattr(request.state, "is_user_key", False) else "legacy_key"
        if not await self._rate_limit_allowed(container, scope, key_id, key_rpm + key_burst, now):
            return JSONResponse({"detail": "api key rate limit exceeded"}, status_code=429)

        return await call_next(request)

    def _get_user_plan_rate_limit(self, key_record: dict) -> dict[str, int] | None:
        user_id = key_record.get("user_id")
        if not user_id:
            return None
        try:
            from app.core.db import get_session
            from app.core.models import SubscriptionPlan, UserSubscription

            session = get_session()
            try:
                sub = (
                    session.query(UserSubscription)
                    .filter(
                        UserSubscription.user_id == int(user_id),
                        UserSubscription.status == "active",
                    )
                    .order_by(UserSubscription.created_at.desc())
                    .first()
                )
                if not sub:
                    return None
                plan = session.query(SubscriptionPlan).filter(SubscriptionPlan.id == sub.plan_id).first()
                if not plan:
                    return None
                return {
                    "requests_per_minute": int(plan.rate_limit_rpm or self._rpm),
                    "burst": int(getattr(plan, "rate_limit_burst", self._burst) or self._burst),
                }
            finally:
                session.close()
        except Exception:
            return None
