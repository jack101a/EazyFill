import asyncio
from types import SimpleNamespace

from app.services.readiness_service import readiness_payload


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, _sql):
        return self

    def fetchone(self):
        return (1,)


class _FailingDb:
    def connect(self):
        raise RuntimeError("database locked")


class _HealthyDb:
    def connect(self):
        return _Connection()


class _StaticHealth:
    def __init__(self, payload):
        self._payload = payload

    async def health(self):
        return self._payload


def _container(db, solver_payload=None, limiter_payload=None):
    return SimpleNamespace(
        settings=SimpleNamespace(storage=SimpleNamespace(db_type="sqlite")),
        db=db,
        solver_service=_StaticHealth(solver_payload or {"status": "ok", "critical": False}),
        rate_limiter=_StaticHealth(limiter_payload or {"status": "ok", "critical": False}),
    )


def test_readiness_is_ok_when_dependencies_are_healthy():
    payload, status_code = asyncio.run(readiness_payload(_container(_HealthyDb()), version="test"))

    assert status_code == 200
    assert payload["status"] == "ok"
    assert payload["mode"] == "normal"
    assert payload["checks"]["database"]["status"] == "ok"
    assert payload["checks"]["orm_database"]["status"] == "disabled"


def test_readiness_returns_503_when_database_fails():
    payload, status_code = asyncio.run(readiness_payload(_container(_FailingDb()), version="test"))

    assert status_code == 503
    assert payload["status"] == "error"
    assert payload["checks"]["database"]["critical"] is True


def test_readiness_degrades_for_noncritical_services():
    container = _container(
        _HealthyDb(),
        solver_payload={"status": "degraded", "critical": False, "backend": "redis"},
    )

    payload, status_code = asyncio.run(readiness_payload(container, version="test"))

    assert status_code == 200
    assert payload["status"] == "degraded"
    assert payload["checks"]["solver_queue"]["backend"] == "redis"


def test_readiness_reports_container_app_mode():
    container = _container(_HealthyDb())
    container.settings.app_mode = "emergency"

    payload, status_code = asyncio.run(readiness_payload(container, version="test"))

    assert status_code == 200
    assert payload["mode"] == "emergency"
