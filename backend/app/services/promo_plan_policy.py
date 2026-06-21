"""Promo plan eligibility policy."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.models import PaymentRecord, SubscriptionPlan, User, UserSubscription


PROMO_AUDIENCE_NEW = "new"
PROMO_AUDIENCE_REGISTERED = "registered"
PROMO_AUDIENCE_BOTH = "both"
PROMO_AUDIENCES = {
    PROMO_AUDIENCE_NEW,
    PROMO_AUDIENCE_REGISTERED,
    PROMO_AUDIENCE_BOTH,
}

SUCCESSFUL_SUBSCRIPTION_STATUSES = {"active", "expired", "cancelled"}
OPEN_PAYMENT_STATUSES = {
    "created",
    "pending_payment",
}


@dataclass(frozen=True)
class PromoEligibility:
    eligible: bool
    reason: str = ""


def normalize_promo_audience(value: object) -> str:
    audience = str(value or PROMO_AUDIENCE_BOTH).strip().lower()
    return audience if audience in PROMO_AUDIENCES else PROMO_AUDIENCE_BOTH


def validate_promo_audience(value: object) -> str:
    audience = str(value or PROMO_AUDIENCE_BOTH).strip().lower()
    if audience not in PROMO_AUDIENCES:
        raise ValueError("promo_audience must be one of: new, registered, both")
    return audience


def user_has_subscription_history(session: Session, user_id: int) -> bool:
    return (
        session.query(UserSubscription.id)
        .filter(
            UserSubscription.user_id == int(user_id),
            UserSubscription.status.in_(SUCCESSFUL_SUBSCRIPTION_STATUSES),
        )
        .first()
        is not None
    )


def user_has_used_plan(session: Session, user_id: int, plan_id: int) -> bool:
    return (
        session.query(UserSubscription.id)
        .filter(
            UserSubscription.user_id == int(user_id),
            UserSubscription.plan_id == int(plan_id),
            UserSubscription.status.in_(SUCCESSFUL_SUBSCRIPTION_STATUSES),
        )
        .first()
        is not None
    )


def user_has_open_payment_for_plan(session: Session, user_id: int, plan_id: int) -> bool:
    return (
        session.query(PaymentRecord.id)
        .filter(
            PaymentRecord.user_id == int(user_id),
            PaymentRecord.plan_id == int(plan_id),
            PaymentRecord.status.in_(OPEN_PAYMENT_STATUSES),
        )
        .first()
        is not None
    )


def check_promo_plan_eligibility(
    session: Session,
    user: User,
    plan: SubscriptionPlan,
    *,
    include_open_payment: bool = True,
    current_payment_id: int | None = None,
) -> PromoEligibility:
    if not bool(getattr(plan, "is_promo", False)):
        return PromoEligibility(True)

    user_id = int(user.id)
    plan_id = int(plan.id)
    if user_has_used_plan(session, user_id, plan_id):
        return PromoEligibility(False, "This promo plan can be availed only once per user.")

    if include_open_payment:
        q = session.query(PaymentRecord.id).filter(
            PaymentRecord.user_id == user_id,
            PaymentRecord.plan_id == plan_id,
            PaymentRecord.status.in_(OPEN_PAYMENT_STATUSES),
        )
        if current_payment_id is not None:
            q = q.filter(PaymentRecord.id != int(current_payment_id))
        if q.first() is not None:
            return PromoEligibility(False, "This user already has an open payment for this promo plan.")

    has_history = user_has_subscription_history(session, user_id)
    audience = normalize_promo_audience(getattr(plan, "promo_audience", None))
    if audience == PROMO_AUDIENCE_NEW and has_history:
        return PromoEligibility(False, "This promo plan is available only for new users.")
    if audience == PROMO_AUDIENCE_REGISTERED and not has_history:
        return PromoEligibility(False, "This promo plan is available only for registered users.")

    return PromoEligibility(True)
