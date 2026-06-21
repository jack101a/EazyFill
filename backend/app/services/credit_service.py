"""EazyFill credit accounting facade."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.models import CreditLedgerEntry, MeteringPolicy, SubscriptionPlan
from app.services.usage_cycle_service import UsageCycleService

CAPTCHA_SOLVE_IMAGE = "captcha.solve.image"

DEFAULT_METERING_POLICIES: dict[str, dict[str, Any]] = {
    CAPTCHA_SOLVE_IMAGE: {
        "event_type": CAPTCHA_SOLVE_IMAGE,
        "display_name": "Image CAPTCHA solve",
        "unit_cost": 1,
        "is_active": True,
        "metadata": {},
    },
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _positive_int(value: object, default: int = 1) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


class CreditService:
    """Expose EazyFill quota semantics on top of existing usage cycles."""

    def __init__(
        self,
        usage_cycle_service: UsageCycleService,
        session_factory: Callable[[], Session] | None = None,
    ) -> None:
        self._usage_cycle_service = usage_cycle_service
        self._session_factory = session_factory

    def get_policy(self, event_type: str, *, plan: SubscriptionPlan | None = None) -> dict[str, Any]:
        event_type = str(event_type or "").strip() or CAPTCHA_SOLVE_IMAGE
        policy = dict(DEFAULT_METERING_POLICIES.get(event_type) or {
            "event_type": event_type,
            "display_name": event_type.replace(".", " ").title(),
            "unit_cost": 0,
            "is_active": True,
            "metadata": {},
        })

        db_policy = self._db_policy(event_type)
        if db_policy:
            policy.update(db_policy)

        override_cost = self._plan_cost_override(plan, event_type)
        if override_cost is not None:
            policy["unit_cost"] = override_cost

        policy["unit_cost"] = _positive_int(policy.get("unit_cost"), 0)
        policy["is_active"] = bool(policy.get("is_active", True))
        return policy

    def get_policies(self, *, plan: SubscriptionPlan | None = None) -> dict[str, Any]:
        event_types = set(DEFAULT_METERING_POLICIES)
        policies = self._db_policies()
        event_types.update(policies)
        return {
            event_type: self.get_policy(event_type, plan=plan)
            for event_type in sorted(event_types)
        }

    def quote(
        self,
        event_type: str,
        *,
        plan: SubscriptionPlan | None = None,
        amount: int = 1,
    ) -> dict[str, Any]:
        units = max(1, int(amount or 1))
        policy = self.get_policy(event_type, plan=plan)
        unit_cost = _positive_int(policy.get("unit_cost"), 0)
        return {
            **policy,
            "amount": units,
            "credits": unit_cost * units,
        }

    def get_balance(
        self,
        user_id: int | None,
        *,
        plan: SubscriptionPlan | None = None,
        cloud_sync_enabled: bool = False,
        rules_count: int = 0,
        scripts_count: int = 0,
        script_storage_used_bytes: int = 0,
        sync_backup_size_bytes: int = 0,
        last_sync_at: str | None = None,
    ) -> dict[str, Any]:
        usage = self._usage(user_id)
        used = int(usage.get("used") or 0)
        limit = int(usage.get("limit") or 0)
        remaining = max(0, int(usage.get("remaining") if usage.get("remaining") is not None else limit - used))
        captcha_quote = self.quote(CAPTCHA_SOLVE_IMAGE, plan=plan)
        return {
            "captcha": {
                "used_today": used,
                "daily_limit": limit,
                "remaining": remaining,
                "resets_at": usage.get("cycle_end"),
                "cycle_id": usage.get("cycle_id"),
                "meter_event_type": CAPTCHA_SOLVE_IMAGE,
                "solve_cost": int(captcha_quote.get("credits") or 0),
                "unit_cost": int(captcha_quote.get("unit_cost") or 0),
            },
            "autofill": {
                "rules_count": max(0, int(rules_count or 0)),
                "rules_limit": None,
                "executions_today": 0,
                "executions_limit": None,
            },
            "scripts": {
                "count": max(0, int(scripts_count or 0)),
                "limit": None,
                "storage_used_bytes": max(0, int(script_storage_used_bytes or 0)),
                "storage_limit_bytes": None,
            },
            "sync": {
                "enabled": bool(cloud_sync_enabled),
                "last_sync_at": last_sync_at,
                "backup_size_bytes": max(0, int(sync_backup_size_bytes or 0)),
            },
            "metering": self.get_policies(plan=plan),
        }

    def reserve(
        self,
        event_type: str,
        user_id: int | None,
        *,
        plan: SubscriptionPlan | None = None,
        subscription_id: int | None = None,
        amount: int = 1,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        quote = self.quote(event_type, plan=plan, amount=amount)
        credits = int(quote.get("credits") or 0)
        if not user_id:
            return self._with_quote(
                {"allowed": True, "metered": False, "used": 0, "limit": 0, "cycle_id": None},
                quote,
            )
        if credits <= 0:
            return self._with_quote(
                {"allowed": True, "metered": True, "used": 0, "limit": 0, "cycle_id": None},
                quote,
            )

        result = self._usage_cycle_service.increment_usage_atomic(int(user_id), amount=credits)
        result = self._with_quote(result, quote)
        if result.get("allowed"):
            self._record_ledger(
                user_id=int(user_id),
                subscription_id=subscription_id,
                cycle_id=result.get("cycle_id"),
                event_type=quote["event_type"],
                status="reserved",
                credit_delta=-credits,
                unit_cost=int(quote.get("unit_cost") or 0),
                amount=int(quote.get("amount") or 1),
                idempotency_key=idempotency_key,
                metadata=metadata,
            )
        return result

    def refund(
        self,
        event_type: str,
        user_id: int | None,
        *,
        plan: SubscriptionPlan | None = None,
        subscription_id: int | None = None,
        amount: int = 1,
        cycle_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        quote = self.quote(event_type, plan=plan, amount=amount)
        credits = int(quote.get("credits") or 0)
        if not user_id:
            return self._with_quote({"refunded": False, "metered": False, "reason": "unmetered_key"}, quote)
        if credits <= 0:
            return self._with_quote({"refunded": False, "metered": True, "reason": "zero_cost"}, quote)
        result = self._usage_cycle_service.refund_usage_atomic(
            int(user_id),
            amount=credits,
            cycle_id=cycle_id,
        )
        result = self._with_quote(result, quote)
        if result.get("refunded"):
            self._record_ledger(
                user_id=int(user_id),
                subscription_id=subscription_id,
                cycle_id=result.get("cycle_id") or cycle_id,
                event_type=quote["event_type"],
                status="refunded",
                credit_delta=credits,
                unit_cost=int(quote.get("unit_cost") or 0),
                amount=int(quote.get("amount") or 1),
                metadata=metadata,
            )
        return result

    def reserve_captcha(
        self,
        user_id: int | None,
        *,
        plan: SubscriptionPlan | None = None,
        subscription_id: int | None = None,
        amount: int = 1,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return self.reserve(
            CAPTCHA_SOLVE_IMAGE,
            user_id,
            plan=plan,
            subscription_id=subscription_id,
            amount=amount,
            metadata=metadata,
            idempotency_key=idempotency_key,
        )

    def refund_captcha(
        self,
        user_id: int | None,
        *,
        plan: SubscriptionPlan | None = None,
        subscription_id: int | None = None,
        amount: int = 1,
        cycle_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.refund(
            CAPTCHA_SOLVE_IMAGE,
            user_id,
            plan=plan,
            subscription_id=subscription_id,
            amount=amount,
            cycle_id=cycle_id,
            metadata=metadata,
        )

    def _usage(self, user_id: int | None) -> dict[str, Any]:
        if not user_id:
            return {"used": 0, "limit": 3000, "remaining": 3000, "cycle_end": None, "cycle_id": None}
        return self._usage_cycle_service.get_user_usage(int(user_id))

    def _db_policy(self, event_type: str) -> dict[str, Any] | None:
        if self._session_factory is None:
            return None
        session = self._session_factory()
        try:
            policy = session.query(MeteringPolicy).filter(MeteringPolicy.event_type == event_type).first()
            return policy.to_dict() if policy else None
        except Exception:
            session.rollback()
            return None
        finally:
            session.close()

    def _db_policies(self) -> dict[str, dict[str, Any]]:
        if self._session_factory is None:
            return {}
        session = self._session_factory()
        try:
            rows = session.query(MeteringPolicy).all()
            return {row.event_type: row.to_dict() for row in rows}
        except Exception:
            session.rollback()
            return {}
        finally:
            session.close()

    def _plan_cost_override(self, plan: SubscriptionPlan | None, event_type: str) -> int | None:
        if plan is None:
            return None
        entitlements = plan.allowed_services or {}
        cost_maps = [
            entitlements.get("credit_costs"),
            entitlements.get("metering"),
            entitlements.get("metering_costs"),
        ]
        for cost_map in cost_maps:
            if isinstance(cost_map, dict) and event_type in cost_map:
                return _positive_int(cost_map.get(event_type), 0)
        if event_type == CAPTCHA_SOLVE_IMAGE:
            for key in ("captcha_solve_cost", "captcha_credit_cost"):
                if key in entitlements:
                    return _positive_int(entitlements.get(key), 0)
        return None

    def _with_quote(self, payload: dict[str, Any], quote: dict[str, Any]) -> dict[str, Any]:
        credits = int(quote.get("credits") or 0)
        return {
            **payload,
            "event_type": quote.get("event_type"),
            "unit_cost": int(quote.get("unit_cost") or 0),
            "amount": int(quote.get("amount") or 1),
            "credits_charged": credits,
            "credits_used": credits,
            "metered": payload.get("metered", True),
        }

    def _record_ledger(
        self,
        *,
        user_id: int,
        subscription_id: int | None,
        cycle_id: int | None,
        event_type: str,
        status: str,
        credit_delta: int,
        unit_cost: int,
        amount: int,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self._session_factory is None:
            return
        session = self._session_factory()
        try:
            session.add(CreditLedgerEntry(
                user_id=user_id,
                subscription_id=subscription_id,
                cycle_id=cycle_id,
                event_type=event_type,
                status=status,
                credit_delta=credit_delta,
                unit_cost=unit_cost,
                amount=amount,
                idempotency_key=idempotency_key,
                metadata_json=metadata or {},
                created_at=_utcnow(),
            ))
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()
