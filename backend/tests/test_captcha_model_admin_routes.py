from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.admin_routes import models


class _FakeDb:
    def __init__(self):
        self.mappings = []

    def get_model_registry(self):
        return [{
            "id": 1,
            "ai_model_name": "Eazy OCR",
            "version": "v1",
            "task_type": "image",
            "ai_runtime": "onnx",
            "ai_model_filename": "eazy_model_v1.onnx",
            "status": "active",
            "lifecycle_state": "production",
        }]

    def get_all_field_mappings(self):
        return self.mappings

    def set_field_mapping(self, **kwargs):
        self.mappings.append({"id": 1, **kwargs})

    def export_master_setup(self):
        return {}


def _app(fake_db):
    app = FastAPI()
    app.state.container = SimpleNamespace(
        db=fake_db,
        settings=SimpleNamespace(
            auth=SimpleNamespace(admin_username="admin", admin_password="password", hash_salt="salt", admin_token="token"),
            redis=SimpleNamespace(prefix="test:", enabled=False),
            storage=SimpleNamespace(sqlite_path="/tmp/eazyfill-test.db"),
        ),
    )
    app.include_router(models.router, prefix="/admin")
    return app


def test_captcha_model_admin_lists_and_sets_mappings(monkeypatch):
    monkeypatch.setenv("ADMIN_TRUST_PROXY_IDENTITY", "1")
    fake_db = _FakeDb()
    client = TestClient(_app(fake_db))
    headers = {
        "x-auth-request-user": "admin@example.test",
        "x-admin-api": "1",
        "accept": "application/json",
    }

    listing = client.get("/admin/api/captcha/models", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["models"][0]["ai_model_filename"] == "eazy_model_v1.onnx"
    assert "model_routes" not in listing.json()

    mapping = client.post(
        "/admin/api/captcha/mappings",
        headers=headers,
        json={
            "domain": "example.com",
            "field_name": "login_captcha",
            "task_type": "image",
            "source_selector": "#captcha-img",
            "target_selector": "#captcha-input",
            "ai_model_id": 1,
        },
    )
    assert mapping.status_code == 200
    assert fake_db.mappings[0]["field_name"] == "login_captcha"
    assert fake_db.mappings[0]["source_selector"] == "#captcha-img"


def test_captcha_model_admin_does_not_expose_domain_fallback_routes(monkeypatch):
    monkeypatch.setenv("ADMIN_TRUST_PROXY_IDENTITY", "1")
    client = TestClient(_app(_FakeDb()))
    response = client.post(
        "/admin/api/captcha/model-routes",
        headers={
            "x-auth-request-user": "admin@example.test",
            "x-admin-api": "1",
            "accept": "application/json",
        },
        json={"domain": "example.com", "ai_model_filename": "eazy_model_v1.onnx"},
    )

    assert response.status_code == 404
