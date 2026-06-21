from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v2_routes.auth import _ensure_subscription
from app.core.db import Base
from app.core.models import SubscriptionPlan, User, UserSubscription


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _seed_user_and_plans(session):
    user = User(full_name="Login User", email="login@example.test", status="active")
    free = SubscriptionPlan(
        code="free",
        name="Free",
        monthly_limit=100,
        duration_days=30,
        price_amount=0,
        allowed_services={"captcha": True, "autofill": True, "userscripts": True},
    )
    pro = SubscriptionPlan(
        code="pro",
        name="Pro",
        monthly_limit=1000,
        duration_days=30,
        price_amount=99900,
        allowed_services={"captcha": True, "autofill": True, "userscripts": True, "sync": True},
    )
    session.add_all([user, free, pro])
    session.flush()
    return user, free, pro


def test_otp_login_replaces_expired_active_subscription_with_fresh_free_plan():
    Session = _session_factory()
    session = Session()
    now = datetime.now(timezone.utc)
    try:
        user, free, _pro = _seed_user_and_plans(session)
        expired = UserSubscription(
            user_id=user.id,
            plan_id=free.id,
            status="active",
            monthly_limit_snapshot=free.monthly_limit,
            start_at=now - timedelta(days=60),
            end_at=now - timedelta(days=1),
            current_cycle_start_at=now - timedelta(days=60),
            current_cycle_end_at=now - timedelta(days=30),
        )
        session.add(expired)
        session.flush()

        created = _ensure_subscription(session, user, "free")
        session.commit()

        assert created is not None
        assert created.id != expired.id
        assert created.status == "active"
        assert created.plan_id == free.id
        assert created.end_at > now.replace(tzinfo=None)
        assert session.get(UserSubscription, expired.id).status == "expired"
    finally:
        session.close()


def test_otp_login_does_not_activate_paid_plan_from_plan_code():
    Session = _session_factory()
    session = Session()
    try:
        user, free, _pro = _seed_user_and_plans(session)

        created = _ensure_subscription(session, user, "pro")
        session.commit()

        assert created is not None
        assert created.status == "active"
        assert created.plan_id == free.id
    finally:
        session.close()


def test_otp_login_keeps_unexpired_paid_subscription():
    Session = _session_factory()
    session = Session()
    now = datetime.now(timezone.utc)
    try:
        user, _free, pro = _seed_user_and_plans(session)
        existing = UserSubscription(
            user_id=user.id,
            plan_id=pro.id,
            status="active",
            monthly_limit_snapshot=pro.monthly_limit,
            start_at=now - timedelta(days=1),
            end_at=now + timedelta(days=20),
            current_cycle_start_at=now - timedelta(days=1),
            current_cycle_end_at=now + timedelta(days=20),
        )
        session.add(existing)
        session.flush()

        result = _ensure_subscription(session, user, "free")
        session.commit()

        assert result.id == existing.id
        assert result.plan_id == pro.id
        assert result.status == "active"
    finally:
        session.close()
