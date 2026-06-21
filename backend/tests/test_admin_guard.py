"""Tests for admin dashboard authentication guard."""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.requests import Request as StarletteRequest


def _create_admin_app(settings):
    """Create app with a test admin endpoint using _admin_guard."""
    from app.api.admin_routes.utils import _admin_guard

    app = FastAPI()
    app.state.container = MagicMock()
    app.state.container.settings = settings

    @app.get("/admin/api/test")
    async def admin_test(request: Request):
        denied = _admin_guard(request)
        if denied:
            return denied
        return JSONResponse({"ok": True})

    return app


def _create_admin_login_app(settings):
    """Create app with the admin login route mounted."""
    from app.api.admin_routes import auth

    app = FastAPI()
    app.state.container = MagicMock()
    app.state.container.settings = settings
    app.include_router(auth.router, prefix="/admin")
    return app


@pytest.fixture
def admin_settings():
    s = MagicMock()
    s.auth.admin_username = "admin"
    s.auth.admin_password = "password123"
    s.auth.hash_salt = "test-salt"
    s.auth.admin_token = "test-admin-token"
    return s


class TestAdminGuard:
    """Admin cookie authentication."""

    def test_no_cookie_returns_redirect(self, admin_settings):
        """Without auth cookie, admin routes should be denied."""
        app = _create_admin_app(admin_settings)
        client = TestClient(app)
        r = client.get("/admin/api/test", follow_redirects=False)
        assert r.status_code == 303

    def test_wrong_cookie_returns_redirect(self, admin_settings):
        app = _create_admin_app(admin_settings)
        client = TestClient(app)
        r = client.get("/admin/api/test", cookies={"admin_session": "wrong-token"}, follow_redirects=False)
        assert r.status_code == 303

    def test_valid_server_side_cookie_allows_access(self, admin_settings):
        from app.api.admin_routes.utils import _admin_session_cookie

        app = _create_admin_app(admin_settings)
        client = TestClient(app)
        scope = {
            "type": "http",
            "app": app,
            "method": "GET",
            "path": "/admin/api/test",
            "headers": [],
            "query_string": b"",
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "scheme": "http",
        }
        token = _admin_session_cookie(StarletteRequest(scope))
        r = client.get("/admin/api/test", cookies={"admin_session": token})
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    def test_admin_api_write_requires_admin_header(self, admin_settings):
        from app.api.admin_routes.utils import _admin_guard, _admin_session_cookie

        app = _create_admin_app(admin_settings)

        @app.post("/admin/api/write")
        async def admin_write(request: Request):
            denied = _admin_guard(request)
            if denied:
                return denied
            return JSONResponse({"ok": True})

        client = TestClient(app)
        scope = {
            "type": "http",
            "app": app,
            "method": "POST",
            "path": "/admin/api/write",
            "headers": [],
            "query_string": b"",
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "scheme": "http",
        }
        token = _admin_session_cookie(StarletteRequest(scope))
        blocked = client.post("/admin/api/write", cookies={"admin_session": token})
        assert blocked.status_code == 403
        allowed = client.post("/admin/api/write", cookies={"admin_session": token}, headers={"x-admin-api": "1"})
        assert allowed.status_code == 200

    def test_admin_login_page_renders(self, admin_settings):
        app = _create_admin_login_app(admin_settings)
        client = TestClient(app)

        response = client.get("/admin/login")

        assert response.status_code == 200
        assert "EazyFill Admin" in response.text
