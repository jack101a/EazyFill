from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.middleware.rate_limit_middleware import RateLimitMiddleware


def _settings(rpm=2, burst=0):
    return SimpleNamespace(rate_limit=SimpleNamespace(requests_per_minute=rpm, burst=burst))


def _app(settings=None, custom_limit=None, rate_limiter=None):
    app = FastAPI()
    app.state.container = SimpleNamespace(db=MagicMock())
    app.state.container.db.get_api_key_rate_limit.return_value = custom_limit
    if rate_limiter is not None:
        app.state.container.rate_limiter = rate_limiter

    app.add_middleware(RateLimitMiddleware, settings=settings or _settings())

    @app.middleware("http")
    async def fake_auth(request: Request, call_next):
        key = request.headers.get("x-api-key", "1")
        request.state.api_key_record = {"id": int(key), "user_id": int(key)}
        request.state.api_key = key
        request.state.is_user_key = False
        return await call_next(request)

    @app.get("/v1/auth/verify")
    async def verify():
        return {"ok": True}

    @app.get("/v1/userscripts/sync")
    async def userscripts_sync():
        return {"scripts": []}

    @app.post("/v1/solve")
    async def solve():
        return {"ok": True}

    return app


def test_sync_endpoints_do_not_consume_solve_limit():
    client = TestClient(_app(_settings(rpm=2, burst=0)))

    for _ in range(5):
        assert client.get("/v1/auth/verify", headers={"x-api-key": "1"}).status_code == 200
        assert client.get("/v1/userscripts/sync", headers={"x-api-key": "1"}).status_code == 200

    assert client.post("/v1/solve", headers={"x-api-key": "1"}).status_code == 200
    assert client.post("/v1/solve", headers={"x-api-key": "1"}).status_code == 200
    assert client.post("/v1/solve", headers={"x-api-key": "1"}).status_code == 429


def test_rate_limit_is_per_key_not_shared_ip():
    client = TestClient(_app(_settings(rpm=1, burst=0)))

    assert client.post("/v1/solve", headers={"x-api-key": "1"}).status_code == 200
    assert client.post("/v1/solve", headers={"x-api-key": "1"}).status_code == 429

    assert client.post("/v1/solve", headers={"x-api-key": "2"}).status_code == 200


def test_custom_key_rate_limit_still_applies():
    client = TestClient(_app(
        _settings(rpm=10, burst=0),
        custom_limit={"requests_per_minute": 1, "burst": 0},
    ))

    assert client.post("/v1/solve", headers={"x-api-key": "1"}).status_code == 200
    assert client.post("/v1/solve", headers={"x-api-key": "1"}).status_code == 429


def test_container_rate_limiter_is_used_when_available():
    limiter = SimpleNamespace(check=AsyncMock(side_effect=[True, False]))
    client = TestClient(_app(_settings(rpm=5, burst=1), rate_limiter=limiter))

    assert client.post("/v1/solve", headers={"x-api-key": "1"}).status_code == 200
    assert client.post("/v1/solve", headers={"x-api-key": "1"}).status_code == 429
    limiter.check.assert_awaited()
    first_call = limiter.check.await_args_list[0]
    assert first_call.kwargs["scope"] == "legacy_key"
    assert first_call.kwargs["identifier"] == "1"
    assert first_call.kwargs["max_requests"] == 6
    assert first_call.kwargs["window_seconds"] == 60


def test_middleware_falls_back_to_memory_when_container_limiter_errors():
    limiter = SimpleNamespace(check=AsyncMock(side_effect=RuntimeError("redis down")))
    client = TestClient(_app(_settings(rpm=1, burst=0), rate_limiter=limiter))

    assert client.post("/v1/solve", headers={"x-api-key": "1"}).status_code == 200
    assert client.post("/v1/solve", headers={"x-api-key": "1"}).status_code == 429
