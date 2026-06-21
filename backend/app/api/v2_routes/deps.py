"""Shared dependencies for EazyFill v2 routes."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import Header, HTTPException, Request

from app.core.db import get_session
from app.core.models import SubscriptionPlan, User, UserSubscription


@dataclass
class V2AuthContext:
    api_key: str
    device_id: str
    record: dict[str, Any]
    key_kind: str
    user: User | None = None
    subscription: UserSubscription | None = None
    plan: SubscriptionPlan | None = None

    @property
    def user_id(self) -> int | None:
        raw = self.record.get("user_id")
        return int(raw) if raw else None

    @property
    def key_id(self) -> int:
        return int(self.record.get("id") or 0)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ensure_user_sync_secret(user: User | None) -> str:
    if user is None:
        return ""
    current = str(getattr(user, "sync_secret", "") or "").strip()
    if current:
        return current
    user.sync_secret = secrets.token_urlsafe(32)
    return str(user.sync_secret)


def _device_id(request: Request, explicit: str | None = None) -> str:
    value = (
        (explicit or "").strip()
        or request.headers.get("x-eazyfill-device-id", "").strip()
        or request.headers.get("x-flowpilot-device-id", "").strip()
        or request.headers.get("x-device-id", "").strip()
        or request.headers.get("x-client-device-id", "").strip()
    )
    if value:
        return value
    ua = request.headers.get("user-agent", "").strip()
    return f"ua:{ua[:180]}" if ua else "ua:unknown"


def _load_user_context(record: dict[str, Any], api_key: str, device_id: str) -> V2AuthContext:
    user_id = int(record.get("user_id") or 0)
    session = get_session()
    try:
        user = session.query(User).filter(User.id == user_id).first()
        ensure_user_sync_secret(user)
        sub = (
            session.query(UserSubscription)
            .filter(UserSubscription.user_id == user_id, UserSubscription.status == "active")
            .order_by(UserSubscription.created_at.desc())
            .first()
        )
        plan = session.query(SubscriptionPlan).filter(SubscriptionPlan.id == sub.plan_id).first() if sub else None
        session.flush()
        session.expunge_all()
        session.commit()
        return V2AuthContext(
            api_key=api_key,
            device_id=device_id,
            record=record,
            key_kind="user",
            user=user,
            subscription=sub,
            plan=plan,
        )
    finally:
        session.close()


def _auth_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"error": code, "message": message})


async def validate_v2_key(
    request: Request,
    x_api_key: str = Header(default="", alias="X-Api-Key"),
    x_eazyfill_device_id: str = Header(default="", alias="X-EazyFill-Device-Id"),
    x_flowpilot_device_id: str = Header(default="", alias="X-FlowPilot-Device-Id"),
) -> V2AuthContext:
    api_key = str(x_api_key or "").strip()
    if not api_key:
        raise _auth_error(401, "invalid_key", "Sign in is required")

    device_id = _device_id(request, x_eazyfill_device_id or x_flowpilot_device_id)
    container = request.app.state.container

    user_key_service = getattr(container, "user_key_service", None)
    if user_key_service is not None:
        record = user_key_service.validate_key(api_key)
        if record:
            auth_error = record.get("auth_error")
            if auth_error:
                raise _auth_error(403, str(auth_error), "Account access is not allowed")
            if not user_key_service.validate_device(int(record["id"]), device_id):
                bound = user_key_service.bind_device(
                    int(record["id"]),
                    device_id,
                    user_agent=request.headers.get("user-agent", ""),
                )
                if bound is None:
                    raise _auth_error(401, "device_mismatch", "This browser is not authorized for the account")
            return _load_user_context(record, api_key, device_id)

    legacy_record = container.key_service.validate_key(api_key)
    if not legacy_record:
        raise _auth_error(401, "invalid_key", "Sign in again to continue")
    if not container.key_service.validate_or_bind_device(
        int(legacy_record["id"]),
        device_id,
        user_agent=request.headers.get("user-agent", ""),
    ):
        raise _auth_error(401, "device_mismatch", "This browser is not authorized for the account")
    return V2AuthContext(
        api_key=api_key,
        device_id=device_id,
        record=legacy_record,
        key_kind="legacy",
    )


def plan_payload(ctx: V2AuthContext) -> dict[str, Any]:
    plan = ctx.plan
    entitlements = {}
    if plan:
        entitlements = plan.allowed_services or {}
    portable_pack = bool(
        entitlements.get("portable_pack")
        if "portable_pack" in entitlements
        else entitlements.get("sync", False)
    )
    return {
        "code": plan.code if plan else "legacy",
        "name": plan.name if plan else "Legacy Plan",
        "captcha_daily_limit": int(plan.monthly_limit if plan else 3000),
        "features": {
            "cloud_sync": bool(entitlements.get("sync", False)),
            "portable_pack": portable_pack,
            "local_backup_export": bool(entitlements.get("local_backup_export", portable_pack)),
            "local_backup_import": bool(entitlements.get("local_backup_import", portable_pack)),
            "unlimited_rules": bool(entitlements.get("unlimited_rules", False)),
            "js_rules": bool(entitlements.get("js_rules", False)),
            "priority_solving": bool(entitlements.get("priority_solving", False)),
            "captcha": entitlements.get("captcha", True),
            "autofill": entitlements.get("autofill", True),
            "userscripts": entitlements.get("userscripts", True),
        },
    }


def credits_payload(ctx: V2AuthContext, request: Request) -> dict[str, Any]:
    cloud_sync_enabled = bool(ctx.plan and (ctx.plan.allowed_services or {}).get("sync", False))
    credit_service = getattr(request.app.state.container, "credit_service", None)
    if credit_service is not None:
        return credit_service.get_balance(
            ctx.user_id,
            plan=ctx.plan,
            cloud_sync_enabled=cloud_sync_enabled,
        )

    if ctx.user_id:
        usage = request.app.state.container.usage_cycle_service.get_user_usage(ctx.user_id)
    else:
        usage = {"used": 0, "limit": 3000, "remaining": 3000, "cycle_end": None}
    used = int(usage.get("used") or 0)
    limit = int(usage.get("limit") or 0)
    remaining = max(0, int(usage.get("remaining") if usage.get("remaining") is not None else limit - used))
    return {
        "captcha": {
            "used_today": used,
            "daily_limit": limit,
            "remaining": remaining,
            "resets_at": usage.get("cycle_end"),
        },
        "autofill": {
            "rules_count": 0,
            "rules_limit": None,
            "executions_today": 0,
            "executions_limit": None,
        },
        "scripts": {
            "count": 0,
            "limit": None,
            "storage_used_bytes": 0,
            "storage_limit_bytes": None,
        },
        "sync": {
            "enabled": cloud_sync_enabled,
            "last_sync_at": None,
            "backup_size_bytes": 0,
        },
    }


def key_info_payload(ctx: V2AuthContext) -> dict[str, Any]:
    return {
        "key_id": ctx.key_id,
        "key_name": str(ctx.record.get("name") or "EazyFill Key"),
        "expires_at": ctx.record.get("expires_at"),
        "key_kind": ctx.key_kind,
    }


def user_payload(ctx: V2AuthContext) -> dict[str, Any]:
    if not ctx.user:
        return {"id": None, "name": "", "email": "", "mobile": ""}
    return {
        "id": getattr(ctx.user, "id", None),
        "name": getattr(ctx.user, "full_name", "") or "",
        "email": getattr(ctx.user, "email", "") or "",
        "mobile": getattr(ctx.user, "mobile_number", "") or "",
    }
