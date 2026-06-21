import asyncio
from types import SimpleNamespace

from fastapi import FastAPI
from starlette.requests import Request as StarletteRequest

from app.api.admin_routes import utils


def _request(*, redis_enabled=False):
    app = FastAPI()
    app.state.container = SimpleNamespace(
        settings=SimpleNamespace(
            redis=SimpleNamespace(
                enabled=redis_enabled,
                url="redis://example/0",
                prefix="test:",
            )
        )
    )
    scope = {
        "type": "http",
        "app": app,
        "method": "POST",
        "path": "/admin/login",
        "headers": [(b"x-forwarded-for", b"203.0.113.10")],
        "query_string": b"",
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "scheme": "http",
    }
    return StarletteRequest(scope)


def test_admin_login_memory_throttle_records_and_clears_failures():
    request = _request(redis_enabled=False)
    utils._ADMIN_LOGIN_FAILURES.clear()

    for _ in range(utils._ADMIN_LOGIN_MAX_FAILURES):
        assert asyncio.run(utils._admin_login_rate_limited(request)) is False
        asyncio.run(utils._admin_login_record_failure(request))

    assert asyncio.run(utils._admin_login_rate_limited(request)) is True
    asyncio.run(utils._admin_login_clear_failures(request))
    assert asyncio.run(utils._admin_login_rate_limited(request)) is False


class _FakePipeline:
    def __init__(self, client):
        self.client = client
        self.ops = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def zremrangebyscore(self, key, minimum, maximum):
        self.ops.append(("zremrangebyscore", key, float(minimum), float(maximum)))

    def zcard(self, key):
        self.ops.append(("zcard", key))

    def zadd(self, key, values):
        self.ops.append(("zadd", key, values))

    def expire(self, key, ttl):
        self.ops.append(("expire", key, ttl))

    async def execute(self):
        results = []
        for op in self.ops:
            name = op[0]
            key = op[1]
            if name == "zremrangebyscore":
                _name, _key, minimum, maximum = op
                self.client.data[key] = [item for item in self.client.data.get(key, []) if not minimum <= item <= maximum]
                results.append(0)
            elif name == "zcard":
                results.append(len(self.client.data.get(key, [])))
            elif name == "zadd":
                _name, _key, values = op
                self.client.data.setdefault(key, []).extend(float(score) for score in values.values())
                results.append(1)
            elif name == "expire":
                results.append(True)
        return results


class _FakeRedis:
    def __init__(self):
        self.data = {}
        self.closed = False

    def pipeline(self):
        return _FakePipeline(self)

    async def delete(self, key):
        self.data.pop(key, None)

    async def aclose(self):
        self.closed = True


def test_admin_login_redis_throttle_records_and_clears_failures(monkeypatch):
    request = _request(redis_enabled=True)
    client = _FakeRedis()

    async def fake_client(_request):
        return client

    monkeypatch.setattr(utils, "_admin_login_redis_client", fake_client)

    for _ in range(utils._ADMIN_LOGIN_MAX_FAILURES):
        assert asyncio.run(utils._admin_login_rate_limited(request)) is False
        asyncio.run(utils._admin_login_record_failure(request))

    assert asyncio.run(utils._admin_login_rate_limited(request)) is True
    asyncio.run(utils._admin_login_clear_failures(request))
    assert asyncio.run(utils._admin_login_rate_limited(request)) is False
