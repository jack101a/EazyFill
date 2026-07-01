"""Admin API — User management (CRUD, status, search)."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse

from app.core.models import (
    CreditLedgerEntry,
    EncryptedBackup,
    PaymentRecord,
    SubscriptionPlan,
    UsageCycle,
    User,
    UserApiKey,
    UserApiKeyDevice,
    UserSession,
    UserSubscription,
)
from app.core.db import get_session
from app.services.promo_plan_policy import check_promo_plan_eligibility
from sqlalchemy import func

from .utils import _admin_guard

router = APIRouter(tags=["admin-users"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _serialize_subscription(sub: UserSubscription, plan: SubscriptionPlan | None = None) -> dict:
    data = sub.to_dict()
    if plan is not None:
        data["plan_name"] = plan.name
        data["plan_code"] = plan.code
        data["plan_duration_days"] = plan.duration_days
        data["plan_monthly_limit"] = plan.monthly_limit
        data["plan_rate_limit_rpm"] = plan.rate_limit_rpm
        data["plan_rate_limit_burst"] = plan.rate_limit_burst
    return data


def _serialize_active_key(key: UserApiKey | None) -> dict | None:
    return key.to_dict() if key else None


def _user_key_usage_summary(session, user_id: int) -> dict:
    keys = (
        session.query(UserApiKey)
        .filter(UserApiKey.user_id == user_id)
        .all()
    )
    total = sum(int(key.usage_count or 0) for key in keys)
    last_used = max((key.last_used_at for key in keys if key.last_used_at), default=None)
    return {
        "total_usage_count": total,
        "last_used_at": last_used.isoformat() if last_used else None,
    }


def _today_ledger_usage(session, user_id: int, now: datetime) -> dict[str, Any]:
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    rows = (
        session.query(CreditLedgerEntry.event_type, func.coalesce(func.sum(CreditLedgerEntry.credit_delta), 0))
        .filter(
            CreditLedgerEntry.user_id == int(user_id),
            CreditLedgerEntry.created_at >= day_start,
            CreditLedgerEntry.credit_delta < 0,
        )
        .group_by(CreditLedgerEntry.event_type)
        .all()
    )
    by_event = {event_type: abs(int(total or 0)) for event_type, total in rows}
    return {
        "date": day_start.date().isoformat(),
        "credits_used": sum(by_event.values()),
        "by_event": by_event,
    }


def _latest_activity_at(*values: datetime | None) -> str | None:
    normalized = []
    for value in values:
        if not value:
            continue
        normalized.append(value if value.tzinfo else value.replace(tzinfo=timezone.utc))
    latest = max(normalized, default=None)
    return latest.isoformat() if latest else None


def _ensure_usage_cycle(session, user_id: int, subscription_id: int, plan: SubscriptionPlan, now: datetime) -> None:
    existing = (
        session.query(UsageCycle)
        .filter(UsageCycle.user_id == user_id, UsageCycle.subscription_id == subscription_id)
        .first()
    )
    if existing:
        existing.monthly_limit = int(plan.monthly_limit or existing.monthly_limit or 0)
        existing.updated_at = now
        return
    session.add(UsageCycle(
        user_id=user_id,
        subscription_id=subscription_id,
        cycle_start_at=now,
        cycle_end_at=now + timedelta(days=30),
        monthly_limit=int(plan.monthly_limit or 0),
        used_count=0,
    ))


def _create_active_subscription(
    session,
    user: User,
    plan: SubscriptionPlan,
    now: datetime,
    *,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    expire_existing: bool = True,
) -> UserSubscription:
    eligibility = check_promo_plan_eligibility(session, user, plan)
    if not eligibility.eligible:
        raise ValueError(eligibility.reason)

    if expire_existing:
        session.query(UserSubscription).filter(
            UserSubscription.user_id == user.id,
            UserSubscription.status == "active",
        ).update({"status": "expired", "updated_at": now})

    start = start_at or now
    end = end_at or (start + timedelta(days=int(plan.duration_days or 30)))
    sub = UserSubscription(
        user_id=user.id,
        plan_id=plan.id,
        status="active",
        monthly_limit_snapshot=int(plan.monthly_limit or 0),
        start_at=start,
        end_at=end,
        billing_anchor_day=start.day,
        current_cycle_start_at=now,
        current_cycle_end_at=now + timedelta(days=30),
        approved_at=now,
    )
    session.add(sub)
    session.flush()
    _ensure_usage_cycle(session, int(user.id), int(sub.id), plan, now)
    user.status = "active"
    user.updated_at = now
    return sub


@router.get("/api/users")
async def list_users(
    request: Request,
    status: str | None = Query(None),
    search: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    users, total = container.user_service.list_users(
        status=status, search=search, offset=offset, limit=limit
    )
    # Enrich with subscription info
    session = get_session()
    try:
        now = _utcnow()
        user_dicts = []
        for u in users:
            d = u.to_dict()
            active_sub = session.query(UserSubscription).filter(
                UserSubscription.user_id == u.id,
                UserSubscription.status == "active",
            ).order_by(UserSubscription.created_at.desc()).first()
            latest_sub = session.query(UserSubscription).filter(
                UserSubscription.user_id == u.id,
            ).order_by(UserSubscription.created_at.desc()).first()
            sub = active_sub or latest_sub
            plan = session.query(SubscriptionPlan).filter(SubscriptionPlan.id == sub.plan_id).first() if sub else None
            cycle = None
            if sub:
                cycle = session.query(UsageCycle).filter(
                    UsageCycle.user_id == u.id,
                    UsageCycle.subscription_id == sub.id,
                ).order_by(UsageCycle.cycle_start_at.desc()).first()
            if not cycle:
                cycle = session.query(UsageCycle).filter(
                    UsageCycle.user_id == u.id,
                ).order_by(UsageCycle.cycle_end_at.desc()).first()
            active_key = (
                session.query(UserApiKey)
                .filter(UserApiKey.user_id == u.id, UserApiKey.status == "active")
                .order_by(UserApiKey.issued_at.desc())
                .first()
            )
            key_usage = _user_key_usage_summary(session, int(u.id))
            sessions = (
                session.query(
                    func.count(UserSession.id),
                    func.max(UserSession.last_seen_at),
                )
                .filter(UserSession.user_id == u.id, UserSession.status == "active")
                .one()
            )
            key_ids = [row.id for row in session.query(UserApiKey.id).filter(UserApiKey.user_id == u.id).all()]
            device_count = (
                session.query(UserApiKeyDevice)
                .filter(UserApiKeyDevice.api_key_id.in_(key_ids), UserApiKeyDevice.status == "active")
                .count()
            ) if key_ids else 0
            sync_blob = session.query(EncryptedBackup).filter(EncryptedBackup.user_id == u.id).first()
            today = _today_ledger_usage(session, int(u.id), now)
            quota_used = int(cycle.used_count if cycle else 0)
            quota_limit = int(cycle.monthly_limit if cycle else (plan.monthly_limit if plan else 0))
            d["plan_name"] = plan.name if plan else None
            d["plan_code"] = plan.code if plan else None
            d["plan_monthly_limit"] = plan.monthly_limit if plan else None
            d["plan_rate_limit_rpm"] = plan.rate_limit_rpm if plan else None
            d["plan_rate_limit_burst"] = plan.rate_limit_burst if plan else None
            d["subscription_status"] = sub.status if sub else None
            d["subscription_expiry"] = sub.end_at.isoformat() if sub and sub.end_at else None
            d["usage_used"] = quota_used
            d["quota_used"] = quota_used
            d["quota_limit"] = quota_limit
            d["quota_remaining"] = max(0, quota_limit - quota_used)
            d["plan_usage_used"] = quota_used
            d["today_credits_used"] = int(today["credits_used"])
            d["request_usage_count"] = key_usage["total_usage_count"]
            d["active_key_id"] = active_key.id if active_key else None
            d["active_key_prefix"] = active_key.key_prefix_display if active_key else None
            d["key_usage_count"] = key_usage["total_usage_count"]
            d["active_key_usage_count"] = active_key.usage_count if active_key else 0
            d["key_last_used_at"] = key_usage["last_used_at"]
            d["active_session_count"] = int(sessions[0] or 0)
            d["active_device_count"] = int(device_count or 0)
            d["sync_backup_size_bytes"] = int(sync_blob.blob_size_bytes or 0) if sync_blob else 0
            d["sync_updated_at"] = sync_blob.updated_at.isoformat() if sync_blob and sync_blob.updated_at else None
            d["last_activity_at"] = _latest_activity_at(
                u.last_login_at,
                sessions[1],
                _parse_datetime(key_usage["last_used_at"]),
                sync_blob.updated_at if sync_blob else None,
                cycle.updated_at if cycle else None,
            )
            user_dicts.append(d)
    finally:
        session.close()

    return JSONResponse({
        "users": user_dicts,
        "total": total,
        "offset": offset,
        "limit": limit,
    })


@router.get("/api/users/{user_id}")
async def get_user(request: Request, user_id: int) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    session = get_session()
    try:
        user = session.query(User).filter(User.id == user_id).first()
        if not user:
            return JSONResponse({"error": "User not found"}, status_code=404)

        data = user.to_dict()
        subs = (
            session.query(UserSubscription)
            .filter(UserSubscription.user_id == user.id)
            .order_by(UserSubscription.created_at.desc())
            .all()
        )
        plan_ids = {s.plan_id for s in subs}
        plans = {
            p.id: p
            for p in session.query(SubscriptionPlan).filter(SubscriptionPlan.id.in_(plan_ids)).all()
        } if plan_ids else {}
        active_sub = next((s for s in subs if s.status == "active"), None)
        display_sub = active_sub or (subs[0] if subs else None)
        active_key = (
            session.query(UserApiKey)
            .filter(UserApiKey.user_id == user.id, UserApiKey.status == "active")
            .order_by(UserApiKey.issued_at.desc())
            .first()
        )
        devices = []
        if active_key:
            devices = (
                session.query(UserApiKeyDevice)
                .filter(UserApiKeyDevice.api_key_id == active_key.id)
                .order_by(UserApiKeyDevice.last_seen_at.desc())
                .all()
            )
        payments = (
            session.query(PaymentRecord)
            .filter(PaymentRecord.user_id == user.id)
            .order_by(PaymentRecord.created_at.desc())
            .limit(20)
            .all()
        )
        all_keys = (
            session.query(UserApiKey)
            .filter(UserApiKey.user_id == user.id)
            .order_by(UserApiKey.issued_at.desc())
            .all()
        )
        all_key_ids = [int(key.id) for key in all_keys]
        all_devices = (
            session.query(UserApiKeyDevice)
            .filter(UserApiKeyDevice.api_key_id.in_(all_key_ids))
            .order_by(UserApiKeyDevice.last_seen_at.desc())
            .all()
        ) if all_key_ids else []
        sessions = (
            session.query(UserSession)
            .filter(UserSession.user_id == user.id)
            .order_by(UserSession.last_seen_at.desc())
            .limit(20)
            .all()
        )
        sync_blob = (
            session.query(EncryptedBackup)
            .filter(EncryptedBackup.user_id == user.id)
            .first()
        )
        now = _utcnow()

        data["active_subscription"] = (
            _serialize_subscription(active_sub, plans.get(active_sub.plan_id)) if active_sub else None
        )
        data["display_subscription"] = (
            _serialize_subscription(display_sub, plans.get(display_sub.plan_id)) if display_sub else None
        )
        data["subscriptions"] = [_serialize_subscription(s, plans.get(s.plan_id)) for s in subs]
        usage = None
        key_usage = _user_key_usage_summary(session, int(user.id))
        if display_sub:
            cycle = (
                session.query(UsageCycle)
                .filter(UsageCycle.user_id == user.id, UsageCycle.subscription_id == display_sub.id)
                .order_by(UsageCycle.cycle_start_at.desc())
                .first()
            )
            plan = plans.get(display_sub.plan_id)
            quota_used = int(cycle.used_count if cycle else 0)
            usage = {
                "quota_used": quota_used,
                "quota_limit": cycle.monthly_limit if cycle else (plan.monthly_limit if plan else 0),
                "plan_usage_used": quota_used,
                "request_usage_count": key_usage["total_usage_count"],
                "cycle_start": cycle.cycle_start_at.isoformat() if cycle and cycle.cycle_start_at else None,
                "cycle_end": cycle.cycle_end_at.isoformat() if cycle and cycle.cycle_end_at else None,
            }

        data["active_key"] = _serialize_active_key(active_key)
        data["key_usage"] = key_usage
        data["usage"] = usage or {
            "quota_used": 0,
            "quota_limit": 0,
            "plan_usage_used": 0,
            "request_usage_count": key_usage["total_usage_count"],
            "cycle_start": None,
            "cycle_end": None,
        }
        data["usage"]["remaining"] = max(0, int(data["usage"].get("quota_limit") or 0) - int(data["usage"].get("quota_used") or 0))
        data["usage"]["today"] = _today_ledger_usage(session, int(user.id), now)
        data["rate_limit"] = {
            "requests_per_minute": plans.get(display_sub.plan_id).rate_limit_rpm if display_sub and plans.get(display_sub.plan_id) else None,
            "burst": plans.get(display_sub.plan_id).rate_limit_burst if display_sub and plans.get(display_sub.plan_id) else None,
        }
        data["devices"] = [
            {
                "id": d.id,
                "device_fingerprint": (d.device_fingerprint[:20] + "...") if d.device_fingerprint else "",
                "device_name": d.device_name,
                "user_agent": d.user_agent[:80] if d.user_agent else "",
                "status": d.status,
                "first_seen": d.first_seen_at.isoformat() if d.first_seen_at else None,
                "last_seen": d.last_seen_at.isoformat() if d.last_seen_at else None,
            }
            for d in devices
        ]
        data["all_devices"] = [
            {
                "id": d.id,
                "api_key_id": d.api_key_id,
                "device_fingerprint": (d.device_fingerprint[:20] + "...") if d.device_fingerprint else "",
                "device_name": d.device_name,
                "user_agent": d.user_agent[:120] if d.user_agent else "",
                "status": d.status,
                "first_seen": d.first_seen_at.isoformat() if d.first_seen_at else None,
                "last_seen": d.last_seen_at.isoformat() if d.last_seen_at else None,
            }
            for d in all_devices
        ]
        data["sessions"] = [
            {
                "id": item.id,
                "api_key_id": item.api_key_id,
                "device_id": (item.device_id[:20] + "...") if item.device_id else "",
                "device_name": item.device_name,
                "user_agent": item.user_agent[:120] if item.user_agent else "",
                "ip_address": item.ip_address,
                "status": item.status,
                "issued_at": item.issued_at.isoformat() if item.issued_at else None,
                "expires_at": item.expires_at.isoformat() if item.expires_at else None,
                "last_seen": item.last_seen_at.isoformat() if item.last_seen_at else None,
            }
            for item in sessions
        ]
        data["sync_backup"] = {
            "found": bool(sync_blob),
            "sync_version": int(sync_blob.sync_version or 0) if sync_blob else 0,
            "blob_size_bytes": int(sync_blob.blob_size_bytes or 0) if sync_blob else 0,
            "blob_hash": sync_blob.blob_hash if sync_blob else None,
            "device_id": sync_blob.device_id if sync_blob else None,
            "created_at": sync_blob.created_at.isoformat() if sync_blob and sync_blob.created_at else None,
            "updated_at": sync_blob.updated_at.isoformat() if sync_blob and sync_blob.updated_at else None,
        }
        data["plan_limits"] = {
            "monthly_limit": plans.get(display_sub.plan_id).monthly_limit if display_sub and plans.get(display_sub.plan_id) else None,
            "duration_days": plans.get(display_sub.plan_id).duration_days if display_sub and plans.get(display_sub.plan_id) else None,
            "max_devices": plans.get(display_sub.plan_id).max_devices if display_sub and plans.get(display_sub.plan_id) else None,
            "allowed_services": plans.get(display_sub.plan_id).allowed_services if display_sub and plans.get(display_sub.plan_id) else {},
        }
        data["payments"] = [p.to_dict() for p in payments]
        return JSONResponse(data)
    finally:
        session.close()


@router.post("/api/users")
async def create_user(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    body = await request.json()
    container = request.app.state.container
    session = get_session()
    try:
        now = _utcnow()
        plan_id = body.get("plan_id")
        user = User(
            full_name=body.get("full_name", ""),
            email=(body.get("email") or "").strip().lower() or None,
            mobile_number=body.get("mobile_number") or None,
            status=body.get("status") or ("active" if plan_id else "pending_payment"),
            notes=body.get("notes", ""),
        )
        session.add(user)
        session.flush()
        plan = None
        sub = None
        if plan_id:
            plan = session.query(SubscriptionPlan).filter(SubscriptionPlan.id == int(plan_id)).first()
            if not plan:
                session.rollback()
                return JSONResponse({"error": "Plan not found"}, status_code=404)
            custom_end = _parse_datetime(body.get("subscription_end"))
            custom_start = _parse_datetime(body.get("subscription_start"))
            duration_days = body.get("duration_days")
            if duration_days and not custom_end:
                custom_end = (custom_start or now) + timedelta(days=int(duration_days))
            sub = _create_active_subscription(
                session,
                user,
                plan,
                now,
                start_at=custom_start,
                end_at=custom_end,
                expire_existing=False,
            )
        session.commit()
        session.refresh(user)

        key_payload = None
        if body.get("issue_api_key", bool(plan_id)):
            key, plain = request.app.state.user_key_service.create_key(user_id=int(user.id))
            key_payload = {
                "key_id": key.id,
                "api_key": plain,
                "key_prefix": key.key_prefix_display,
                "expires_at": key.expires_at.isoformat() if key.expires_at else None,
            }

        container.audit_service.log(
            actor_type="admin", action="user_created",
            target_type="user", target_id=user.id,
        )
        result = user.to_dict()
        result["active_subscription"] = _serialize_subscription(sub, plan) if sub and plan else None
        result["created_key"] = key_payload
        return JSONResponse(result, status_code=201)
    except Exception as e:
        session.rollback()
        return JSONResponse({"error": str(e)}, status_code=400)
    finally:
        session.close()


@router.put("/api/users/{user_id}")
async def update_user(request: Request, user_id: int) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    body = await request.json()
    session = get_session()
    try:
        user = session.query(User).filter(User.id == user_id).first()
        if not user:
            return JSONResponse({"error": "User not found"}, status_code=404)
        for key in ("full_name", "email", "mobile_number", "notes", "status"):
            if key in body:
                value = body.get(key)
                if key in {"email", "mobile_number"}:
                    setattr(user, key, (str(value).strip().lower() if key == "email" else value) or None)
                else:
                    setattr(user, key, value)
        user.updated_at = _utcnow()
        session.commit()
        session.refresh(user)
    except Exception as e:
        session.rollback()
        return JSONResponse({"error": str(e)}, status_code=400)
    finally:
        session.close()
    container.audit_service.log(
        actor_type="admin", action="user_updated",
        target_type="user", target_id=user.id,
    )
    return JSONResponse(user.to_dict())


@router.post("/api/users/{user_id}/subscription/change-plan")
async def change_user_plan(request: Request, user_id: int) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    body = await request.json()
    plan_id = body.get("plan_id")
    if not plan_id:
        return JSONResponse({"error": "plan_id is required"}, status_code=400)

    session = get_session()
    try:
        now = _utcnow()
        user = session.query(User).filter(User.id == user_id).first()
        if not user:
            return JSONResponse({"error": "User not found"}, status_code=404)
        plan = session.query(SubscriptionPlan).filter(SubscriptionPlan.id == int(plan_id)).first()
        if not plan:
            return JSONResponse({"error": "Plan not found"}, status_code=404)
        custom_end = _parse_datetime(body.get("subscription_end"))
        duration_days = body.get("duration_days")
        if duration_days and not custom_end:
            custom_end = now + timedelta(days=int(duration_days))
        sub = _create_active_subscription(session, user, plan, now, end_at=custom_end)
        session.commit()

        container.audit_service.log(
            actor_type="admin", action="subscription_plan_changed",
            target_type="user", target_id=user_id,
        )
        return JSONResponse(_serialize_subscription(sub, plan), status_code=201)
    except Exception as e:
        session.rollback()
        return JSONResponse({"error": str(e)}, status_code=400)
    finally:
        session.close()


@router.post("/api/users/{user_id}/subscription/renew")
async def renew_user_subscription(request: Request, user_id: int) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    body = await request.json()
    session = get_session()
    try:
        now = _utcnow()
        user = session.query(User).filter(User.id == user_id).first()
        if not user:
            return JSONResponse({"error": "User not found"}, status_code=404)
        current = (
            session.query(UserSubscription)
            .filter(UserSubscription.user_id == user_id, UserSubscription.status == "active")
            .order_by(UserSubscription.created_at.desc())
            .first()
        )
        plan_id = body.get("plan_id") or (current.plan_id if current else None)
        if not plan_id:
            return JSONResponse({"error": "plan_id is required when user has no active subscription"}, status_code=400)
        plan = session.query(SubscriptionPlan).filter(SubscriptionPlan.id == int(plan_id)).first()
        if not plan:
            return JSONResponse({"error": "Plan not found"}, status_code=404)

        duration_days = int(body.get("duration_days") or plan.duration_days or 30)
        if current and int(current.plan_id) == int(plan.id):
            base = current.end_at or now
            if base.tzinfo is None:
                base = base.replace(tzinfo=timezone.utc)
            if base < now:
                base = now
            current.end_at = base + timedelta(days=duration_days)
            current.monthly_limit_snapshot = int(plan.monthly_limit or current.monthly_limit_snapshot or 0)
            current.status = "active"
            current.updated_at = now
            user.status = "active"
            user.updated_at = now
            _ensure_usage_cycle(session, int(user.id), int(current.id), plan, now)
            sub = current
        else:
            sub = _create_active_subscription(session, user, plan, now)
        session.commit()

        created_key_payload = None
        active_key = request.app.state.user_key_service.get_user_key(user_id)
        if not active_key and body.get("issue_api_key", True):
            key, plain = request.app.state.user_key_service.create_key(user_id=user_id)
            created_key_payload = {
                "key_id": key.id,
                "api_key": plain,
                "key_prefix": key.key_prefix_display,
                "expires_at": key.expires_at.isoformat() if key.expires_at else None,
            }

        container.audit_service.log(
            actor_type="admin", action="subscription_renewed",
            target_type="user", target_id=user_id,
        )
        payload = _serialize_subscription(sub, plan)
        payload["created_key"] = created_key_payload
        return JSONResponse(payload)
    except Exception as e:
        session.rollback()
        return JSONResponse({"error": str(e)}, status_code=400)
    finally:
        session.close()


@router.post("/api/users/{user_id}/subscription/expire")
async def expire_user_subscription(request: Request, user_id: int) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    session = get_session()
    try:
        now = _utcnow()
        user = session.query(User).filter(User.id == user_id).first()
        if not user:
            return JSONResponse({"error": "User not found"}, status_code=404)
        count = session.query(UserSubscription).filter(
            UserSubscription.user_id == user_id,
            UserSubscription.status == "active",
        ).update({"status": "expired", "updated_at": now})
        user.status = "expired"
        user.updated_at = now
        session.commit()
        container.audit_service.log(
            actor_type="admin", action="subscription_expired",
            target_type="user", target_id=user_id,
        )
        return JSONResponse({"ok": True, "expired_count": count})
    except Exception as e:
        session.rollback()
        return JSONResponse({"error": str(e)}, status_code=400)
    finally:
        session.close()


@router.post("/api/users/{user_id}/status")
async def set_user_status(request: Request, user_id: int) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    body = await request.json()
    new_status = body.get("status", "")
    valid_statuses = ["active", "blocked", "inactive", "expired", "deleted", "pending_payment", "pending_approval"]
    if new_status not in valid_statuses:
        return JSONResponse({"error": f"Invalid status. Must be one of: {valid_statuses}"}, status_code=400)

    user = container.user_service.set_user_status(user_id, new_status)
    if not user:
        return JSONResponse({"error": "User not found"}, status_code=404)
    container.audit_service.log(
        actor_type="admin", action=f"user_{new_status}",
        target_type="user", target_id=user.id,
    )
    return JSONResponse(user.to_dict())


@router.delete("/api/users/{user_id}")
async def delete_user(request: Request, user_id: int) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    ok = container.user_service.delete_user(user_id)
    if not ok:
        return JSONResponse({"error": "User not found"}, status_code=404)
    container.audit_service.log(
        actor_type="admin", action="user_deleted",
        target_type="user", target_id=user_id,
    )
    return JSONResponse({"ok": True})
