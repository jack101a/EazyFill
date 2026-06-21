import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.admin_routes import captcha_proposals


class _FakeSolver:
    def __init__(self, result):
        self.result = result

    async def solve_direct(self, **kwargs):
        return {
            "result": self.result,
            "model_used": kwargs.get("model_filename") or "model.onnx",
            "processing_ms": 1,
        }


class _FakeDb:
    def __init__(self, db_path):
        self.db_path = db_path
        self.mappings = []
        self.statuses = []
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE field_mapping_proposals (
                    id INTEGER PRIMARY KEY,
                    domain TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    source_data_type TEXT NOT NULL,
                    source_selector TEXT NOT NULL,
                    target_data_type TEXT NOT NULL,
                    target_selector TEXT NOT NULL,
                    proposed_field_name TEXT NOT NULL,
                    reported_by INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE field_mappings (
                    id INTEGER PRIMARY KEY,
                    domain TEXT NOT NULL,
                    field_name TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    source_selector TEXT NOT NULL,
                    target_selector TEXT NOT NULL
                );
                CREATE TABLE retrain_samples (
                    id INTEGER PRIMARY KEY,
                    domain TEXT NOT NULL,
                    image_path TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    field_name TEXT,
                    label_text TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                INSERT INTO field_mapping_proposals (
                    id, domain, task_type, source_data_type, source_selector,
                    target_data_type, target_selector, proposed_field_name,
                    reported_by, status, created_at
                )
                VALUES (1, 'example.com', 'image', 'image', '#captcha', 'text', '#answer', 'captcha_route', 7, 'pending', 'now')
                """
            )
            conn.execute(
                """
                INSERT INTO retrain_samples (
                    id, domain, image_path, task_type, field_name, label_text, status, created_at
                )
                VALUES (1, 'example.com', 'sample.png', 'image', 'captcha_route', 'ABC123', 'queued', 'now')
                """
            )
            conn.commit()
        self.models = self

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def get_model_registry(self):
        return [{
            "id": 9,
            "ai_model_name": "Route OCR",
            "version": "v1",
            "task_type": "image",
            "ai_runtime": "onnx",
            "ai_model_filename": "route_v1.onnx",
            "status": "active",
            "lifecycle_state": "production",
        }]

    def set_field_mapping(self, **kwargs):
        self.mappings.append(kwargs)

    def mark_field_mapping_proposal_status(self, proposal_id, status):
        self.statuses.append((proposal_id, status))

    def export_master_setup(self):
        return {}


def _client(fake_db, solver):
    app = FastAPI()
    app.state.container = SimpleNamespace(
        db=fake_db,
        solver_service=solver,
        settings=SimpleNamespace(
            auth=SimpleNamespace(admin_username="admin", admin_password="password", hash_salt="salt", admin_token="token"),
            redis=SimpleNamespace(prefix="test:", enabled=False),
            storage=SimpleNamespace(sqlite_path="/tmp/eazyfill-test.db"),
        ),
    )
    app.include_router(captcha_proposals.router, prefix="/admin")
    return TestClient(app)


def _headers(monkeypatch):
    monkeypatch.setenv("ADMIN_TRUST_PROXY_IDENTITY", "1")
    return {
        "x-auth-request-user": "admin@example.test",
        "x-admin-api": "1",
        "accept": "application/json",
    }


def test_captcha_proposal_approval_rejects_model_sample_mismatch(monkeypatch, tmp_path):
    monkeypatch.setattr(captcha_proposals, "_PROJECT_ROOT", tmp_path)
    (tmp_path / "sample.png").write_bytes(b"not-an-image-but-base64-input")
    fake_db = _FakeDb(tmp_path / "test.db")

    response = _client(fake_db, _FakeSolver("WRONG")).post(
        "/admin/api/captcha/proposals/1/approve",
        headers=_headers(monkeypatch),
        json={"model_id": 9},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "model_sample_mismatch"
    assert fake_db.mappings == []
    assert fake_db.statuses == []


def test_captcha_proposal_approval_accepts_matching_sample(monkeypatch, tmp_path):
    monkeypatch.setattr(captcha_proposals, "_PROJECT_ROOT", tmp_path)
    (tmp_path / "sample.png").write_bytes(b"not-an-image-but-base64-input")
    fake_db = _FakeDb(tmp_path / "test.db")

    response = _client(fake_db, _FakeSolver("ABC123")).post(
        "/admin/api/captcha/proposals/1/approve",
        headers=_headers(monkeypatch),
        json={"model_id": 9},
    )

    assert response.status_code == 200
    assert fake_db.mappings[0]["field_name"] == "captcha_route"
    assert fake_db.mappings[0]["ai_model_id"] == 9
    assert fake_db.statuses == [(1, "approved")]
