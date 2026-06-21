"""Tests for AuthMiddleware — dual-key authentication flow."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.middleware.auth_middleware import AuthMiddleware


def _create_test_app(key_service, settings, user_key_svc=None):
    """Create a minimal FastAPI app with AuthMiddleware for testing."""
    app = FastAPI()
    app.add_middleware(AuthMiddleware, settings=settings, key_service=key_service)

    if user_key_svc:
        app.state.user_key_service = user_key_svc

    @app.get("/v1/test")
    async def test_endpoint(request: Request):
        record = getattr(request.state, "api_key_record", None)
        return {"ok": True, "key_id": record.get("id") if record else None}

    @app.get("/v1/key/create")
    async def key_create_endpoint(request: Request):
        record = getattr(request.state, "api_key_record", None)
        return {"ok": True, "key_type": record.get("key_type") if record else None}

    @app.get("/v1/field-mappings")
    async def field_mappings():
        return {"public": True}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


@pytest.fixture
def settings():
    s = MagicMock()
    s.auth.hash_salt = "test-salt"
    s.auth.admin_token = "test-admin-token"
    s.auth.key_prefix = "SK-"
    return s


@pytest.fixture
def key_service():
    ks = MagicMock()
    ks.validate_key.return_value = None
    ks.validate_or_bind_device.return_value = True
    ks.get_entitlements.return_value = {}
    return ks


class TestPublicPaths:
    """Only non-v1 health paths should bypass API-key authentication."""

    def test_health_no_auth(self, settings, key_service):
        app = _create_test_app(key_service, settings)
        client = TestClient(app)
        r = client.get("/health")
        assert r.status_code == 200

    def test_field_mappings_requires_auth(self, settings, key_service):
        app = _create_test_app(key_service, settings)
        client = TestClient(app)
        r = client.get("/v1/field-mappings")
        assert r.status_code == 401
        assert r.json()["error_code"] == "invalid_key"


class TestLegacyKey:
    """Legacy API key validation."""

    def test_valid_legacy_key(self, settings, key_service):
        key_service.validate_key.return_value = {"id": 1, "name": "test", "enabled": 1}
        app = _create_test_app(key_service, settings)
        client = TestClient(app)
        r = client.get("/v1/test", headers={"x-api-key": "valid-key"})
        assert r.status_code == 200
        assert r.json()["key_id"] == 1

    def test_invalid_key_returns_401(self, settings, key_service):
        key_service.validate_key.return_value = None
        app = _create_test_app(key_service, settings)
        client = TestClient(app)
        r = client.get("/v1/test", headers={"x-api-key": "bad-key"})
        assert r.status_code == 401
        assert r.json()["error_code"] == "invalid_key"

    def test_no_key_returns_401(self, settings, key_service):
        app = _create_test_app(key_service, settings)
        client = TestClient(app)
        r = client.get("/v1/test")
        assert r.status_code == 401

    def test_device_mismatch_returns_401(self, settings, key_service):
        key_service.validate_key.return_value = {"id": 1, "name": "test", "enabled": 1}
        key_service.validate_or_bind_device.return_value = False
        app = _create_test_app(key_service, settings)
        client = TestClient(app)
        r = client.get("/v1/test", headers={"x-api-key": "key", "x-device-id": "wrong-device"})
        assert r.status_code == 401
        assert r.json()["error_code"] == "device_mismatch"


class TestUserLinkedKey:
    """User-linked key validation with fallthrough to legacy."""

    def test_user_key_valid(self, settings, key_service):
        user_key_svc = MagicMock()
        user_key_svc.validate_key.return_value = {
            "id": 10, "user_id": 5, "key_hash": "h", "status": "active",
            "key_version": 1, "user_status": "active",
        }
        user_key_svc.validate_device.return_value = True
        key_service.validate_key.return_value = {"id": 1, "name": "legacy", "enabled": 1}
        app = _create_test_app(key_service, settings, user_key_svc=user_key_svc)
        client = TestClient(app)
        with patch("app.middleware.auth_middleware.logger.info"):
            r = client.get("/v1/test", headers={"x-api-key": "user-key", "x-device-id": "dev1"})
        assert r.status_code == 200
        user_key_svc.validate_key.assert_called_once()

    def test_user_key_blocked_returns_403(self, settings, key_service):
        user_key_svc = MagicMock()
        user_key_svc.validate_key.return_value = {
            "id": 10, "user_id": 5, "key_hash": "h", "status": "active",
            "key_version": 1, "user_status": "blocked",
        }
        app = _create_test_app(key_service, settings, user_key_svc=user_key_svc)
        client = TestClient(app)
        r = client.get("/v1/test", headers={"x-api-key": "user-key"})
        assert r.status_code == 403
        assert r.json()["error_code"] == "blocked_user"

    def test_user_key_revoked_does_not_fall_through(self, settings, key_service):
        user_key_svc = MagicMock()
        user_key_svc.validate_key.return_value = {
            "id": 10, "user_id": 5, "key_hash": "h", "status": "revoked",
            "key_version": 1, "auth_error": "revoked_key",
        }
        key_service.validate_key.return_value = {"id": 1, "name": "legacy", "enabled": 1}
        app = _create_test_app(key_service, settings, user_key_svc=user_key_svc)
        client = TestClient(app)
        r = client.get("/v1/test", headers={"x-api-key": "user-key"})
        assert r.status_code == 401
        assert r.json()["error_code"] == "revoked_key"
        key_service.validate_key.assert_not_called()

    def test_user_key_expired_subscription_does_not_fall_through(self, settings, key_service):
        user_key_svc = MagicMock()
        user_key_svc.validate_key.return_value = {
            "id": 10, "user_id": 5, "key_hash": "h", "status": "active",
            "key_version": 1, "auth_error": "expired_subscription",
        }
        key_service.validate_key.return_value = {"id": 1, "name": "legacy", "enabled": 1}
        app = _create_test_app(key_service, settings, user_key_svc=user_key_svc)
        client = TestClient(app)
        r = client.get("/v1/test", headers={"x-api-key": "user-key"})
        assert r.status_code == 403
        assert r.json()["error_code"] == "expired_subscription"
        key_service.validate_key.assert_not_called()

    def test_user_key_not_found_falls_through_to_legacy(self, settings, key_service):
        user_key_svc = MagicMock()
        user_key_svc.validate_key.return_value = None
        user_key_svc.legacy_user_access.return_value = None
        key_service.validate_key.return_value = {"id": 1, "name": "legacy", "enabled": 1}
        app = _create_test_app(key_service, settings, user_key_svc=user_key_svc)
        client = TestClient(app)
        r = client.get("/v1/test", headers={"x-api-key": "legacy-key"})
        assert r.status_code == 200
        assert r.json()["key_id"] == 1

    def test_linked_legacy_key_expired_subscription_returns_403(self, settings, key_service):
        user_key_svc = MagicMock()
        user_key_svc.validate_key.return_value = None
        user_key_svc.legacy_user_access.return_value = {
            "user_id": 5,
            "user_status": "active",
            "auth_error": "expired_subscription",
        }
        key_service.validate_key.return_value = {"id": 1, "name": "legacy", "enabled": 1}
        key_service.get_entitlements.return_value = {"mobile": "+919999999999", "services": {"captcha": True}}
        app = _create_test_app(key_service, settings, user_key_svc=user_key_svc)
        client = TestClient(app)

        r = client.get("/v1/test", headers={"x-api-key": "legacy-key"})

        assert r.status_code == 403
        assert r.json()["error_code"] == "expired_subscription"
        key_service.validate_or_bind_device.assert_not_called()

    def test_linked_legacy_key_uses_user_entitlements(self, settings, key_service):
        user_key_svc = MagicMock()
        user_key_svc.validate_key.return_value = None
        user_key_svc.legacy_user_access.return_value = {
            "user_id": 5,
            "user_status": "active",
            "entitlements": {"plan_name": "Max", "services": {"captcha": True, "custom": False}},
        }
        key_service.validate_key.return_value = {"id": 1, "name": "legacy", "enabled": 1}
        app = _create_test_app(key_service, settings, user_key_svc=user_key_svc)
        client = TestClient(app)

        r = client.get("/v1/test", headers={"x-api-key": "legacy-key"})

        assert r.status_code == 200

    def test_user_key_exception_returns_503(self, settings, key_service):
        user_key_svc = MagicMock()
        user_key_svc.validate_key.side_effect = Exception("DB error")
        key_service.validate_key.return_value = {"id": 1, "name": "legacy", "enabled": 1}
        app = _create_test_app(key_service, settings, user_key_svc=user_key_svc)
        client = TestClient(app)
        r = client.get("/v1/test", headers={"x-api-key": "any-key"})
        assert r.status_code == 503
        assert r.json()["error_code"] == "auth_service_unavailable"
        key_service.validate_key.assert_not_called()


class TestAdminToken:
    """Admin token endpoints."""

    def test_valid_admin_token(self, settings, key_service):
        app = _create_test_app(key_service, settings)
        client = TestClient(app)
        r = client.get("/v1/key/create", headers={"x-admin-token": "test-admin-token"})
        assert r.status_code == 200
        assert r.json()["key_type"] == "master"

    def test_invalid_admin_token_returns_401(self, settings, key_service):
        app = _create_test_app(key_service, settings)
        client = TestClient(app)
        r = client.get("/v1/key/create", headers={"x-admin-token": "wrong"})
        assert r.status_code == 401

    def test_master_key_can_access_key_management_without_admin_token(self, settings, key_service):
        key_service.validate_key.return_value = {"id": 1, "name": "Master Key", "enabled": 1, "key_type": "master"}
        app = _create_test_app(key_service, settings)
        client = TestClient(app)
        r = client.get("/v1/key/create", headers={"x-api-key": "master-key"})
        assert r.status_code == 200
        assert r.json()["key_type"] == "master"
