"""Admin API - EazyFill support and abuse overview."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func

from app.core.db import get_session
from app.core.models import (
    PaymentRecord,
    PaymentWebhookEvent,
    UsageCycle,
    User,
    UserApiKey,
    UserApiKeyDevice,
    UserSubscription,
)

from .utils import _admin_guard

router = APIRouter(tags=["admin-eazyfill"])


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _money_total(rows: list[tuple[int | None, str | None]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for amount, currency in rows:
        code = str(currency or "INR").upper()
        totals[code] = totals.get(code, 0) + int(amount or 0)
    return totals


@router.get("/api/eazyfill/overview")
@router.get("/api/flowpilot/overview", include_in_schema=False)
async def eazyfill_overview(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied

    session = get_session()
    try:
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=7)
        total_users = session.query(User).count()
        active_users = session.query(User).filter(User.status == "active").count()
        blocked_users = session.query(User).filter(User.status == "blocked").count()
        active_subscriptions = session.query(UserSubscription).filter(UserSubscription.status == "active").count()
        active_keys = session.query(UserApiKey).filter(UserApiKey.status == "active").count()
        active_devices = session.query(UserApiKeyDevice).filter(UserApiKeyDevice.status == "active").count()
        pending_payments = session.query(PaymentRecord).filter(
            PaymentRecord.status.in_(["created", "pending_payment"])
        ).count()
        approved_rows = (
            session.query(PaymentRecord.amount, PaymentRecord.currency)
            .filter(PaymentRecord.status == "approved")
            .all()
        )
        usage = session.query(
            func.coalesce(func.sum(UsageCycle.used_count), 0),
            func.coalesce(func.sum(UsageCycle.monthly_limit), 0),
        ).one()
        recent_webhook_failures = session.query(PaymentWebhookEvent).filter(
            PaymentWebhookEvent.status == "failed",
            PaymentWebhookEvent.received_at >= since,
        ).count()
        quota_risk_users = session.query(UsageCycle).filter(
            UsageCycle.cycle_end_at > now,
            UsageCycle.monthly_limit > 0,
            UsageCycle.used_count >= UsageCycle.monthly_limit,
        ).count()

        return JSONResponse({
            "users": {
                "total": total_users,
                "active": active_users,
                "blocked": blocked_users,
            },
            "subscriptions": {
                "active": active_subscriptions,
            },
            "keys": {
                "active": active_keys,
                "active_devices": active_devices,
            },
            "billing": {
                "pending_payments": pending_payments,
                "approved_revenue": _money_total(approved_rows),
                "webhook_failures_7d": recent_webhook_failures,
            },
            "usage": {
                "used": int(usage[0] or 0),
                "limit": int(usage[1] or 0),
                "quota_risk_users": quota_risk_users,
            },
        })
    finally:
        session.close()


@router.get("/api/eazyfill/users/{user_id}/support")
@router.get("/api/flowpilot/users/{user_id}/support", include_in_schema=False)
async def eazyfill_user_support(request: Request, user_id: int) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied

    session = get_session()
    try:
        user = session.query(User).filter(User.id == int(user_id)).first()
        if not user:
            return JSONResponse({"error": "user_not_found"}, status_code=404)

        subscription = (
            session.query(UserSubscription)
            .filter(UserSubscription.user_id == user.id)
            .order_by(UserSubscription.created_at.desc())
            .first()
        )
        cycle = (
            session.query(UsageCycle)
            .filter(UsageCycle.user_id == user.id)
            .order_by(UsageCycle.cycle_end_at.desc())
            .first()
        )
        keys = (
            session.query(UserApiKey)
            .filter(UserApiKey.user_id == user.id)
            .order_by(UserApiKey.issued_at.desc())
            .all()
        )
        key_ids = [int(key.id) for key in keys]
        devices = (
            session.query(UserApiKeyDevice)
            .filter(UserApiKeyDevice.api_key_id.in_(key_ids))
            .order_by(UserApiKeyDevice.last_seen_at.desc())
            .all()
        ) if key_ids else []
        payments = (
            session.query(PaymentRecord)
            .filter(PaymentRecord.user_id == user.id)
            .order_by(PaymentRecord.created_at.desc())
            .limit(10)
            .all()
        )

        return JSONResponse({
            "user": user.to_dict(),
            "subscription": subscription.to_dict() if subscription else None,
            "usage": {
                "cycle_id": cycle.id if cycle else None,
                "used": cycle.used_count if cycle else 0,
                "limit": cycle.monthly_limit if cycle else 0,
                "blocked_at_limit": bool(cycle.blocked_at_limit) if cycle else False,
                "cycle_start_at": _iso(cycle.cycle_start_at) if cycle else None,
                "cycle_end_at": _iso(cycle.cycle_end_at) if cycle else None,
            },
            "keys": [key.to_dict() for key in keys],
            "devices": [{
                "id": device.id,
                "api_key_id": device.api_key_id,
                "device_fingerprint": device.device_fingerprint,
                "device_name": device.device_name,
                "status": device.status,
                "first_seen_at": _iso(device.first_seen_at),
                "last_seen_at": _iso(device.last_seen_at),
            } for device in devices],
            "payments": [payment.to_dict() for payment in payments],
        })
    finally:
        session.close()


@router.get("/api/eazyfill/abuse")
@router.get("/api/flowpilot/abuse", include_in_schema=False)
async def eazyfill_abuse_queue(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied

    session = get_session()
    try:
        now = datetime.now(timezone.utc)
        quota_cycles = (
            session.query(UsageCycle, User)
            .join(User, User.id == UsageCycle.user_id)
            .filter(
                UsageCycle.cycle_end_at > now,
                UsageCycle.monthly_limit > 0,
                UsageCycle.used_count >= UsageCycle.monthly_limit,
            )
            .order_by(UsageCycle.used_count.desc())
            .limit(limit)
            .all()
        )
        multi_device_keys = (
            session.query(UserApiKey.id, UserApiKey.user_id, func.count(UserApiKeyDevice.id).label("device_count"))
            .join(UserApiKeyDevice, UserApiKeyDevice.api_key_id == UserApiKey.id)
            .filter(UserApiKeyDevice.status == "active")
            .group_by(UserApiKey.id, UserApiKey.user_id)
            .having(func.count(UserApiKeyDevice.id) > 1)
            .limit(limit)
            .all()
        )
        failed_webhooks = (
            session.query(PaymentWebhookEvent)
            .filter(PaymentWebhookEvent.status == "failed")
            .order_by(PaymentWebhookEvent.received_at.desc())
            .limit(limit)
            .all()
        )
        return JSONResponse({
            "quota_exhausted": [{
                "user_id": user.id,
                "name": user.full_name,
                "status": user.status,
                "cycle_id": cycle.id,
                "used": cycle.used_count,
                "limit": cycle.monthly_limit,
                "cycle_end_at": _iso(cycle.cycle_end_at),
            } for cycle, user in quota_cycles],
            "multi_device_keys": [{
                "key_id": int(row.id),
                "user_id": int(row.user_id),
                "active_device_count": int(row.device_count),
            } for row in multi_device_keys],
            "failed_webhooks": [{
                "event_id": event.event_id,
                "provider": event.provider,
                "event_type": event.event_type,
                "payment_id": event.payment_id,
                "error_message": event.error_message,
                "received_at": _iso(event.received_at),
            } for event in failed_webhooks],
        })
    finally:
        session.close()
