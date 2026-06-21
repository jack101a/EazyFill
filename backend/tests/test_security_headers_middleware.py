from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.security_headers_middleware import SecurityHeadersMiddleware


def test_security_headers_are_added():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/admin/")
    async def admin_page():
        return {"ok": True}

    response = TestClient(app).get("/admin/")
    assert response.status_code == 200
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"


def test_public_static_extension_artifacts_are_not_served():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/static/extensions/eazyfill_extension.zip")
    async def extension_zip():
        return {"leaked": True}

    response = TestClient(app).get("/static/extensions/eazyfill_extension.zip")
    assert response.status_code == 404
