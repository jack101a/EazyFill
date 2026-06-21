"""Payment management service — records, approval, rejection."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session, joinedload

from app.core.config import Settings
from app.core.models import PaymentRecord
from app.services.promo_plan_policy import check_promo_plan_eligibility


class PaymentService:
    """Manages payment records and approval workflow."""

    def __init__(self, session_factory, settings: Settings):
        self._session_factory = session_factory
        self._settings = settings

    def _session(self) -> Session:
        return self._session_factory()

    def create_payment(
        self,
        user_id: int,
        amount: int,
        payment_method: str = "razorpay",
        payment_provider: str = "razorpay",
        payment_note: str = "",
        subscription_id: int | None = None,
        plan_id: int | None = None,
        payment_ref: str | None = None,
    ) -> PaymentRecord:
        session = self._session()
        try:
            if plan_id is not None:
                from app.core.models import SubscriptionPlan, User

                user = session.query(User).filter(User.id == int(user_id)).first()
                plan = session.query(SubscriptionPlan).filter(SubscriptionPlan.id == int(plan_id)).first()
                if not user or not plan:
                    raise ValueError("User or plan not found")
                eligibility = check_promo_plan_eligibility(session, user, plan)
                if not eligibility.eligible:
                    raise ValueError(eligibility.reason)

            now = datetime.now(timezone.utc)
            payment = PaymentRecord(
                user_id=user_id,
                subscription_id=subscription_id,
                plan_id=plan_id,
                payment_method=payment_method,
                payment_provider=payment_provider,
                amount=amount,
                payment_note=payment_note,
                payment_ref=payment_ref,
                status="created",
                submitted_at=now,
                expires_at=now + timedelta(hours=1),
            )
            session.add(payment)
            session.commit()
            session.refresh(payment)
            return payment
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def activate_payment(
        self,
        payment_id: int,
        *,
        verified_by_admin_id: int | None = None,
        triggered_by: str = "admin",
    ) -> dict | None:
        """Approve a payment and atomically activate the user's subscription/key."""

        from app.core.models import (
            SubscriptionPlan,
            UsageCycle,
            User,
            UserApiKey,
            UserSubscription,
        )
        from app.core.security import generate_plain_api_key, hash_api_key

        session = self._session()
        plain_key_for_user = None
        try:
            payment = session.query(PaymentRecord).filter(PaymentRecord.id == payment_id).first()
            if not payment:
                return None

            user = session.query(User).filter(User.id == payment.user_id).first()
            if not user:
                raise ValueError("Payment user not found")

            now = datetime.now(timezone.utc)
            plan = None
            if payment.plan_id:
                plan = session.query(SubscriptionPlan).filter(SubscriptionPlan.id == payment.plan_id).first()
            if not plan:
                plan = (
                    session.query(SubscriptionPlan)
                    .filter(
                        SubscriptionPlan.price_amount == payment.amount,
                        SubscriptionPlan.currency == payment.currency,
                        SubscriptionPlan.is_active == True,
                    )
                    .first()
                )
            if not plan:
                raise ValueError("No active plan matches this payment")
            eligibility = check_promo_plan_eligibility(
                session,
                user,
                plan,
                current_payment_id=int(payment.id),
            )
            if not eligibility.eligible:
                raise ValueError(eligibility.reason)

            payment.status = "approved"
            payment.plan_id = plan.id
            payment.verified_by_admin_id = verified_by_admin_id
            payment.verified_at = now
            payment.updated_at = now

            active_sub = None
            if payment.subscription_id:
                active_sub = (
                    session.query(UserSubscription)
                    .filter(UserSubscription.id == payment.subscription_id)
                    .first()
                )

            if not active_sub or active_sub.status != "active":
                session.query(UserSubscription).filter(
                    UserSubscription.user_id == user.id,
                    UserSubscription.status == "active",
                ).update({"status": "expired", "updated_at": now})

                active_sub = UserSubscription(
                    user_id=user.id,
                    plan_id=plan.id,
                    status="active",
                    monthly_limit_snapshot=plan.monthly_limit,
                    start_at=now,
                    end_at=now + timedelta(days=plan.duration_days),
                    billing_anchor_day=now.day,
                    current_cycle_start_at=now,
                    current_cycle_end_at=now + timedelta(days=30),
                    approved_by_admin_id=verified_by_admin_id,
                    approved_at=now,
                )
                session.add(active_sub)
                session.flush()
                payment.subscription_id = active_sub.id

                cycle = UsageCycle(
                    user_id=user.id,
                    subscription_id=active_sub.id,
                    cycle_start_at=now,
                    cycle_end_at=now + timedelta(days=30),
                    monthly_limit=plan.monthly_limit,
                    used_count=0,
                )
                session.add(cycle)

            user.status = "active"
            user.updated_at = now

            existing_key = (
                session.query(UserApiKey)
                .filter(UserApiKey.user_id == user.id, UserApiKey.status == "active")
                .first()
            )
            if not existing_key:
                created_plain = generate_plain_api_key(self._settings)
                created_key = UserApiKey(
                    user_id=user.id,
                    key_hash=hash_api_key(created_plain, self._settings.auth.hash_salt),
                    key_prefix_display=created_plain[:10] + "...",
                    status="active",
                    key_version=1,
                    issued_at=now,
                    expires_at=None,
                )
                session.add(created_key)
                session.flush()
                plain_key_for_user = created_plain
                existing_key = created_key
            else:
                existing_key.expires_at = None
                existing_key.revoked_at = None
                existing_key.revoked_reason = ""

            session.commit()
            session.refresh(payment)

            return {
                "payment": payment.to_dict(),
                "plain_key": plain_key_for_user,
                "user": {
                    "id": user.id,
                    "full_name": user.full_name,
                    "email": user.email,
                    "mobile_number": user.mobile_number,
                },
                "plan": plan.to_dict(),
                "triggered_by": triggered_by,
            }
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_payment(self, payment_id: int) -> PaymentRecord | None:
        session = self._session()
        try:
            return session.query(PaymentRecord).filter(PaymentRecord.id == payment_id).first()
        finally:
            session.close()

    def append_payment_note(self, payment_id: int, note: str) -> PaymentRecord | None:
        session = self._session()
        try:
            payment = session.query(PaymentRecord).filter(PaymentRecord.id == payment_id).first()
            if not payment:
                return None
            cleaned_note = str(note or "").strip()
            if cleaned_note:
                existing = str(payment.payment_note or "").strip()
                payment.payment_note = f"{existing}\n{cleaned_note}".strip() if existing else cleaned_note
                payment.updated_at = datetime.now(timezone.utc)
                session.commit()
                session.refresh(payment)
            return payment
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def record_provider_payment(
        self,
        payment_id: int,
        *,
        provider: str,
        provider_payment_id: str = "",
        provider_order_id: str = "",
        provider_signature: str = "",
        provider_status: str = "captured",
        provider_payload_json: str = "",
    ) -> PaymentRecord | None:
        session = self._session()
        try:
            payment = session.query(PaymentRecord).filter(PaymentRecord.id == int(payment_id)).first()
            if not payment:
                return None
            now = datetime.now(timezone.utc)
            payment.payment_provider = provider
            payment.payment_method = provider
            if provider_order_id:
                payment.provider_order_id = provider_order_id
            if provider_payment_id:
                payment.provider_payment_id = provider_payment_id
            if provider_signature:
                payment.provider_signature = provider_signature
            payment.provider_status = provider_status
            if provider_payload_json:
                payment.provider_payload_json = provider_payload_json
            payment.updated_at = now
            session.commit()
            session.refresh(payment)
            return payment
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def list_payments(
        self,
        status: str | None = None,
        user_id: int | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[PaymentRecord], int]:
        session = self._session()
        try:
            q = session.query(PaymentRecord).options(
                joinedload(PaymentRecord.user),
                joinedload(PaymentRecord.plan),
            )
            if status:
                q = q.filter(PaymentRecord.status == status)
            if user_id:
                q = q.filter(PaymentRecord.user_id == user_id)
            total = q.count()
            payments = q.order_by(PaymentRecord.created_at.desc()).offset(offset).limit(limit).all()
            return payments, total
        finally:
            session.close()

    def approve_payment(
        self,
        payment_id: int,
        verified_by_admin_id: int | None = None,
    ) -> PaymentRecord | None:
        session = self._session()
        try:
            payment = session.query(PaymentRecord).filter(PaymentRecord.id == payment_id).first()
            if not payment:
                return None
            now = datetime.now(timezone.utc)
            payment.status = "approved"
            payment.verified_by_admin_id = verified_by_admin_id
            payment.verified_at = now
            payment.updated_at = now
            session.commit()
            session.refresh(payment)
            return payment
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def reject_payment(
        self,
        payment_id: int,
        rejection_reason: str = "",
        verified_by_admin_id: int | None = None,
    ) -> PaymentRecord | None:
        session = self._session()
        try:
            payment = session.query(PaymentRecord).filter(PaymentRecord.id == payment_id).first()
            if not payment:
                return None
            now = datetime.now(timezone.utc)
            payment.status = "rejected"
            payment.rejection_reason = rejection_reason
            payment.verified_by_admin_id = verified_by_admin_id
            payment.verified_at = now
            payment.updated_at = now
            session.commit()
            session.refresh(payment)
            return payment
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_pending_count(self) -> int:
        session = self._session()
        try:
            return session.query(PaymentRecord).filter(
                PaymentRecord.status.in_(["created", "pending_payment"])
            ).count()
        finally:
            session.close()

    def get_user_payments(self, user_id: int) -> list[PaymentRecord]:
        session = self._session()
        try:
            return (
                session.query(PaymentRecord)
                .filter(PaymentRecord.user_id == user_id)
                .order_by(PaymentRecord.created_at.desc())
                .all()
            )
        finally:
            session.close()
