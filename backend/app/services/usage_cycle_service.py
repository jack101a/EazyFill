"""Usage cycle tracking — monthly quota enforcement with atomic accounting."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.models import UsageCycle, UserSubscription, User


def _utcnow_db() -> datetime:
    """Naive UTC datetime for DB comparisons; SQLite drops timezone info."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class UsageCycleService:
    """Manages per-user monthly usage cycles with atomic quota tracking."""

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def _session(self) -> Session:
        return self._session_factory()

    def get_or_create_cycle(self, user_id: int) -> UsageCycle | None:
        """Get the current active usage cycle, or create one from the active subscription."""
        session = self._session()
        try:
            now = _utcnow_db()

            # Find active cycle
            cycle = (
                session.query(UsageCycle)
                .filter(
                    UsageCycle.user_id == user_id,
                    UsageCycle.cycle_start_at <= now,
                    UsageCycle.cycle_end_at > now,
                )
                .order_by(UsageCycle.cycle_start_at.desc())
                .first()
            )
            if cycle:
                return cycle

            # No active cycle — try to create from active subscription
            sub = (
                session.query(UserSubscription)
                .filter(
                    UserSubscription.user_id == user_id,
                    UserSubscription.status == "active",
                )
                .first()
            )
            if not sub:
                return None

            # Create new cycle
            cycle_start = sub.current_cycle_start_at or now
            cycle_end = sub.current_cycle_end_at or (now + timedelta(days=30))

            # If cycle is in the past, create a fresh one
            if cycle_end <= now:
                cycle_start = now
                cycle_end = now + timedelta(days=30)
                sub.current_cycle_start_at = cycle_start
                sub.current_cycle_end_at = cycle_end

            cycle = UsageCycle(
                user_id=user_id,
                subscription_id=sub.id,
                cycle_start_at=cycle_start,
                cycle_end_at=cycle_end,
                monthly_limit=sub.monthly_limit_snapshot,
                used_count=0,
            )
            session.add(cycle)
            session.commit()
            session.refresh(cycle)
            return cycle
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def check_quota(self, user_id: int) -> dict:
        """Check if user has remaining quota. Returns {allowed, used, limit, cycle_id}."""
        cycle = self.get_or_create_cycle(user_id)
        if not cycle:
            return {"allowed": False, "reason": "no_active_subscription", "used": 0, "limit": 0}

        if cycle.blocked_at_limit:
            return {"allowed": False, "reason": "quota_exceeded", "used": cycle.used_count, "limit": cycle.monthly_limit}

        if cycle.used_count >= cycle.monthly_limit:
            return {"allowed": False, "reason": "quota_exceeded", "used": cycle.used_count, "limit": cycle.monthly_limit}

        return {"allowed": True, "used": cycle.used_count, "limit": cycle.monthly_limit, "cycle_id": cycle.id}

    def increment_usage(self, user_id: int, amount: int = 1) -> dict:
        """Atomically increment usage count. Returns updated quota state."""
        session = self._session()
        try:
            cycle = self.get_or_create_cycle(user_id)
            if not cycle:
                return {"allowed": False, "reason": "no_active_subscription", "used": 0, "limit": 0}

            # Re-fetch in this session
            cycle = session.query(UsageCycle).filter(UsageCycle.id == cycle.id).first()
            if not cycle:
                return {"allowed": False, "reason": "cycle_not_found", "used": 0, "limit": 0}

            if cycle.blocked_at_limit:
                return {"allowed": False, "reason": "quota_exceeded", "used": cycle.used_count, "limit": cycle.monthly_limit}

            new_used = cycle.used_count + amount
            if new_used > cycle.monthly_limit:
                cycle.blocked_at_limit = True
                session.commit()
                return {"allowed": False, "reason": "quota_exceeded", "used": new_used, "limit": cycle.monthly_limit}

            cycle.used_count = new_used
            cycle.updated_at = _utcnow_db()
            session.commit()
            return {"allowed": True, "used": new_used, "limit": cycle.monthly_limit, "cycle_id": cycle.id}
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def increment_usage_atomic(self, user_id: int, amount: int = 1) -> dict:
        """Atomically increment usage count using a single UPDATE with WHERE clause.
        This prevents TOCTOU races that could exceed the monthly limit under concurrent load."""
        cycle = self.get_or_create_cycle(user_id)
        if not cycle:
            return {"allowed": False, "reason": "no_active_subscription", "used": 0, "limit": 0}
        cycle_id = int(cycle.id)
        session = self._session()
        try:
            now = _utcnow_db()
            # Atomic: increment only if under limit, returns rowcount = 1 if successful
            result = session.execute(
                text(
                    "UPDATE usage_cycles SET used_count = used_count + :amount, updated_at = :now "
                    "WHERE id = :cycle_id "
                    "AND used_count + :amount <= monthly_limit AND blocked_at_limit = 0"
                ),
                {"amount": amount, "now": now, "cycle_id": cycle_id}
            )
            session.commit()
            if result.rowcount > 0:
                # Re-fetch to get updated values
                cycle = session.query(UsageCycle).filter(UsageCycle.id == cycle_id).first()
                if cycle:
                    return {"allowed": True, "used": cycle.used_count, "limit": cycle.monthly_limit, "cycle_id": cycle.id}
            cycle = session.query(UsageCycle).filter(UsageCycle.id == cycle_id).first()
            if cycle:
                return {
                    "allowed": False,
                    "reason": "quota_exceeded",
                    "used": cycle.used_count,
                    "limit": cycle.monthly_limit,
                    "cycle_id": cycle.id,
                }
            return {"allowed": False, "reason": "cycle_not_found", "used": 0, "limit": 0}
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def refund_usage_atomic(self, user_id: int, amount: int = 1, cycle_id: int | None = None) -> dict:
        """Refund a previously reserved quota unit without dropping usage below zero."""
        if amount <= 0:
            return {"refunded": False, "reason": "invalid_amount"}
        if cycle_id is None:
            cycle = self.get_or_create_cycle(user_id)
            if not cycle:
                return {"refunded": False, "reason": "no_active_subscription", "used": 0, "limit": 0}
            cycle_id = int(cycle.id)

        session = self._session()
        try:
            now = _utcnow_db()
            result = session.execute(
                text(
                    "UPDATE usage_cycles "
                    "SET used_count = CASE WHEN used_count >= :amount THEN used_count - :amount ELSE 0 END, "
                    "blocked_at_limit = 0, updated_at = :now "
                    "WHERE id = :cycle_id AND user_id = :user_id"
                ),
                {"amount": amount, "now": now, "cycle_id": int(cycle_id), "user_id": int(user_id)},
            )
            session.commit()
            cycle = session.query(UsageCycle).filter(UsageCycle.id == int(cycle_id)).first()
            if result.rowcount > 0 and cycle:
                return {
                    "refunded": True,
                    "used": cycle.used_count,
                    "limit": cycle.monthly_limit,
                    "cycle_id": cycle.id,
                }
            return {"refunded": False, "reason": "cycle_not_found", "used": 0, "limit": 0}
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_user_usage(self, user_id: int) -> dict:
        """Get current usage summary for a user."""
        cycle = self.get_or_create_cycle(user_id)
        if not cycle:
            return {"has_subscription": False, "used": 0, "limit": 0, "remaining": 0}

        return {
            "has_subscription": True,
            "cycle_id": cycle.id,
            "used": cycle.used_count,
            "limit": cycle.monthly_limit,
            "remaining": max(0, cycle.monthly_limit - cycle.used_count),
            "blocked": cycle.blocked_at_limit,
            "cycle_start": cycle.cycle_start_at.isoformat() if cycle.cycle_start_at else None,
            "cycle_end": cycle.cycle_end_at.isoformat() if cycle.cycle_end_at else None,
        }

    def get_usage_history(self, user_id: int, limit: int = 12) -> list[dict]:
        """Return recent usage cycles for dashboard history views."""
        session = self._session()
        try:
            rows = (
                session.query(UsageCycle)
                .filter(UsageCycle.user_id == int(user_id))
                .order_by(UsageCycle.cycle_start_at.desc())
                .limit(max(1, min(int(limit or 12), 50)))
                .all()
            )
            items = []
            for cycle in rows:
                used = int(cycle.used_count or 0)
                quota = int(cycle.monthly_limit or 0)
                remaining = max(0, quota - used)
                items.append({
                    "cycle_id": cycle.id,
                    "cycle_start": cycle.cycle_start_at.isoformat() if cycle.cycle_start_at else None,
                    "cycle_end": cycle.cycle_end_at.isoformat() if cycle.cycle_end_at else None,
                    "captcha_used": used,
                    "captcha_limit": quota,
                    "captcha_remaining": remaining,
                    "blocked": bool(cycle.blocked_at_limit),
                    "created_at": cycle.created_at.isoformat() if cycle.created_at else None,
                    "updated_at": cycle.updated_at.isoformat() if cycle.updated_at else None,
                })
            return items
        finally:
            session.close()

    def reset_cycle(self, user_id: int) -> UsageCycle | None:
        """Force-reset the current cycle (admin override for bonus quota)."""
        session = self._session()
        try:
            now = _utcnow_db()
            old = (
                session.query(UsageCycle)
                .filter(UsageCycle.user_id == user_id, UsageCycle.cycle_end_at > now)
                .first()
            )
            if old:
                old.cycle_end_at = now  # Close old cycle
                old.blocked_at_limit = False

            # Create new cycle with same limit
            new_cycle = UsageCycle(
                user_id=user_id,
                subscription_id=old.subscription_id if old else 0,
                cycle_start_at=now,
                cycle_end_at=now + timedelta(days=30),
                monthly_limit=old.monthly_limit if old else 3000,
                used_count=0,
            )
            session.add(new_cycle)
            session.commit()
            session.refresh(new_cycle)
            return new_cycle
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
