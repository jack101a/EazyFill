from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request as StarletteRequest

from app.core.database import Database


def _settings(tmp_path):
    settings = MagicMock()
    settings.storage.sqlite_path = str(tmp_path / "app.db")
    settings.storage.db_type = "sqlite"
    settings.auth.hash_salt = "test-salt"
    settings.auth.admin_token = "test-admin-token"
    settings.auth.admin_username = "admin"
    settings.auth.admin_password = "password123"
    settings.auth.default_expiry_days = 30
    settings.auth.key_prefix = "SK-"
    settings.auth.key_length = 32
    return settings


def _db(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    monkeypatch.setattr("app.core.repositories.api_keys.get_settings", lambda: settings)
    db = Database(settings)
    db.init()
    return db


def test_master_key_can_be_deactivated_without_rotation_or_auto_reactivation(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    created = db.get_master_key_info()
    from app.core.security import hash_api_key

    assert db.is_master_key_hash(hash_api_key(created["key"], "test-salt")) is True

    disabled = db.set_master_key_enabled(False)
    ensured = db.ensure_master_key()

    assert disabled["id"] == created["id"]
    assert disabled["key"] == created["key"]
    assert disabled["enabled"] is False
    assert ensured["id"] == created["id"]
    assert ensured["key"] == created["key"]
    assert ensured["enabled"] is False
    assert db.is_master_key_hash(hash_api_key(created["key"], "test-salt")) is False


def test_master_key_reactivation_preserves_same_key(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    created = db.get_master_key_info()

    db.set_master_key_enabled(False)
    enabled = db.set_master_key_enabled(True)

    assert enabled["id"] == created["id"]
    assert enabled["key"] == created["key"]
    assert enabled["enabled"] is True


def test_disabled_master_key_is_not_deleted_by_revoked_key_cleanup(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    created = db.get_master_key_info()

    db.set_master_key_enabled(False)
    deleted_count = db.delete_revoked_api_keys()
    after = db.get_master_key_info()

    assert deleted_count == 0
    assert after["id"] == created["id"]
    assert after["key"] == created["key"]
    assert after["enabled"] is False


def test_master_key_repair_preserves_disabled_setting(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    created = db.get_master_key_info()

    db.set_master_key_enabled(False)
    with db.api_keys.connect() as conn:
        conn.execute("DELETE FROM api_keys WHERE id = ?", (created["id"],))
        conn.commit()

    repaired = db.ensure_master_key()

    assert repaired["key"] == created["key"]
    assert repaired["enabled"] is False


def test_admin_master_key_toggle_endpoint_changes_active_state(tmp_path, monkeypatch):
    from app.api.admin_routes import keys as keys_routes
    from app.api.admin_routes.utils import _admin_session_cookie

    settings = _settings(tmp_path)
    monkeypatch.setattr("app.core.repositories.api_keys.get_settings", lambda: settings)
    db = Database(settings)
    db.init()

    app = FastAPI()
    container = MagicMock()
    container.settings = settings
    container.db = db
    app.state.container = container
    app.include_router(keys_routes.router, prefix="/admin")
    client = TestClient(app)
    scope = {
        "type": "http",
        "app": app,
        "method": "POST",
        "path": "/admin/api/master-key/enabled",
        "headers": [],
        "query_string": b"",
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "scheme": "http",
    }
    token = _admin_session_cookie(StarletteRequest(scope))

    disabled = client.post(
        "/admin/api/master-key/enabled",
        json={"enabled": "false"},
        cookies={"admin_session": token},
        headers={"x-admin-api": "1"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["master_key"]["enabled"] is False

    enabled = client.post(
        "/admin/api/master-key/enabled",
        json={"enabled": "true"},
        cookies={"admin_session": token},
        headers={"x-admin-api": "1"},
    )
    assert enabled.status_code == 200
    assert enabled.json()["master_key"]["enabled"] is True


def test_generic_revoke_and_delete_do_not_remove_master_key(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    created = db.get_master_key_info()
    from app.core.security import hash_api_key

    assert db.revoke_api_key(hash_api_key(created["key"], "test-salt")) is False
    assert db.revoke_api_key_by_id(created["id"]) is False
    db.set_master_key_enabled(False)
    assert db.delete_revoked_api_key_by_id(created["id"]) is False

    after = db.get_master_key_info()
    assert after["id"] == created["id"]
    assert after["key"] == created["key"]
    assert after["enabled"] is False


def test_manually_created_master_key_can_be_revoked_and_deleted(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)

    manual_id = db.insert_api_key(
        name="Manual Master",
        key_hash="manual-master-hash",
        expires_at=None,
        key_type="master",
    )

    assert db.revoke_api_key_by_id(manual_id) is True
    assert db.delete_revoked_api_key_by_id(manual_id) is True


def test_admin_create_key_accepts_manual_master_key_type(tmp_path, monkeypatch):
    from app.api.admin_routes import keys as keys_routes
    from app.api.admin_routes.utils import _admin_session_cookie
    from app.services.key_service import KeyService

    settings = _settings(tmp_path)
    monkeypatch.setattr("app.core.repositories.api_keys.get_settings", lambda: settings)
    db = Database(settings)
    db.init()

    app = FastAPI()
    container = MagicMock()
    container.settings = settings
    container.db = db
    container.key_service = KeyService(db, settings)
    app.state.container = container
    app.include_router(keys_routes.router, prefix="/admin")
    client = TestClient(app)
    scope = {
        "type": "http",
        "app": app,
        "method": "POST",
        "path": "/admin/api/keys/create",
        "headers": [],
        "query_string": b"",
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "scheme": "http",
    }
    token = _admin_session_cookie(StarletteRequest(scope))

    response = client.post(
        "/admin/api/keys/create",
        data={"key_name": "Manual Master", "expiry_days": "0", "key_type": "master"},
        cookies={"admin_session": token},
        headers={"x-admin-api": "1"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["api_key"].startswith("SK-")
    with db.connect() as conn:
        row = conn.execute("SELECT key_type FROM api_keys WHERE id = ?", (payload["key_id"],)).fetchone()
    assert row["key_type"] == "master"
