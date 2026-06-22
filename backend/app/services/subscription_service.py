"""Subscription management service — plans, user subscriptions, lifecycle."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.core.models import PaymentRecord, SubscriptionPlan, UsageCycle, UserSubscription, User
from app.services.promo_plan_policy import (
    check_promo_plan_eligibility,
    validate_promo_audience,
)


class SubscriptionService:
    """Manages subscription plans and user subscription lifecycle."""

    def __init__(self, session_factory, settings=None):
        self._session_factory = session_factory
        self._settings = settings

    def _session(self) -> Session:
        return self._session_factory()

    def _bootstrap_plan_specs(self) -> list[dict]:
        plans_config = getattr(self._settings, "plans", None)
        raw = getattr(plans_config, "bootstrap_plans", None) if plans_config else None
        return [dict(item) for item in (raw or []) if isinstance(item, dict)]

    def _auto_seed_on_empty(self) -> bool:
        plans_config = getattr(self._settings, "plans", None)
        return bool(getattr(plans_config, "auto_seed_on_empty", False))

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None)

    @staticmethod
    def _as_naive_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    @classmethod
    def _subscription_is_current(cls, sub: UserSubscription | None, now: datetime | None = None) -> bool:
        if not sub or sub.status != "active":
            return False
        end_at = cls._as_naive_utc(sub.end_at)
        return end_at is None or end_at >= (now or cls._now())

    # ── Plans ──────────────────────────────────────────────────────────────

    def ensure_default_checkout_plans(
        self,
        codes: set[str] | None = None,
        *,
        only_when_empty: bool = False,
    ) -> list[SubscriptionPlan]:
        """Create or repair configured bootstrap plans when deployment data is empty."""
        if only_when_empty and not self._auto_seed_on_empty():
            return []

        wanted_codes = {str(code or "").strip().lower() for code in (codes or set()) if str(code or "").strip()}
        specs = [
            spec for spec in self._bootstrap_plan_specs()
            if str(spec.get("code") or "").strip() and (not wanted_codes or str(spec.get("code")).lower() in wanted_codes)
        ]
        if not specs:
            return []

        session = self._session()
        try:
            if only_when_empty:
                visible_plan = (
                    session.query(SubscriptionPlan.id)
                    .filter(
                        SubscriptionPlan.is_active == True,  # noqa: E712
                        SubscriptionPlan.show_in_checkout == True,  # noqa: E712
                    )
                    .first()
                )
                if visible_plan:
                    return []

            touched: list[SubscriptionPlan] = []
            for spec in specs:
                code = str(spec.get("code") or "").strip().lower()
                plan = session.query(SubscriptionPlan).filter(SubscriptionPlan.code == code).first()
                values = {
                    "code": code,
                    "name": str(spec.get("name") or code.title()),
                    "description": str(spec.get("description") or ""),
                    "monthly_limit": int(spec.get("monthly_limit") or 0),
                    "duration_days": int(spec.get("duration_days") or 30),
                    "price_amount": int(spec.get("price_amount") or 0),
                    "currency": str(spec.get("currency") or "INR").upper()[:3],
                    "max_devices": int(spec.get("max_devices") or 1),
                    "allowed_services": dict(spec.get("allowed_services") or {}),
                    "rate_limit_rpm": int(spec.get("rate_limit_rpm") or 60),
                    "rate_limit_burst": int(spec.get("rate_limit_burst") or 10),
                    "show_in_checkout": bool(spec.get("show_in_checkout", True)),
                    "is_promo": bool(spec.get("is_promo", False)),
                    "promo_audience": validate_promo_audience(spec.get("promo_audience", "both")),
                }
                if plan:
                    if only_when_empty or wanted_codes:
                        for key, value in values.items():
                            if hasattr(plan, key):
                                setattr(plan, key, value)
                        plan.is_active = True
                        plan.updated_at = datetime.now(timezone.utc)
                        touched.append(plan)
                    continue
                plan = SubscriptionPlan(**values)
                session.add(plan)
                touched.append(plan)

            session.commit()
            for plan in touched:
                session.refresh(plan)
            return touched
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def create_plan(
        self,
        code: str,
        name: str,
        monthly_limit: int = 3000,
        duration_days: int = 30,
        price_amount: int = 0,
        currency: str = "INR",
        description: str = "",
        max_devices: int = 1,
        allowed_services: dict | None = None,
        rate_limit_rpm: int = 60,
        rate_limit_burst: int = 10,
        show_in_checkout: bool = True,
        is_promo: bool = False,
        promo_audience: str = "both",
    ) -> SubscriptionPlan:
        session = self._session()
        try:
            promo_audience = validate_promo_audience(promo_audience)
            plan = SubscriptionPlan(
                code=code,
                name=name,
                description=description,
                monthly_limit=monthly_limit,
                duration_days=duration_days,
                price_amount=price_amount,
                currency=currency,
                max_devices=max_devices,
                allowed_services=allowed_services or {},
                rate_limit_rpm=rate_limit_rpm,
                rate_limit_burst=rate_limit_burst,
                show_in_checkout=bool(show_in_checkout),
                is_promo=bool(is_promo),
                promo_audience=promo_audience,
            )
            session.add(plan)
            session.commit()
            session.refresh(plan)
            return plan
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_plan(self, plan_id: int) -> SubscriptionPlan | None:
        session = self._session()
        try:
            return session.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
        finally:
            session.close()

    def get_plan_by_code(self, code: str) -> SubscriptionPlan | None:
        session = self._session()
        try:
            return session.query(SubscriptionPlan).filter(SubscriptionPlan.code == code).first()
        finally:
            session.close()

    def list_plans(self, active_only: bool = True) -> list[SubscriptionPlan]:
        session = self._session()
        try:
            q = session.query(SubscriptionPlan)
            if active_only:
                q = q.filter(SubscriptionPlan.is_active == True)
            return q.order_by(SubscriptionPlan.price_amount).all()
        finally:
            session.close()

    def update_plan(self, plan_id: int, **kwargs) -> SubscriptionPlan | None:
        session = self._session()
        try:
            plan = session.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
            if not plan:
                return None
            if kwargs.get("is_active") is False:
                kwargs["show_in_checkout"] = False
            if kwargs.get("show_in_checkout") is True and not kwargs.get("is_active", plan.is_active):
                kwargs["show_in_checkout"] = False
            if "promo_audience" in kwargs:
                kwargs["promo_audience"] = validate_promo_audience(kwargs.get("promo_audience"))
            for key, value in kwargs.items():
                if hasattr(plan, key):
                    setattr(plan, key, value)
            plan.updated_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(plan)
            return plan
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def delete_plan(self, plan_id: int, target_plan_id: int | None = None) -> dict | None:
        """Delete a plan, migrating required subscription references first."""
        session = self._session()
        try:
            plan = session.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
            if not plan:
                return None
            target_plan = None
            if target_plan_id is not None:
                if int(target_plan_id) == int(plan_id):
                    raise ValueError("target_plan_id must be different from plan_id")
                target_plan = (
                    session.query(SubscriptionPlan)
                    .filter(SubscriptionPlan.id == int(target_plan_id))
                    .first()
                )
                if not target_plan:
                    raise ValueError(f"Target plan {target_plan_id} not found")
                if not target_plan.is_active:
                    raise ValueError("Target plan must be active")

            subs = session.query(UserSubscription).filter(UserSubscription.plan_id == plan_id).all()
            live_subs = [sub for sub in subs if sub.status in {"active", "pending"}]
            historical_subs = [sub for sub in subs if sub.status not in {"active", "pending"}]
            if live_subs and target_plan is None:
                raise ValueError("Select a target plan before deleting a plan linked to subscriptions")

            now = datetime.now(timezone.utc)
            migrated_count = 0
            deleted_subscription_count = 0
            if target_plan is not None:
                for sub in subs:
                    sub.plan_id = int(target_plan.id)
                    sub.monthly_limit_snapshot = int(target_plan.monthly_limit)
                    sub.updated_at = now
                migrated_count = len(subs)
            else:
                historical_subscription_ids = [int(sub.id) for sub in historical_subs]
                if historical_subscription_ids:
                    (
                        session.query(UsageCycle)
                        .filter(UsageCycle.subscription_id.in_(historical_subscription_ids))
                        .delete(synchronize_session=False)
                    )
                    (
                        session.query(PaymentRecord)
                        .filter(PaymentRecord.subscription_id.in_(historical_subscription_ids))
                        .update(
                            {
                                PaymentRecord.subscription_id: None,
                                PaymentRecord.plan_id: None,
                                PaymentRecord.updated_at: now,
                            },
                            synchronize_session=False,
                        )
                    )
                for sub in historical_subs:
                    session.delete(sub)
                deleted_subscription_count = len(historical_subs)

            payments = session.query(PaymentRecord).filter(PaymentRecord.plan_id == plan_id).all()
            for payment in payments:
                payment.plan_id = int(target_plan.id) if target_plan is not None else None
                payment.updated_at = now

            session.delete(plan)
            session.commit()
            return {
                "plan_id": int(plan_id),
                "migrated_count": migrated_count,
                "target_plan_id": int(target_plan.id) if target_plan is not None else None,
                "payment_refs_updated": len(payments),
                "deleted_subscription_count": deleted_subscription_count,
            }
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ── User Subscriptions ─────────────────────────────────────────────────

    def create_subscription(
        self,
        user_id: int,
        plan_id: int,
        approved_by_admin_id: int | None = None,
    ) -> UserSubscription:
        session = self._session()
        try:
            plan = session.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
            if not plan:
                raise ValueError(f"Plan {plan_id} not found")
            user = session.query(User).filter(User.id == user_id).first()
            if not user:
                raise ValueError(f"User {user_id} not found")
            eligibility = check_promo_plan_eligibility(session, user, plan)
            if not eligibility.eligible:
                raise ValueError(eligibility.reason)

            now = datetime.now(timezone.utc)
            sub = UserSubscription(
                user_id=user_id,
                plan_id=plan_id,
                status="active",
                monthly_limit_snapshot=plan.monthly_limit,
                start_at=now,
                end_at=now + timedelta(days=plan.duration_days),
                billing_anchor_day=now.day,
                current_cycle_start_at=now,
                current_cycle_end_at=now + timedelta(days=30),
                approved_by_admin_id=approved_by_admin_id,
                approved_at=now,
            )
            session.add(sub)

            # Activate the user (unless blocked)
            if user:
                if user.status != "blocked":
                    user.status = "active"
                user.updated_at = now

            session.commit()
            session.refresh(sub)
            return sub
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_active_subscription(self, user_id: int) -> UserSubscription | None:
        session = self._session()
        try:
            now = self._now()
            (
                session.query(UserSubscription)
                .filter(
                    UserSubscription.user_id == user_id,
                    UserSubscription.status == "active",
                    UserSubscription.end_at.isnot(None),
                    UserSubscription.end_at < now,
                )
                .update({"status": "expired", "updated_at": now}, synchronize_session=False)
            )
            session.commit()
            return (
                session.query(UserSubscription)
                .filter(
                    UserSubscription.user_id == user_id,
                    UserSubscription.status == "active",
                    or_(UserSubscription.end_at.is_(None), UserSubscription.end_at >= now),
                )
                .order_by(UserSubscription.created_at.desc())
                .first()
            )
        finally:
            session.close()

    def get_free_plan(self, session: Session) -> SubscriptionPlan | None:
        plan = (
            session.query(SubscriptionPlan)
            .filter(
                SubscriptionPlan.code == "free",
                SubscriptionPlan.is_active == True,  # noqa: E712
            )
            .first()
        )
        if plan:
            return plan
        return (
            session.query(SubscriptionPlan)
            .filter(
                SubscriptionPlan.is_active == True,  # noqa: E712
                SubscriptionPlan.price_amount <= 0,
            )
            .order_by(SubscriptionPlan.monthly_limit.asc(), SubscriptionPlan.id.asc())
            .first()
        )

    def ensure_current_or_free_subscription(self, user_id: int) -> tuple[UserSubscription | None, SubscriptionPlan | None]:
        """Return a current subscription, downgrading expired paid access to the free plan if available."""
        session = self._session()
        try:
            now = self._now()
            active_subs = (
                session.query(UserSubscription)
                .filter(UserSubscription.user_id == int(user_id), UserSubscription.status == "active")
                .order_by(UserSubscription.created_at.desc())
                .all()
            )
            current = None
            for sub in active_subs:
                if self._subscription_is_current(sub, now):
                    if current is None:
                        current = sub
                    continue
                sub.status = "expired"
                sub.updated_at = now

            if current is None:
                free_plan = self.get_free_plan(session)
                if free_plan:
                    current = UserSubscription(
                        user_id=int(user_id),
                        plan_id=int(free_plan.id),
                        status="active",
                        monthly_limit_snapshot=int(free_plan.monthly_limit or 0),
                        start_at=now,
                        end_at=now + timedelta(days=int(free_plan.duration_days or 30)),
                        billing_anchor_day=now.day,
                        current_cycle_start_at=now,
                        current_cycle_end_at=now + timedelta(days=int(free_plan.duration_days or 30)),
                        approved_at=now,
                    )
                    session.add(current)
                    session.flush()

            plan = (
                session.query(SubscriptionPlan).filter(SubscriptionPlan.id == current.plan_id).first()
                if current else None
            )
            session.commit()
            if current:
                session.refresh(current)
            if plan:
                session.refresh(plan)
            if current:
                session.expunge(current)
            if plan:
                session.expunge(plan)
            return current, plan
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_user_subscriptions(self, user_id: int) -> list[UserSubscription]:
        session = self._session()
        try:
            return (
                session.query(UserSubscription)
                .filter(UserSubscription.user_id == user_id)
                .order_by(UserSubscription.created_at.desc())
                .all()
            )
        finally:
            session.close()

    def cancel_subscription(self, subscription_id: int) -> UserSubscription | None:
        session = self._session()
        try:
            sub = session.query(UserSubscription).filter(UserSubscription.id == subscription_id).first()
            if not sub:
                return None
            sub.status = "cancelled"
            sub.updated_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(sub)
            return sub
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def expire_subscription(self, subscription_id: int) -> UserSubscription | None:
        session = self._session()
        try:
            sub = session.query(UserSubscription).filter(UserSubscription.id == subscription_id).first()
            if not sub:
                return None
            sub.status = "expired"
            sub.updated_at = datetime.now(timezone.utc)

            # Also expire the user
            user = session.query(User).filter(User.id == sub.user_id).first()
            if user:
                user.status = "expired"
                user.updated_at = datetime.now(timezone.utc)

            session.commit()
            session.refresh(sub)
            return sub
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def expire_overdue(self) -> list[dict]:
        """Find and expire all active subscriptions past end_at. Returns list of expired user info."""
        session = self._session()
        try:
            now = datetime.now(timezone.utc)
            overdue = (
                session.query(UserSubscription)
                .filter(
                    UserSubscription.status == "active",
                    UserSubscription.end_at < now,
                )
                .all()
            )
            expired_users = []
            for sub in overdue:
                sub.status = "expired"
                sub.updated_at = now
                user = session.query(User).filter(User.id == sub.user_id).first()
                if user:
                    user.status = "expired"
                    user.updated_at = now
                    expired_users.append({
                        "user_id": user.id,
                        "name": user.full_name,
                        "email": user.email,
                        "mobile_number": user.mobile_number,
                    })
            session.commit()
            return expired_users
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
