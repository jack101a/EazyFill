from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.core.models import SubscriptionPlan, User, UserSubscription
from app.services.subscription_service import SubscriptionService


BOOTSTRAP_PLANS = [
    {
        "code": "free",
        "name": "Free",
        "monthly_limit": 25,
        "duration_days": 30,
        "price_amount": 0,
        "show_in_checkout": False,
        "allowed_services": {"captcha": True, "autofill": True, "userscripts": True, "rules_limit": 3, "scripts_limit": 1},
    },
    {
        "code": "basic",
        "name": "Basic",
        "monthly_limit": 500,
        "duration_days": 30,
        "price_amount": 14900,
        "show_in_checkout": True,
        "allowed_services": {"captcha": True, "sync": True, "portable_pack": True, "rules_limit": 50, "scripts_limit": 10},
    },
]


def _settings(*, auto_seed_on_empty=True, plans=None):
    return SimpleNamespace(
        plans=SimpleNamespace(
            auto_seed_on_empty=auto_seed_on_empty,
            bootstrap_plans=plans if plans is not None else BOOTSTRAP_PLANS,
        )
    )


def _service(settings=None):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return SubscriptionService(Session, settings=settings), Session


def test_configured_checkout_plans_seed_when_checkout_catalog_is_empty():
    service, Session = _service(_settings())

    service.ensure_default_checkout_plans(only_when_empty=True)

    session = Session()
    try:
        visible = (
            session.query(SubscriptionPlan)
            .filter(SubscriptionPlan.is_active == True, SubscriptionPlan.show_in_checkout == True)  # noqa: E712
            .order_by(SubscriptionPlan.price_amount)
            .all()
        )
        assert [plan.code for plan in visible] == ["basic"]
        assert visible[0].price_amount == 14900
        assert visible[0].allowed_services["sync"] is True
        assert visible[0].allowed_services["portable_pack"] is True
        free = session.query(SubscriptionPlan).filter(SubscriptionPlan.code == "free").one()
        assert free.is_active is True
        assert free.show_in_checkout is False
    finally:
        session.close()


def test_configured_checkout_plan_repair_is_skipped_when_custom_checkout_exists():
    service, Session = _service(_settings())
    session = Session()
    try:
        session.add(
            SubscriptionPlan(
                code="custom",
                name="Custom",
                monthly_limit=25,
                price_amount=2500,
                is_active=True,
                show_in_checkout=True,
                allowed_services={"captcha": True},
            )
        )
        session.commit()
    finally:
        session.close()

    service.ensure_default_checkout_plans(only_when_empty=True)

    session = Session()
    try:
        assert session.query(SubscriptionPlan).count() == 1
        assert session.query(SubscriptionPlan).one().code == "custom"
    finally:
        session.close()


def test_no_bootstrap_plans_means_no_hardcoded_catalog():
    service, Session = _service(_settings(plans=[]))

    service.ensure_default_checkout_plans(codes={"basic"})

    session = Session()
    try:
        assert session.query(SubscriptionPlan).count() == 0
    finally:
        session.close()


def test_configured_checkout_plan_can_repair_requested_missing_code():
    service, Session = _service(_settings())

    service.ensure_default_checkout_plans(codes={"basic"})

    session = Session()
    try:
        plans = session.query(SubscriptionPlan).all()
        assert [plan.code for plan in plans] == ["basic"]
        assert plans[0].is_active is True
        assert plans[0].show_in_checkout is True
        assert plans[0].price_amount == 14900
    finally:
        session.close()


def test_expired_paid_subscription_downgrades_to_configured_free_plan():
    service, Session = _service(_settings())
    service.ensure_default_checkout_plans(codes={"free", "basic"})
    session = Session()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        user = User(full_name="Plan User", email="plan@example.test", status="active")
        session.add(user)
        session.flush()
        basic = session.query(SubscriptionPlan).filter(SubscriptionPlan.code == "basic").one()
        session.add(UserSubscription(
            user_id=user.id,
            plan_id=basic.id,
            status="active",
            monthly_limit_snapshot=basic.monthly_limit,
            start_at=now - timedelta(days=40),
            end_at=now - timedelta(days=1),
            current_cycle_start_at=now - timedelta(days=40),
            current_cycle_end_at=now - timedelta(days=10),
        ))
        session.commit()
        user_id = int(user.id)
    finally:
        session.close()

    sub, plan = service.ensure_current_or_free_subscription(user_id)

    session = Session()
    try:
        assert plan.code == "free"
        assert sub.status == "active"
        assert session.query(UserSubscription).filter(UserSubscription.status == "expired").count() == 1
        assert session.query(UserSubscription).filter(UserSubscription.status == "active").count() == 1
    finally:
        session.close()
