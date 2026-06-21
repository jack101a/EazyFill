"""EazyFill v2 billing endpoints."""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.v2_routes.deps import V2AuthContext, validate_v2_key
from app.api.webhooks import create_razorpay_order_for_user

router = APIRouter(prefix="/billing", tags=["v2-billing"])


class CreateOrderRequest(BaseModel):
    plan_id: int | None = None
    plan_code: str | None = None
    provider: str = Field(default="razorpay")


class VerifyPaymentRequest(BaseModel):
    payment_id: int
    provider: str = Field(default="razorpay")
    provider_order_id: str | None = None
    provider_payment_id: str | None = None
    provider_signature: str | None = None


def _require_user(ctx: V2AuthContext) -> int:
    if not ctx.user_id:
        raise HTTPException(status_code=403, detail={"error": "user_account_required"})
    return int(ctx.user_id)


def _payment_payload(payment: Any) -> dict[str, Any]:
    return payment.to_dict() if hasattr(payment, "to_dict") else dict(payment)


def _plan_by_payload(request: Request, payload: CreateOrderRequest) -> Any:
    service = request.app.state.container.subscription_service
    if payload.plan_id is not None:
        plan = service.get_plan(int(payload.plan_id))
    elif payload.plan_code:
        plan = service.get_plan_by_code(str(payload.plan_code).strip())
    else:
        raise HTTPException(status_code=400, detail={"error": "plan_required"})
    if not plan or not getattr(plan, "is_active", True):
        raise HTTPException(status_code=404, detail={"error": "plan_not_found"})
    return plan


def _razorpay_secret(request: Request) -> str:
    payment_cfg = getattr(request.app.state.container.settings, "payment", None)
    return os.getenv("RAZORPAY_KEY_SECRET", getattr(payment_cfg, "razorpay_key_secret", "")).strip()


def _valid_razorpay_payment_signature(order_id: str, payment_id: str, signature: str, secret: str) -> bool:
    if not order_id or not payment_id or not signature or not secret:
        return False
    message = f"{order_id}|{payment_id}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


@router.post("/create-order")
async def create_order(
    request: Request,
    payload: CreateOrderRequest,
    ctx: V2AuthContext = Depends(validate_v2_key),
) -> dict:
    user_id = _require_user(ctx)
    provider = str(payload.provider or "razorpay").strip().lower()
    if provider != "razorpay":
        raise HTTPException(status_code=400, detail={"error": "unsupported_payment_provider"})

    plan = _plan_by_payload(request, payload)
    return await create_razorpay_order_for_user(request, user_id=user_id, plan_id=int(plan.id))


@router.post("/verify-payment")
async def verify_payment(
    request: Request,
    payload: VerifyPaymentRequest,
    ctx: V2AuthContext = Depends(validate_v2_key),
) -> dict:
    user_id = _require_user(ctx)
    payment = request.app.state.container.payment_service.get_payment(int(payload.payment_id))
    if not payment or int(payment.user_id) != user_id:
        raise HTTPException(status_code=404, detail={"error": "payment_not_found"})
    provider = str(payload.provider or getattr(payment, "payment_provider", "") or "razorpay").strip().lower()
    if provider == "razorpay":
        order_id = str(payload.provider_order_id or getattr(payment, "provider_order_id", "") or "").strip()
        provider_payment_id = str(payload.provider_payment_id or "").strip()
        signature = str(payload.provider_signature or "").strip()
        if not _valid_razorpay_payment_signature(order_id, provider_payment_id, signature, _razorpay_secret(request)):
            raise HTTPException(status_code=400, detail={"error": "invalid_payment_signature"})
        request.app.state.container.payment_service.record_provider_payment(
            int(payment.id),
            provider="razorpay",
            provider_order_id=order_id,
            provider_payment_id=provider_payment_id,
            provider_signature=signature,
            provider_status="captured",
        )
        result = request.app.state.container.payment_service.activate_payment(
            int(payment.id),
            triggered_by="razorpay_verify",
        )
        return {
            "ok": True,
            "status": "approved",
            "payment": result["payment"] if result else _payment_payload(payment),
            "plan": result.get("plan") if result else None,
            "api_key": result.get("plain_key") if result else None,
        }
    raise HTTPException(status_code=400, detail={"error": "unsupported_payment_provider"})


@router.get("/history")
async def history(
    request: Request,
    ctx: V2AuthContext = Depends(validate_v2_key),
) -> dict:
    user_id = _require_user(ctx)
    payments = request.app.state.container.payment_service.get_user_payments(user_id)
    return {"items": [_payment_payload(payment) for payment in payments], "next_cursor": None}


@router.post("/cancel")
async def cancel(
    request: Request,
    ctx: V2AuthContext = Depends(validate_v2_key),
) -> dict:
    user_id = _require_user(ctx)
    subscription = request.app.state.container.subscription_service.get_active_subscription(user_id)
    if not subscription:
        return {"ok": True, "cancelled": False, "reason": "no_active_subscription"}
    cancelled = request.app.state.container.subscription_service.cancel_subscription(int(subscription.id))
    return {"ok": True, "cancelled": bool(cancelled), "subscription": cancelled.to_dict() if cancelled else None}
