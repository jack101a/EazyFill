import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v2_routes import router
from app.core.db import Base
from app.core.models import SubscriptionPlan, UserSession


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(
        SubscriptionPlan(
            code="free",
            name="Free",
            monthly_limit=100,
            duration_days=30,
            price_amount=0,
            currency="INR",
            is_active=True,
            allowed_services={"captcha": True, "autofill": True, "userscripts": True, "sync": True},
        )
    )
    session.commit()
    session.close()
    return Session


def _app(monkeypatch):
    from app.api.v2_routes import deps
    from app.services import account_auth_service

    Session = _session_factory()
    monkeypatch.setattr(deps, "get_session", Session)
    monkeypatch.setattr(account_auth_service, "get_session", Session)

    app = FastAPI()
    app.state.container = SimpleNamespace(
        settings=SimpleNamespace(
            server=SimpleNamespace(debug=True),
            email=SimpleNamespace(otp_dev_otp_enabled=True),
        ),
        email_service=SimpleNamespace(enabled=False),
        credit_service=SimpleNamespace(
            get_balance=MagicMock(return_value={
                "captcha": {"used_today": 0, "daily_limit": 100, "remaining": 100},
                "autofill": {},
                "scripts": {},
                "sync": {"enabled": True},
            })
        ),
    )
    app.include_router(router)
    return app, Session


def test_account_email_first_signup_profile_then_verify(monkeypatch):
    app, Session = _app(monkeypatch)
    client = TestClient(app)
    headers = {"X-EazyFill-Device-Id": "device-1"}

    start = client.post("/v2/account/start", json={"email": "newuser@gmail.com"}, headers=headers)
    assert start.status_code == 200
    assert start.json()["next_step"] == "profile"
    assert "challenge_id" not in start.json()

    profile = client.post(
        "/v2/account/profile",
        json={"email": "newuser@gmail.com", "name": "New User"},
        headers=headers,
    )
    assert profile.status_code == 200
    challenge = profile.json()
    assert challenge["next_step"] == "verify"
    assert challenge["account_mode"] == "signup"
    assert challenge["dev_otp"]

    verify = client.post(
        "/v2/account/verify",
        json={"challenge_id": challenge["challenge_id"], "otp": challenge["dev_otp"], "device_name": "Chrome"},
        headers=headers,
    )
    assert verify.status_code == 200
    body = verify.json()
    assert body["session_token"].startswith("efs_")
    assert "api_key" not in body
    assert body["user"]["email"] == "newuser@gmail.com"
    assert body["entitlements"]["cloud_sync"] is True

    refresh = client.post(
        "/v2/account/refresh",
        headers={**headers, "X-EazyFill-Session": body["session_token"]},
        json={},
    )
    assert refresh.status_code == 200
    assert refresh.json()["user"]["email"] == "newuser@gmail.com"

    session = Session()
    assert session.query(UserSession).filter(UserSession.status == "active").count() == 1


def test_account_logout_revokes_session(monkeypatch):
    app, Session = _app(monkeypatch)
    client = TestClient(app)
    headers = {"X-EazyFill-Device-Id": "device-logout"}

    start = client.post("/v2/account/start", json={"email": "logoutuser@gmail.com"}, headers=headers)
    assert start.json()["next_step"] == "profile"
    profile = client.post(
        "/v2/account/profile",
        json={"email": "logoutuser@gmail.com", "name": "Logout User"},
        headers=headers,
    )
    verify = client.post(
        "/v2/account/verify",
        json={"challenge_id": profile.json()["challenge_id"], "otp": profile.json()["dev_otp"]},
        headers=headers,
    )
    assert verify.status_code == 200

    logout = client.post(
        "/v2/account/logout",
        headers={**headers, "X-EazyFill-Session": verify.json()["session_token"]},
        json={},
    )

    assert logout.status_code == 200
    assert logout.json()["ok"] is True
    assert logout.json()["revoked"] is True
    session = Session()
    try:
        assert session.query(UserSession).filter(UserSession.status == "active").count() == 0
        assert session.query(UserSession).filter(UserSession.status == "revoked").count() == 1
    finally:
        session.close()


def test_account_logout_returns_when_revoke_is_slow(monkeypatch):
    from app.api.v2_routes import account as account_route

    app, _Session = _app(monkeypatch)

    def slow_logout(_token):
        time.sleep(0.05)
        return True

    monkeypatch.setattr(account_route.account_auth_service, "logout", slow_logout)
    monkeypatch.setattr(account_route, "LOGOUT_TIMEOUT_SECONDS", 0.01)
    started = time.perf_counter()

    response = TestClient(app).post(
        "/v2/account/logout",
        headers={"X-EazyFill-Session": "efs_slow"},
        json={},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "revoked": False}
    assert time.perf_counter() - started < 0.5


def test_account_existing_email_start_sends_otp(monkeypatch):
    app, _Session = _app(monkeypatch)
    client = TestClient(app)
    headers = {"X-EazyFill-Device-Id": "device-1"}

    first = client.post("/v2/account/start", json={"email": "existing@gmail.com"}, headers=headers)
    assert first.json()["next_step"] == "profile"
    profile = client.post(
        "/v2/account/profile",
        json={"email": "existing@gmail.com", "name": "Existing User"},
        headers=headers,
    )
    verify = client.post(
        "/v2/account/verify",
        json={"challenge_id": profile.json()["challenge_id"], "otp": profile.json()["dev_otp"]},
        headers=headers,
    )
    assert verify.status_code == 200

    second = client.post("/v2/account/start", json={"email": "existing@gmail.com"}, headers=headers)
    assert second.status_code == 200
    assert second.json()["next_step"] == "verify"
    assert second.json()["account_mode"] == "login"
    assert second.json()["dev_otp"]
