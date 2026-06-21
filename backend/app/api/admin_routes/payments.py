"""Admin API - payment approval workflow."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from .utils import _admin_guard

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin-payments"])


@router.get("/api/payments")
async def list_payments(
    request: Request,
    status: str | None = Query(None),
    user_id: int | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    payments, total = container.payment_service.list_payments(
        status=status, user_id=user_id, offset=offset, limit=limit
    )
    return JSONResponse({
        "payments": [payment.to_dict() for payment in payments],
        "total": total,
        "offset": offset,
        "limit": limit,
    })


@router.get("/api/payments/pending-count")
async def pending_payment_count(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    return JSONResponse({"pending_count": container.payment_service.get_pending_count()})


@router.post("/api/payments/{payment_id}/approve")
async def approve_payment(request: Request, payment_id: int) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    try:
        body = await request.json()
    except Exception:
        body = {}
    reason = str(body.get("manual_override_reason") or "").strip()
    confirmed = bool(body.get("confirm_manual_override"))
    if not confirmed:
        return JSONResponse(
            {"error": "Manual approval confirmation is required"},
            status_code=422,
        )
    if len(reason) < 8:
        return JSONResponse(
            {"error": "Manual approval reason must be at least 8 characters"},
            status_code=422,
        )

    try:
        result = container.payment_service.activate_payment(payment_id, triggered_by="admin")
        if not result:
            return JSONResponse({"error": "Payment not found"}, status_code=404)
        note = f"Manual admin approval override: {reason}"
        append_note = getattr(container.payment_service, "append_payment_note", None)
        if append_note:
            updated_payment = append_note(payment_id, note)
            if updated_payment:
                result["payment"] = updated_payment.to_dict()
            else:
                result["payment"]["payment_note"] = note
        else:
            result["payment"]["payment_note"] = note
    except Exception as exc:
        logger.error("payment_approve_auto_activate_failed", extra={"context": {"error": str(exc)}})
        return JSONResponse({"error": "Failed to process approval"}, status_code=500)

    container.audit_service.log(
        actor_type="admin",
        action="payment_approved",
        target_type="payment",
        target_id=payment_id,
        after_json=json.dumps({"manual_override": True, "reason": reason}),
    )
    return JSONResponse(result["payment"])


@router.post("/api/payments/{payment_id}/reject")
async def reject_payment(request: Request, payment_id: int) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    body = await request.json()
    reason = body.get("rejection_reason", "")

    payment = container.payment_service.reject_payment(payment_id, rejection_reason=reason)
    if not payment:
        return JSONResponse({"error": "Payment not found"}, status_code=404)

    container.audit_service.log(
        actor_type="admin",
        action="payment_rejected",
        target_type="payment",
        target_id=payment_id,
        after_json=json.dumps({"reason": reason}),
    )
    return JSONResponse(payment.to_dict())


@router.post("/api/payments/razorpay/order")
async def create_admin_razorpay_order(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied

    try:
        body = await request.json()
        user_id = int(body.get("user_id"))
        plan_id = int(body.get("plan_id"))
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "error": "user_id and plan_id are required"}, status_code=400)

    from app.api.webhooks import create_razorpay_order_for_user

    response = await create_razorpay_order_for_user(request, user_id=user_id, plan_id=plan_id)
    if response.status_code < 400:
        request.app.state.container.audit_service.log(
            actor_type="admin",
            action="razorpay_order_created",
            target_type="user",
            target_id=user_id,
            after_json=json.dumps({"plan_id": plan_id}),
        )
    return response
