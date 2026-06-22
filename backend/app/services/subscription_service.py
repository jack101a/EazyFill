"""Subscription management service — plans, user subscriptions, lifecycle."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session
from app.core.models import PaymentRecord, SubscriptionPlan, UsageCycle, UserSubscription, User
from app.services.promo_plan_policy import (
    check_promo_plan_eligibility,
    validate_promo_audience,
)


DEFAULT_CHECKOUT_PLAN_SPECS: tuple[dict, ...] = (
    {
        "code": "free",
        "name": "Free",
        "description": "Starter access for trying EazyFill.",
        "monthly_limit": 100,
        "duration_days": 30,
        "price_amount": 0,
        "currency": "INR",
        "max_devices": 1,
        "allowed_services": {
            "captcha": True,
            "autofill": True,
            "userscripts": True,
            "sync": False,
            "portable_pack": False,
            "local_backup_export": False,
            "local_backup_import": False,
            "rules_limit": 25,
            "scripts_limit": 5,
            "script_storage_mb": 5,
            "captcha_credit_cost": 1,
        },
        "rate_limit_rpm": 30,
        "rate_limit_burst": 5,
        "show_in_checkout": False,
        "is_promo": False,
        "promo_audience": "both",
    },
    {
        "code": "basic",
        "name": "Basic",
        "description": "Core EazyFill automation, sync, and import/export.",
        "monthly_limit": 500,
        "duration_days": 30,
        "price_amount": 14900,
        "currency": "INR",
        "max_devices": 2,
        "allowed_services": {
            "captcha": True,
            "autofill": True,
            "userscripts": True,
            "sync": True,
            "portable_pack": True,
            "local_backup_export": True,
            "local_backup_import": True,
            "rules_limit": 100,
            "scripts_limit": 25,
            "script_storage_mb": 25,
            "captcha_credit_cost": 1,
        },
        "rate_limit_rpm": 60,
        "rate_limit_burst": 10,
        "show_in_checkout": True,
        "is_promo": False,
        "promo_audience": "both",
    },
    {
        "code": "pro",
        "name": "Pro",
        "description": "Higher credits, more devices, and priority CAPTCHA solving.",
        "monthly_limit": 2500,
        "duration_days": 30,
        "price_amount": 49900,
        "currency": "INR",
        "max_devices": 5,
        "allowed_services": {
            "captcha": True,
            "autofill": True,
            "userscripts": True,
            "sync": True,
            "portable_pack": True,
            "local_backup_export": True,
            "local_backup_import": True,
            "unlimited_rules": True,
            "js_rules": True,
            "priority_solving": True,
            "rules_limit": None,
            "scripts_limit": 100,
            "script_storage_mb": 100,
            "captcha_credit_cost": 1,
        },
        "rate_limit_rpm": 120,
        "rate_limit_burst": 20,
        "show_in_checkout": True,
        "is_promo": False,
        "promo_audience": "both",
    },
)


class SubscriptionService:
    """Manages subscription plans and user subscription lifecycle."""

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def _session(self) -> Session:
        return self._session_factory()

    # ── Plans ──────────────────────────────────────────────────────────────

    def ensure_default_checkout_plans(
        self,
        codes: set[str] | None = None,
        *,
        only_when_empty: bool = False,
    ) -> list[SubscriptionPlan]:
        """Create or repair the built-in checkout catalog when deployment data is empty."""
        wanted_codes = {str(code or "").strip().lower() for code in (codes or set()) if str(code or "").strip()}
        specs = [
            spec for spec in DEFAULT_CHECKOUT_PLAN_SPECS
            if not wanted_codes or str(spec["code"]) in wanted_codes
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
                plan = session.query(SubscriptionPlan).filter(SubscriptionPlan.code == spec["code"]).first()
                values = {**spec, "allowed_services": deepcopy(spec.get("allowed_services") or {})}
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
            return (
                session.query(UserSubscription)
                .filter(
                    UserSubscription.user_id == user_id,
                    UserSubscription.status == "active",
                )
                .order_by(UserSubscription.created_at.desc())
                .first()
            )
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
