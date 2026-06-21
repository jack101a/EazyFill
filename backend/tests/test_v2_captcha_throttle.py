import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api.v2_routes import router
from app.api.v2_routes.deps import V2AuthContext, validate_v2_key
from app.middleware.v2_captcha_throttle import V2CaptchaThrottle
from app.services.rate_limiter import RateLimiter


class FakeClock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _context(api_key: str, *, key_id: int, user_id: int, limit: int) -> V2AuthContext:
    return V2AuthContext(
        api_key=api_key,
        device_id=f"device-{user_id}",
        record={"id": key_id, "user_id": user_id, "name": api_key},
        key_kind="user",
        plan=SimpleNamespace(
            rate_limit_rpm=limit,
            rate_limit_burst=0,
            allowed_services={"captcha": True},
        ),
    )


def _app(*, limit: int, clock: FakeClock, max_memory_buckets: int = 100) -> FastAPI:
    app = FastAPI()
    credit_service = MagicMock()
    credit_service.reserve_captcha.return_value = {
        "allowed": True,
        "used": 1,
        "limit": 500,
        "cycle_id": 9,
    }
    credit_service.get_balance.return_value = {
        "captcha": {
            "used_today": 1,
            "daily_limit": 500,
            "remaining": 499,
            "resets_at": "2026-07-01T00:00:00",
        },
        "autofill": {},
        "scripts": {},
        "sync": {},
    }
    app.state.container = SimpleNamespace(
        settings=SimpleNamespace(
            rate_limit=SimpleNamespace(requests_per_minute=limit, burst=0),
        ),
        db=SimpleNamespace(get_field_mapped_model=MagicMock(return_value={"ai_model_filename": "login_captcha.onnx"})),
        credit_service=credit_service,
        solver_service=SimpleNamespace(
            submit_captcha=AsyncMock(
                return_value={"result": "X7K2", "processing_ms": 10, "model_used": "onnx"}
            ),
        ),
        usage_service=MagicMock(),
    )
    app.state.v2_captcha_throttle = V2CaptchaThrottle(
        clock=clock,
        max_memory_buckets=max_memory_buckets,
    )
    app.include_router(router)

    async def override_validate_v2_key(request: Request) -> V2AuthContext:
        api_key = request.headers.get("x-api-key", "caller-a")
        if api_key == "caller-b":
            return _context(api_key, key_id=12, user_id=102, limit=limit)
        if api_key == "caller-c":
            return _context(api_key, key_id=13, user_id=103, limit=limit)
        return _context(api_key, key_id=11, user_id=101, limit=limit)

    app.dependency_overrides[validate_v2_key] = override_validate_v2_key
    return app


def _solve(client: TestClient, api_key: str = "caller-a"):
    return client.post(
        "/v2/captcha/solve",
        headers={"X-Api-Key": api_key},
        json={
            "type": "image",
            "payload_base64": "QUJDRA==",
            "domain": "example.com",
            "field_name": "login_captcha",
        },
    )


def test_v2_captcha_throttle_allows_traffic_below_threshold():
    app = _app(limit=2, clock=FakeClock())
    client = TestClient(app)

    assert _solve(client).status_code == 200
    assert _solve(client).status_code == 200
    assert app.state.container.credit_service.reserve_captcha.call_count == 2
    assert app.state.container.solver_service.submit_captcha.await_count == 2


def test_v2_captcha_throttle_rejects_at_threshold_before_quota_reservation():
    app = _app(limit=2, clock=FakeClock())
    client = TestClient(app)

    assert _solve(client).status_code == 200
    assert _solve(client).status_code == 200
    response = _solve(client)

    assert response.status_code == 429
    assert response.json()["detail"] == {
        "error": "rate_limit_exceeded",
        "message": "Too many CAPTCHA solve requests. Retry later.",
        "retry_after_seconds": 60,
        "resets_at": "1970-01-01T00:17:40Z",
    }
    assert response.headers["retry-after"] == "60"
    assert response.headers["x-ratelimit-limit"] == "2"
    assert response.headers["x-ratelimit-remaining"] == "0"
    assert response.headers["x-ratelimit-reset"] == "1060"
    assert app.state.container.credit_service.reserve_captcha.call_count == 2
    assert app.state.container.solver_service.submit_captcha.await_count == 2


def test_v2_captcha_throttle_isolates_authenticated_callers():
    app = _app(limit=1, clock=FakeClock())
    client = TestClient(app)

    assert _solve(client, "caller-a").status_code == 200
    assert _solve(client, "caller-a").status_code == 429
    assert _solve(client, "caller-b").status_code == 200


def test_v2_captcha_throttle_resets_after_window_expiry():
    clock = FakeClock()
    app = _app(limit=1, clock=clock)
    client = TestClient(app)

    assert _solve(client).status_code == 200
    assert _solve(client).status_code == 429

    clock.advance(60)

    assert _solve(client).status_code == 200
    assert app.state.container.credit_service.reserve_captcha.call_count == 2


def test_v2_captcha_throttle_bounds_local_caller_buckets():
    app = _app(limit=1, clock=FakeClock(), max_memory_buckets=2)
    client = TestClient(app)

    assert _solve(client, "caller-a").status_code == 200
    assert _solve(client, "caller-b").status_code == 200
    assert _solve(client, "caller-c").status_code == 200

    throttle = app.state.v2_captcha_throttle
    assert len(throttle._events) == 2
    assert "v2_captcha_user:101" not in throttle._events


def test_shared_rate_limiter_memory_fallback_is_bounded(monkeypatch):
    from app.services import rate_limiter as rate_limiter_module

    monkeypatch.setattr(rate_limiter_module, "_MAX_MEMORY_BUCKETS", 2)
    settings = SimpleNamespace(
        redis=SimpleNamespace(enabled=False, prefix="test:", url="redis://unused"),
    )
    limiter = RateLimiter(settings)

    for identifier in ("caller-a", "caller-b", "caller-c"):
        assert asyncio.run(
            limiter.check(
                scope="v2_captcha_user",
                identifier=identifier,
                max_requests=1,
                window_seconds=60,
            )
        )

    assert len(limiter._buckets) == 2
