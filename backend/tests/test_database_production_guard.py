from unittest.mock import MagicMock

import pytest

from app.core.database import Database


def _settings(tmp_path):
    settings = MagicMock()
    settings.storage.sqlite_path = str(tmp_path / "app.db")
    settings.storage.db_type = "sqlite"
    settings.auth.hash_salt = "test-salt"
    settings.auth.admin_token = "test-admin-token"
    settings.auth.default_expiry_days = 30
    settings.auth.key_prefix = "SK-"
    settings.auth.key_length = 32
    return settings


def test_production_gateway_refuses_sqlite_legacy_db(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("INSTANCE_ID", "node-a-gateway-1")
    monkeypatch.setenv("LEGACY_DB_TYPE", "sqlite")
    monkeypatch.delenv("ALLOW_PRODUCTION_SQLITE_GATEWAY", raising=False)

    db = Database(_settings(tmp_path))

    with pytest.raises(RuntimeError, match="LEGACY_DB_TYPE=sqlite"):
        db.init()


def test_production_gateway_sqlite_requires_explicit_override(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("INSTANCE_ID", "node-a-gateway-1")
    monkeypatch.setenv("LEGACY_DB_TYPE", "sqlite")
    monkeypatch.setenv("ALLOW_PRODUCTION_SQLITE_GATEWAY", "true")

    db = Database(_settings(tmp_path))

    db.init()
