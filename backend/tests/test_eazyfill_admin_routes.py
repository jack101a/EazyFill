from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.admin_routes import eazyfill
from app.core.db import Base
from app.core.models import (
    PaymentRecord,
    PaymentWebhookEvent,
    SubscriptionPlan,
    UsageCycle,
    User,
    UserApiKey,
    UserApiKeyDevice,
    UserSubscription,
)


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _app(Session):
    app = FastAPI()
    app.state.container = SimpleNamespace(
        settings=SimpleNamespace(
            auth=SimpleNamespace(admin_username="admin", admin_password="password", hash_salt="salt", admin_token="token"),
            redis=SimpleNamespace(prefix="test:", enabled=False),
        )
    )
    app.include_router(eazyfill.router, prefix="/admin")
    return app


def _seed(Session):
    session = Session()
    now = datetime.now(timezone.utc)
    try:
        plan = SubscriptionPlan(
            code="basic",
            name="Basic",
            monthly_limit=10,
            duration_days=30,
            price_amount=14900,
            currency="INR",
            is_active=True,
        )
        user = User(full_name="Eazy User", mobile_number="9999999999", status="active")
        session.add_all([plan, user])
        session.flush()
        sub = UserSubscription(
            user_id=user.id,
            plan_id=plan.id,
            status="active",
            monthly_limit_snapshot=10,
            start_at=now,
            end_at=now + timedelta(days=30),
            current_cycle_start_at=now,
            current_cycle_end_at=now + timedelta(days=30),
        )
        key = UserApiKey(
            user_id=user.id,
            key_hash="hash",
            key_prefix_display="fp_test...",
            status="active",
            issued_at=now,
        )
        payment = PaymentRecord(
            user_id=user.id,
            plan_id=plan.id,
            payment_method="razorpay",
            payment_provider="razorpay",
            amount=14900,
            currency="INR",
            status="approved",
        )
        session.add_all([sub, key, payment])
        session.flush()
        cycle = UsageCycle(
            user_id=user.id,
            subscription_id=sub.id,
            cycle_start_at=now,
            cycle_end_at=now + timedelta(days=30),
            monthly_limit=10,
            used_count=10,
            blocked_at_limit=True,
        )
        device_a = UserApiKeyDevice(
            api_key_id=key.id,
            device_fingerprint="device-a",
            device_name="Chrome",
            status="active",
            first_seen_at=now,
            last_seen_at=now,
        )
        device_b = UserApiKeyDevice(
            api_key_id=key.id,
            device_fingerprint="device-b",
            device_name="Firefox",
            status="active",
            first_seen_at=now,
            last_seen_at=now,
        )
        webhook = PaymentWebhookEvent(
            provider="razorpay",
            event_id="evt_failed",
            event_type="payment.failed",
            payment_id=payment.id,
            status="failed",
            payload_json="{}",
            error_message="No matching payment",
            received_at=now,
        )
        session.add_all([cycle, device_a, device_b, webhook])
        session.commit()
        return int(user.id)
    finally:
        session.close()


def test_eazyfill_admin_overview_support_and_abuse(monkeypatch):
    Session = _session_factory()
    user_id = _seed(Session)
    monkeypatch.setattr(eazyfill, "get_session", Session)
    monkeypatch.setenv("ADMIN_TRUST_PROXY_IDENTITY", "1")
    app = _app(Session)
    client = TestClient(app)
    headers = {"x-auth-request-user": "admin@example.test", "accept": "application/json"}

    overview = client.get("/admin/api/eazyfill/overview", headers=headers)
    assert overview.status_code == 200
    assert overview.json()["users"]["active"] == 1
    assert overview.json()["billing"]["approved_revenue"]["INR"] == 14900
    assert overview.json()["usage"]["quota_risk_users"] == 1

    support = client.get(f"/admin/api/eazyfill/users/{user_id}/support", headers=headers)
    assert support.status_code == 200
    assert support.json()["user"]["full_name"] == "Eazy User"
    assert len(support.json()["devices"]) == 2

    abuse = client.get("/admin/api/eazyfill/abuse", headers=headers)
    assert abuse.status_code == 200
    assert abuse.json()["quota_exhausted"][0]["user_id"] == user_id
    assert abuse.json()["multi_device_keys"][0]["active_device_count"] == 2
    assert abuse.json()["failed_webhooks"][0]["event_id"] == "evt_failed"

    legacy_overview = client.get("/admin/api/flowpilot/overview", headers=headers)
    assert legacy_overview.status_code == 200
    assert legacy_overview.json()["users"]["active"] == 1
