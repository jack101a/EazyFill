from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.core.models import SubscriptionPlan
from app.services.subscription_service import SubscriptionService


def _service():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return SubscriptionService(Session), Session


def test_default_checkout_plans_seed_when_checkout_catalog_is_empty():
    service, Session = _service()

    service.ensure_default_checkout_plans(only_when_empty=True)

    session = Session()
    try:
        visible = (
            session.query(SubscriptionPlan)
            .filter(SubscriptionPlan.is_active == True, SubscriptionPlan.show_in_checkout == True)  # noqa: E712
            .order_by(SubscriptionPlan.price_amount)
            .all()
        )
        assert [plan.code for plan in visible] == ["basic", "pro"]
        assert visible[0].price_amount == 14900
        assert visible[0].allowed_services["sync"] is True
        assert visible[0].allowed_services["portable_pack"] is True
        free = session.query(SubscriptionPlan).filter(SubscriptionPlan.code == "free").one()
        assert free.is_active is True
        assert free.show_in_checkout is False
    finally:
        session.close()


def test_default_checkout_plan_repair_is_skipped_when_custom_checkout_exists():
    service, Session = _service()
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


def test_default_checkout_plan_can_repair_requested_missing_code():
    service, Session = _service()

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
