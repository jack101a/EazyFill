from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import webhooks
from app.core.db import Base
from app.core.models import PaymentRecord, SubscriptionPlan, User, UserSubscription
from app.services.payment_service import PaymentService
from app.services.promo_plan_policy import check_promo_plan_eligibility


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


def test_promo_plan_allows_first_use_and_blocks_second_use():
    Session = _session_factory()
    session = Session()
    try:
        user = User(full_name="Promo User", status="pending_payment")
        plan = SubscriptionPlan(
            code="new_demo1",
            name="New Demo1",
            price_amount=1000,
            is_promo=True,
            promo_audience="both",
        )
        session.add_all([user, plan])
        session.commit()

        assert check_promo_plan_eligibility(session, user, plan).eligible is True

        session.add(UserSubscription(user_id=user.id, plan_id=plan.id, status="active"))
        session.commit()

        result = check_promo_plan_eligibility(session, user, plan)
        assert result.eligible is False
        assert "only once" in result.reason
    finally:
        session.close()


def test_promo_plan_audience_targets_new_or_registered_users():
    Session = _session_factory()
    session = Session()
    try:
        new_user = User(full_name="New User", status="pending_payment")
        registered_user = User(full_name="Registered User", status="active")
        old_plan = SubscriptionPlan(code="old", name="Old Plan", price_amount=1000)
        new_only = SubscriptionPlan(
            code="promo_new",
            name="Promo New",
            price_amount=500,
            is_promo=True,
            promo_audience="new",
        )
        registered_only = SubscriptionPlan(
            code="promo_registered",
            name="Promo Registered",
            price_amount=500,
            is_promo=True,
            promo_audience="registered",
        )
        session.add_all([new_user, registered_user, old_plan, new_only, registered_only])
        session.flush()
        session.add(UserSubscription(user_id=registered_user.id, plan_id=old_plan.id, status="expired"))
        session.commit()

        assert check_promo_plan_eligibility(session, new_user, new_only).eligible is True
        assert check_promo_plan_eligibility(session, registered_user, new_only).eligible is False
        assert check_promo_plan_eligibility(session, registered_user, registered_only).eligible is True
        assert check_promo_plan_eligibility(session, new_user, registered_only).eligible is False
    finally:
        session.close()


def test_payment_activation_blocks_second_promo_use():
    Session = _session_factory()
    session = Session()
    try:
        user = User(full_name="Promo User", status="active")
        plan = SubscriptionPlan(
            code="new_demo1",
            name="New Demo1",
            price_amount=1000,
            is_promo=True,
            promo_audience="both",
        )
        session.add_all([user, plan])
        session.flush()
        session.add(UserSubscription(user_id=user.id, plan_id=plan.id, status="expired"))
        payment = PaymentRecord(
            user_id=user.id,
            plan_id=plan.id,
            amount=1000,
            currency="INR",
            status="created",
            payment_method="razorpay",
            payment_provider="razorpay",
        )
        session.add(payment)
        session.commit()
        payment_id = int(payment.id)
    finally:
        session.close()

    service = PaymentService(Session, _settings())
    try:
        service.activate_payment(payment_id, triggered_by="test")
    except ValueError as exc:
        assert "only once" in str(exc)
    else:
        raise AssertionError("Expected promo activation to be blocked")


def test_razorpay_order_creation_rejects_ineligible_promo(monkeypatch):
    Session = _session_factory()
    session = Session()
    try:
        user = User(full_name="Promo User", status="active")
        plan = SubscriptionPlan(
            code="new_demo1",
            name="New Demo1",
            price_amount=1000,
            is_active=True,
            is_promo=True,
            promo_audience="both",
        )
        session.add_all([user, plan])
        session.flush()
        session.add(UserSubscription(user_id=user.id, plan_id=plan.id, status="expired"))
        session.commit()
        user_id = int(user.id)
        plan_id = int(plan.id)
    finally:
        session.close()

    app = FastAPI()
    app.state.container = SimpleNamespace(settings=_settings())
    app.include_router(webhooks.router)
    monkeypatch.setattr(webhooks, "get_session", Session)

    response = TestClient(app).post(
        "/api/payments/razorpay/order",
        json={"user_id": user_id, "plan_id": plan_id},
        headers={"x-payment-init-token": "order-token"},
    )

    assert response.status_code == 400
    assert "only once" in response.json()["error"]
