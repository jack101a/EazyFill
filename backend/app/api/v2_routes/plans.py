"""EazyFill v2 plan catalog endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(prefix="/plans", tags=["v2-plans"])


def entitlement_enabled(entitlements: dict[str, Any], key: str, *, fallback_key: str | None = None) -> bool:
    if key in entitlements:
        return bool(entitlements.get(key))
    if fallback_key and fallback_key in entitlements:
        return bool(entitlements.get(fallback_key))
    return False


def plan_to_payload(plan: Any, credit_service: Any | None = None) -> dict[str, Any]:
    entitlements = plan.allowed_services or {}
    rules_limit = entitlements.get("rules_limit")
    scripts_limit = entitlements.get("scripts_limit")
    script_storage_mb = entitlements.get("script_storage_mb")
    portable_pack = entitlement_enabled(entitlements, "portable_pack", fallback_key="sync")
    local_backup_export = bool(entitlements.get("local_backup_export")) if "local_backup_export" in entitlements else portable_pack
    local_backup_import = bool(entitlements.get("local_backup_import")) if "local_backup_import" in entitlements else portable_pack
    metering = credit_service.get_policies(plan=plan) if credit_service is not None else {}
    return {
        "id": plan.id,
        "code": plan.code,
        "name": plan.name,
        "description": plan.description or "",
        "price": {
            "amount": int(plan.price_amount or 0),
            "currency": plan.currency or "INR",
        },
        "duration_days": int(plan.duration_days or 30),
        "limits": {
            "captcha_daily_limit": int(plan.monthly_limit or 0),
            "rules": rules_limit,
            "scripts": scripts_limit,
            "script_storage_bytes": int(script_storage_mb) * 1024 * 1024 if script_storage_mb else None,
            "max_devices": int(plan.max_devices or 1),
        },
        "features": {
            "captcha": entitlements.get("captcha", True),
            "autofill": entitlements.get("autofill", True),
            "userscripts": entitlements.get("userscripts", True),
            "cloud_sync": bool(entitlements.get("sync", False)),
            "portable_pack": portable_pack,
            "local_backup_export": local_backup_export,
            "local_backup_import": local_backup_import,
            "unlimited_rules": bool(entitlements.get("unlimited_rules", False)),
            "js_rules": bool(entitlements.get("js_rules", False)),
            "priority_solving": bool(entitlements.get("priority_solving", False)),
        },
        "metering": metering,
        "rate_limit": {
            "rpm": int(plan.rate_limit_rpm or 0),
            "burst": int(plan.rate_limit_burst or 0),
        },
    }


def payment_providers_payload(request: Request) -> list[dict[str, Any]]:
    payment_cfg = getattr(request.app.state.container.settings, "payment", None)
    razorpay_key_id = str(getattr(payment_cfg, "razorpay_key_id", "") or "").strip()
    razorpay_key_secret = str(getattr(payment_cfg, "razorpay_key_secret", "") or "").strip()
    return [
        {
            "code": "razorpay",
            "name": "Razorpay",
            "available": bool(razorpay_key_id and razorpay_key_secret),
            "requires_checkout": True,
            "key_id": razorpay_key_id if razorpay_key_id else None,
        },
    ]


@router.get("")
async def list_plans(request: Request) -> dict:
    plans = request.app.state.container.subscription_service.list_plans(active_only=True)
    plans = [plan for plan in plans if getattr(plan, "show_in_checkout", True)]
    credit_service = getattr(request.app.state.container, "credit_service", None)
    return {
        "plans": [plan_to_payload(plan, credit_service=credit_service) for plan in plans],
        "payment_providers": payment_providers_payload(request),
    }
