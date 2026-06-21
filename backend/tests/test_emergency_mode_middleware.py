from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.emergency_mode_middleware import EmergencyModeMiddleware


def _app(mode: str = "normal") -> FastAPI:
    app = FastAPI()
    app.add_middleware(EmergencyModeMiddleware, settings=SimpleNamespace(app_mode=mode))

    @app.get("/ready")
    async def ready():
        return {"status": "ok"}

    @app.post("/v1/solve")
    async def solve():
        return {"ok": True}

    @app.post("/v1/autofill/fill")
    async def autofill_fill():
        return {"ok": True}

    @app.post("/v1/extension/error-report")
    async def extension_error_report():
        return {"ok": True}

    @app.post("/v1/report")
    async def captcha_report():
        return {"ok": True}

    @app.post("/api/payments/razorpay/order")
    async def razorpay_order():
        return {"ok": True}

    @app.post("/api/webhooks/razorpay")
    async def razorpay_webhook():
        return {"ok": True}

    @app.post("/admin/api/users")
    async def create_user():
        return {"ok": True}

    @app.put("/admin/api/plans/1")
    async def update_plan():
        return {"ok": True}

    return app


def test_normal_mode_does_not_block_writes():
    client = TestClient(_app("normal"))

    response = client.post("/admin/api/users")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_emergency_mode_allows_safe_extension_workflows():
    client = TestClient(_app("emergency"))

    assert client.get("/ready").status_code == 200
    assert client.post("/v1/solve").status_code == 200
    assert client.post("/v1/autofill/fill").status_code == 200
    assert client.post("/v1/extension/error-report").status_code == 200


def test_emergency_mode_blocks_permanent_business_writes():
    client = TestClient(_app("emergency"))

    for path in (
        "/admin/api/users",
        "/admin/api/plans/1",
        "/api/payments/razorpay/order",
        "/api/webhooks/razorpay",
        "/v1/report",
    ):
        response = client.post(path) if not path.endswith("/1") else client.put(path)
        assert response.status_code == 503
        assert response.json()["error_code"] == "emergency_mode_read_only"
        assert response.headers["retry-after"] == "300"
