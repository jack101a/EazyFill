from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.emergency_mode_middleware import EmergencyModeMiddleware


def _client(mode: str) -> TestClient:
    app = FastAPI()
    app.add_middleware(EmergencyModeMiddleware, settings=SimpleNamespace(app_mode=mode))

    @app.get("/health/public")
    async def public_health():
        return {"ok": True}

    @app.get("/v1/auth/verify")
    async def verify():
        return {"valid": True}

    @app.post("/v1/solve")
    async def solve():
        return {"ok": True}

    @app.post("/admin/api/keys/create")
    async def create_key():
        return {"ok": True}

    return TestClient(app)


def test_standby_allows_public_health_but_blocks_api_traffic():
    client = _client("standby")

    assert client.get("/health/public").status_code == 200

    response = client.get("/v1/auth/verify")

    assert response.status_code == 503
    assert response.json()["error_code"] == "standby_not_active"


def test_recovery_blocks_public_api_traffic():
    response = _client("recovery").get("/v1/auth/verify")

    assert response.status_code == 503
    assert response.json()["mode"] == "recovery"


def test_remote_primary_db_allows_writes():
    response = _client("remote_primary_db").post("/admin/api/keys/create")

    assert response.status_code == 200


def test_failover_readonly_allows_existing_solve_but_blocks_admin_writes():
    client = _client("failover_readonly")

    assert client.get("/v1/auth/verify").status_code == 200
    assert client.post("/v1/solve").status_code == 200

    response = client.post("/admin/api/keys/create")

    assert response.status_code == 503
    assert response.json()["error_code"] == "failover_read_only"


def test_legacy_emergency_maps_to_failover_readonly_behavior():
    response = _client("emergency").post("/admin/api/keys/create")

    assert response.status_code == 503
    assert response.json()["mode"] == "emergency"
