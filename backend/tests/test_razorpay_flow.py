import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import webhooks
from app.api.admin_routes import payments as admin_payments
from app.core.db import Base
from app.core.models import PaymentRecord, PaymentWebhookEvent, SubscriptionPlan, User


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _settings():
    settings = MagicMock()
    settings.payment.razorpay_key_id = "rzp_test_key"
    settings.payment.razorpay_key_secret = "rzp_test_secret"
    settings.payment.razorpay_webhook_secret = "whsec_test"
    settings.payment.razorpay_order_token = "order-token"
    settings.redis.enabled = False
    settings.redis.prefix = "eazyfill:"
    settings.auth.admin_token = "test-admin-token"
    settings.auth.hash_salt = "test-salt"
    settings.auth.key_prefix = "SK-"
    settings.auth.key_length = 16
    settings.auth.default_expiry_days = 30
    return settings


def _app(Session):
    app = FastAPI()
    settings = _settings()
    app.state.container = SimpleNamespace(
        settings=settings,
        audit_service=SimpleNamespace(log=MagicMock()),
        payment_service=SimpleNamespace(activate_payment=MagicMock(return_value={"payment": {"id": 1}})),
    )
    app.include_router(webhooks.router)
    app.include_router(admin_payments.router, prefix="/admin")
    return app


def _seed_user_plan(Session):
    session = Session()
    try:
        user = User(full_name="Test User", mobile_number="+919999999999", status="pending_payment")
        plan = SubscriptionPlan(
            code="pro",
            name="Pro",
            monthly_limit=1000,
            duration_days=30,
            price_amount=50000,
            currency="INR",
            is_active=True,
        )
        session.add_all([user, plan])
        session.commit()
        return int(user.id), int(plan.id)
    finally:
        session.close()

class _FakeRazorpayResponse:
    status_code = 200
    text = ""

    def json(self):
        return {
            "id": "order_test_123",
            "amount": 50000,
            "currency": "INR",
            "status": "created",
        }


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, *, auth, json):
        assert url == "https://api.razorpay.com/v1/orders"
        assert auth == ("rzp_test_key", "rzp_test_secret")
        assert json["amount"] == 50000
        assert json["currency"] == "INR"
        assert json["notes"]["payment_id"]
        return _FakeRazorpayResponse()


def test_admin_can_create_razorpay_order_with_session_guard(monkeypatch):
    Session = _session_factory()
    user_id, plan_id = _seed_user_plan(Session)
    app = _app(Session)
    monkeypatch.setattr(webhooks, "get_session", Session)
    monkeypatch.setattr(admin_payments, "_admin_guard", lambda request: None)
    monkeypatch.setattr(webhooks.httpx, "AsyncClient", _FakeAsyncClient)

    response = TestClient(app).post(
        "/admin/api/payments/razorpay/order",
        json={"user_id": user_id, "plan_id": plan_id},
        headers={"X-Admin-API": "1"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["key_id"] == "rzp_test_key"
    assert data["order"]["id"] == "order_test_123"
    session = Session()
    try:
        payment = session.query(PaymentRecord).one()
        assert payment.payment_provider == "razorpay"
        assert payment.provider_order_id == "order_test_123"
        assert payment.status == "created"
    finally:
        session.close()


def test_admin_payment_manual_approval_requires_confirmation_and_reason(monkeypatch):
    Session = _session_factory()
    app = _app(Session)
    monkeypatch.setattr(admin_payments, "_admin_guard", lambda request: None)

    response = TestClient(app).post(
        "/admin/api/payments/123/approve",
        json={},
        headers={"X-Admin-API": "1"},
    )

    assert response.status_code == 422
    assert "confirmation" in response.json()["error"].lower()
    app.state.container.payment_service.activate_payment.assert_not_called()


def test_admin_payment_manual_approval_records_reason_without_affecting_razorpay(monkeypatch):
    Session = _session_factory()
    app = _app(Session)
    monkeypatch.setattr(admin_payments, "_admin_guard", lambda request: None)
    app.state.container.payment_service.activate_payment.return_value = {"payment": {"id": 123, "status": "approved"}}
    app.state.container.payment_service.append_payment_note = MagicMock(return_value=None)

    response = TestClient(app).post(
        "/admin/api/payments/123/approve",
        json={
            "confirm_manual_override": True,
            "manual_override_reason": "Verified bank transfer reference manually",
        },
        headers={"X-Admin-API": "1"},
    )

    assert response.status_code == 200
    assert response.json()["payment_note"].startswith("Manual admin approval override")
    app.state.container.payment_service.activate_payment.assert_called_once_with(123, triggered_by="admin")
    app.state.container.payment_service.append_payment_note.assert_called_once()
    app.state.container.audit_service.log.assert_called()
    audit_kwargs = app.state.container.audit_service.log.call_args.kwargs
    assert audit_kwargs["action"] == "payment_approved"
    assert "Verified bank transfer" in audit_kwargs["after_json"]


def test_razorpay_webhook_uses_header_event_id_and_deduplicates(monkeypatch):
    Session = _session_factory()
    user_id, plan_id = _seed_user_plan(Session)
    session = Session()
    try:
        payment = PaymentRecord(
            user_id=user_id,
            plan_id=plan_id,
            payment_method="razorpay",
            payment_provider="razorpay",
            provider_order_id="order_test_123",
            amount=50000,
            currency="INR",
            status="created",
        )
        session.add(payment)
        session.commit()
        payment_id = int(payment.id)
    finally:
        session.close()

    app = _app(Session)
    app.state.container.payment_service.activate_payment.return_value = {"payment": {"id": payment_id}}
    monkeypatch.setattr(webhooks, "get_session", Session)

    payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_test_123",
                    "order_id": "order_test_123",
                    "amount": 50000,
                    "currency": "INR",
                    "status": "captured",
                }
            }
        },
    }
    raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(b"whsec_test", raw_body, hashlib.sha256).hexdigest()
    headers = {
        "X-Razorpay-Signature": signature,
        "X-Razorpay-Event-Id": "evt_test_123",
        "Content-Type": "application/json",
    }
    client = TestClient(app)

    response = client.post("/api/webhooks/razorpay", content=raw_body, headers=headers)
    duplicate = client.post("/api/webhooks/razorpay", content=raw_body, headers=headers)

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert duplicate.status_code == 200
    assert duplicate.json() == {"ok": True, "duplicate": True, "scope": "database"}
    app.state.container.payment_service.activate_payment.assert_called_once_with(
        payment_id,
        triggered_by="razorpay",
    )
    session = Session()
    try:
        event = session.query(PaymentWebhookEvent).one()
        assert event.event_id == "evt_test_123"
        assert event.status == "processed"
    finally:
        session.close()
