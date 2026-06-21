from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.core.models import SubscriptionPlan, User, UserApiKey, UserSubscription
from app.core.security import hash_api_key
from app.services.usage_cycle_service import UsageCycleService
from app.services.user_key_service import UserKeyService


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _settings():
    settings = MagicMock()
    settings.auth.hash_salt = "test-salt"
    settings.auth.key_prefix = "SK-"
    settings.auth.key_length = 16
    settings.auth.default_expiry_days = 30
    return settings


def _seed_user_with_plan(Session, *, user_status="active", subscription_status="active", end_delta_days=10, mobile=None, services=None):
    session = Session()
    now = datetime.now(timezone.utc)
    try:
        user = User(full_name="Test User", status=user_status, mobile_number=mobile)
        plan = SubscriptionPlan(
            code="standard",
            name="Standard",
            monthly_limit=100,
            duration_days=30,
            price_amount=1000,
            allowed_services=services or {"captcha": True, "autofill": True},
        )
        session.add_all([user, plan])
        session.flush()
        sub = UserSubscription(
            user_id=user.id,
            plan_id=plan.id,
            status=subscription_status,
            monthly_limit_snapshot=plan.monthly_limit,
            start_at=now - timedelta(days=1),
            end_at=now + timedelta(days=end_delta_days),
            current_cycle_start_at=now - timedelta(days=1),
            current_cycle_end_at=now + timedelta(days=29),
        )
        session.add(sub)
        session.commit()
        return user.id
    finally:
        session.close()


def test_create_user_key_has_no_independent_expiry():
    Session = _session_factory()
    user_id = _seed_user_with_plan(Session)
    svc = UserKeyService(Session, _settings())

    key, plain = svc.create_key(user_id)

    assert plain.startswith("SK-")
    assert key.status == "active"
    assert key.expires_at is None


def test_create_user_key_keeps_existing_device_keys_active():
    Session = _session_factory()
    user_id = _seed_user_with_plan(Session)
    svc = UserKeyService(Session, _settings())

    first_key, first_plain = svc.create_key(user_id)
    second_key, second_plain = svc.create_key(user_id)

    assert first_plain != second_plain
    session = Session()
    try:
        statuses = {
            key.id: key.status
            for key in session.query(UserApiKey).filter(UserApiKey.user_id == user_id).all()
        }
    finally:
        session.close()
    assert statuses[int(first_key.id)] == "active"
    assert statuses[int(second_key.id)] == "active"


def test_rotate_user_key_revokes_existing_device_keys():
    Session = _session_factory()
    user_id = _seed_user_with_plan(Session)
    svc = UserKeyService(Session, _settings())

    first_key, _first_plain = svc.create_key(user_id)
    second_key, _second_plain = svc.create_key(user_id)
    rotated_key, _rotated_plain = svc.rotate_key(user_id)

    session = Session()
    try:
        statuses = {
            key.id: key.status
            for key in session.query(UserApiKey).filter(UserApiKey.user_id == user_id).all()
        }
    finally:
        session.close()
    assert statuses[int(first_key.id)] == "rotated"
    assert statuses[int(second_key.id)] == "rotated"
    assert statuses[int(rotated_key.id)] == "active"


def test_validate_user_key_requires_active_subscription():
    Session = _session_factory()
    user_id = _seed_user_with_plan(Session, end_delta_days=-1)
    settings = _settings()
    plain = "SK-expired-subscription"
    session = Session()
    try:
        session.add(UserApiKey(
            user_id=user_id,
            key_hash=hash_api_key(plain, settings.auth.hash_salt),
            key_prefix_display=plain[:10] + "...",
            status="active",
        ))
        session.commit()
    finally:
        session.close()

    result = UserKeyService(Session, settings).validate_key(plain)

    assert result["auth_error"] == "expired_subscription"


def test_legacy_user_access_blocks_expired_linked_user():
    Session = _session_factory()
    _seed_user_with_plan(Session, mobile="+919999999999", end_delta_days=-1)

    result = UserKeyService(Session, _settings()).legacy_user_access({
        "mobile": "9999999999",
        "services": {"captcha": True},
    })

    assert result["auth_error"] == "expired_subscription"


def test_legacy_user_access_returns_active_plan_entitlements():
    Session = _session_factory()
    _seed_user_with_plan(
        Session,
        mobile="+917777777777",
        services={"captcha": True, "autofill": False, "custom": False},
    )

    result = UserKeyService(Session, _settings()).legacy_user_access({
        "mobile": "7777777777",
        "services": {"captcha": False, "autofill": True, "custom": True},
    })

    assert "auth_error" not in result
    assert result["entitlements"]["services"] == {"captcha": True, "autofill": False, "custom": False}


def test_validate_user_key_distinguishes_revoked_key():
    Session = _session_factory()
    user_id = _seed_user_with_plan(Session)
    settings = _settings()
    plain = "SK-revoked"
    session = Session()
    try:
        session.add(UserApiKey(
            user_id=user_id,
            key_hash=hash_api_key(plain, settings.auth.hash_salt),
            key_prefix_display=plain[:10] + "...",
            status="revoked",
            revoked_at=datetime.now(timezone.utc),
            revoked_reason="admin_revoked",
        ))
        session.commit()
    finally:
        session.close()

    result = UserKeyService(Session, settings).validate_key(plain)

    assert result["auth_error"] == "revoked_key"


def test_increment_usage_atomic_works_with_sqlalchemy_two():
    Session = _session_factory()
    user_id = _seed_user_with_plan(Session)
    svc = UsageCycleService(Session)

    result = svc.increment_usage_atomic(user_id, amount=1)

    assert result["allowed"] is True
    assert result["used"] == 1
    assert result["limit"] == 100


def test_increment_usage_atomic_blocks_without_incrementing_over_limit():
    Session = _session_factory()
    user_id = _seed_user_with_plan(Session)
    svc = UsageCycleService(Session)

    result = svc.increment_usage_atomic(user_id, amount=101)

    assert result["allowed"] is False
    assert result["reason"] == "quota_exceeded"
    assert result["used"] == 0
    assert result["limit"] == 100


def test_refund_usage_atomic_decrements_reserved_usage():
    Session = _session_factory()
    user_id = _seed_user_with_plan(Session)
    svc = UsageCycleService(Session)

    reserved = svc.increment_usage_atomic(user_id, amount=1)
    refunded = svc.refund_usage_atomic(user_id, amount=1, cycle_id=reserved["cycle_id"])

    assert reserved["allowed"] is True
    assert refunded["refunded"] is True
    assert refunded["used"] == 0
    assert refunded["limit"] == 100


def test_refund_usage_atomic_never_goes_below_zero():
    Session = _session_factory()
    user_id = _seed_user_with_plan(Session)
    svc = UsageCycleService(Session)
    cycle = svc.get_or_create_cycle(user_id)

    refunded = svc.refund_usage_atomic(user_id, amount=1, cycle_id=cycle.id)

    assert refunded["refunded"] is True
    assert refunded["used"] == 0
    assert refunded["limit"] == 100
