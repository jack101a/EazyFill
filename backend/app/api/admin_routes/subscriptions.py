"""Admin API — Subscription plans and user subscription management."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .utils import _admin_guard

router = APIRouter(tags=["admin-subscriptions"])


# ── Plans ─────────────────────────────────────────────────────────────────

@router.get("/api/plans")
async def list_plans(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    plans = container.subscription_service.list_plans(active_only=False)
    rows = []
    for p in plans:
        d = p.to_dict()
        rows.append(d)
    return JSONResponse({"plans": rows})


@router.post("/api/plans")
async def create_plan(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    body = await request.json()
    try:
        plan = container.subscription_service.create_plan(
            code=body.get("code"),
            name=body["name"],
            monthly_limit=body.get("monthly_limit", 1000),
            duration_days=body.get("duration_days", 30),
            price_amount=body.get("price_amount", 0),
            currency=body.get("currency", "INR"),
            description=body.get("description", ""),
            max_devices=body.get("max_devices", 1),
            allowed_services=body.get("allowed_services", {}),
            rate_limit_rpm=body.get("rate_limit_rpm", 60),
            rate_limit_burst=body.get("rate_limit_burst", 10),
            show_in_checkout=body.get("show_in_checkout", True),
            is_promo=body.get("is_promo", False),
            promo_audience=body.get("promo_audience", "both"),
        )
        container.audit_service.log(
            actor_type="admin", action="plan_created",
            target_type="plan", target_id=plan.id,
        )
        return JSONResponse(plan.to_dict(), status_code=201)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.put("/api/plans/{plan_id}")
async def update_plan(request: Request, plan_id: int) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    try:
        body = await request.json()
        if not isinstance(body, dict):
            return JSONResponse({"error": "Invalid payload"}, status_code=400)
        plan = container.subscription_service.update_plan(plan_id, **body)
        if not plan:
            return JSONResponse({"error": "Plan not found"}, status_code=404)
        return JSONResponse(plan.to_dict())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.delete("/api/plans/{plan_id}")
async def delete_plan(request: Request, plan_id: int) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    body = {}
    try:
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
    except Exception:
        body = {}
    target_plan_id = body.get("target_plan_id")
    try:
        result = container.subscription_service.delete_plan(
            plan_id,
            target_plan_id=int(target_plan_id) if target_plan_id is not None else None,
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    if not result:
        return JSONResponse({"error": "Plan not found"}, status_code=404)
    container.audit_service.log(
        actor_type="admin", action="plan_deleted",
        target_type="plan", target_id=plan_id,
        after_json=json.dumps({
            "target_plan_id": result.get("target_plan_id"),
            "migrated_count": result.get("migrated_count", 0),
            "payment_refs_updated": result.get("payment_refs_updated", 0),
            "deleted_subscription_count": result.get("deleted_subscription_count", 0),
        }),
    )
    return JSONResponse({
        "ok": True,
        "plan_id": result.get("plan_id", plan_id),
        "migrated_count": result.get("migrated_count", 0),
        "target_plan_id": result.get("target_plan_id"),
        "payment_refs_updated": result.get("payment_refs_updated", 0),
        "deleted_subscription_count": result.get("deleted_subscription_count", 0),
    })


# ── User Subscriptions ────────────────────────────────────────────────────

@router.post("/api/users/{user_id}/subscribe")
async def create_subscription(request: Request, user_id: int) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    body = await request.json()
    plan_id = body.get("plan_id")
    if not plan_id:
        return JSONResponse({"error": "plan_id is required"}, status_code=400)

    try:
        sub = container.subscription_service.create_subscription(
            user_id=user_id,
            plan_id=int(plan_id),
        )
        container.audit_service.log(
            actor_type="admin", action="subscription_activated",
            target_type="subscription", target_id=sub.id,
        )
        return JSONResponse(sub.to_dict(), status_code=201)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.get("/api/users/{user_id}/subscriptions")
async def get_user_subscriptions(request: Request, user_id: int) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    subs = container.subscription_service.get_user_subscriptions(user_id)
    return JSONResponse({"subscriptions": [s.to_dict() for s in subs]})


@router.post("/api/subscriptions/{subscription_id}/cancel")
async def cancel_subscription(request: Request, subscription_id: int) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    sub = container.subscription_service.cancel_subscription(subscription_id)
    if not sub:
        return JSONResponse({"error": "Subscription not found"}, status_code=404)
    container.audit_service.log(
        actor_type="admin", action="subscription_cancelled",
        target_type="subscription", target_id=subscription_id,
    )
    return JSONResponse(sub.to_dict())
