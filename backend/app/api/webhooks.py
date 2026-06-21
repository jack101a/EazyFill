"""Public payment webhooks."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.core.db import get_session
from app.core.models import PaymentRecord, PaymentWebhookEvent, SubscriptionPlan, User
from app.services.promo_plan_policy import check_promo_plan_eligibility

logger = logging.getLogger(__name__)

router = APIRouter(tags=["payment-webhooks"])


def _razorpay_credentials(request: Request) -> tuple[str, str]:
    container = request.app.state.container
    payment_cfg = container.settings.payment
    key_id = os.getenv("RAZORPAY_KEY_ID", getattr(payment_cfg, "razorpay_key_id", "")).strip()
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", getattr(payment_cfg, "razorpay_key_secret", "")).strip()
    return key_id, key_secret


def _webhook_secret(request: Request) -> str:
    container = request.app.state.container
    settings_secret = getattr(container.settings.payment, "razorpay_webhook_secret", "")
    return os.getenv("RAZORPAY_WEBHOOK_SECRET", settings_secret).strip()


def _order_token(request: Request) -> str:
    container = request.app.state.container
    settings_token = getattr(container.settings.payment, "razorpay_order_token", "")
    return os.getenv("RAZORPAY_ORDER_TOKEN", settings_token).strip()


def _valid_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, str(signature or "").strip())


def _payment_entity(payload: dict[str, Any]) -> dict[str, Any]:
    entity = (
        payload.get("payload", {})
        .get("payment", {})
        .get("entity", {})
    )
    return entity if isinstance(entity, dict) else {}


def _order_entity(payload: dict[str, Any]) -> dict[str, Any]:
    entity = (
        payload.get("payload", {})
        .get("order", {})
        .get("entity", {})
    )
    return entity if isinstance(entity, dict) else {}


def _notes_from(*entities: dict[str, Any]) -> dict[str, Any]:
    for entity in entities:
        notes = entity.get("notes") if entity else None
        if isinstance(notes, dict):
            return notes
    return {}


async def _claim_redis_dedup(request: Request, event_id: str) -> tuple[object | None, str, bool]:
    container = request.app.state.container
    redis_cfg = getattr(container.settings, "redis", None)
    if not redis_cfg or not redis_cfg.enabled:
        return None, "", True
    try:
        import redis.asyncio as redis

        client = redis.from_url(str(redis_cfg.url), decode_responses=True)
        key = f"{redis_cfg.prefix}dedup:razorpay:{event_id}"
        claimed = await client.set(key, "1", ex=300, nx=True)
        return client, key, bool(claimed)
    except Exception as exc:
        logger.warning("razorpay_redis_dedup_failed", extra={"context": {"error": str(exc)}})
        return None, "", True


async def _release_redis_dedup(client, key: str) -> None:
    if not client:
        return
    try:
        if key:
            await client.delete(key)
    finally:
        try:
            await client.aclose()
        except Exception:
            pass


def _find_payment(
    session,
    payment_entity: dict[str, Any],
    order_entity: dict[str, Any],
) -> PaymentRecord | None:
    provider_payment_id = str(payment_entity.get("id") or "").strip()
    provider_order_id = str(payment_entity.get("order_id") or order_entity.get("id") or "").strip()
    notes = _notes_from(payment_entity, order_entity)

    query = session.query(PaymentRecord)
    candidates = []
    if provider_order_id:
        candidates.append(PaymentRecord.provider_order_id == provider_order_id)
    if provider_payment_id:
        candidates.append(PaymentRecord.provider_payment_id == provider_payment_id)
    if candidates:
        payment = query.filter(or_(*candidates)).first()
        if payment:
            return payment

    local_payment_id = notes.get("payment_id") or notes.get("payment_record_id")
    if local_payment_id:
        try:
            return query.filter(PaymentRecord.id == int(local_payment_id)).first()
        except (TypeError, ValueError):
            return None
    return None


@router.post("/api/payments/razorpay/order")
async def create_razorpay_order(request: Request) -> JSONResponse:
    key_id, key_secret = _razorpay_credentials(request)
    if not key_id or not key_secret:
        return JSONResponse({"ok": False, "error": "Razorpay is not configured"}, status_code=503)
    expected_token = _order_token(request)
    supplied_token = request.headers.get("x-payment-init-token", "")
    admin_token = getattr(request.app.state.container.settings.auth, "admin_token", "")
    if not expected_token:
        return JSONResponse({"ok": False, "error": "Razorpay order token is not configured"}, status_code=503)
    if not (
        hmac.compare_digest(supplied_token, expected_token)
        or hmac.compare_digest(request.headers.get("x-admin-token", ""), admin_token)
    ):
        return JSONResponse({"ok": False, "error": "Invalid payment init token"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)

    try:
        user_id = int(body.get("user_id"))
        plan_id = int(body.get("plan_id"))
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "error": "user_id and plan_id are required"}, status_code=400)

    return await create_razorpay_order_for_user(request, user_id=user_id, plan_id=plan_id)


async def create_razorpay_order_for_user(request: Request, *, user_id: int, plan_id: int) -> JSONResponse:
    key_id, key_secret = _razorpay_credentials(request)
    if not key_id or not key_secret:
        return JSONResponse({"ok": False, "error": "Razorpay is not configured"}, status_code=503)

    session = get_session()
    payment_id = None
    try:
        user = session.query(User).filter(User.id == user_id).first()
        plan = session.query(SubscriptionPlan).filter(
            SubscriptionPlan.id == plan_id,
            SubscriptionPlan.is_active == True,
        ).first()
        if not user or not plan:
            return JSONResponse({"ok": False, "error": "User or active plan not found"}, status_code=404)
        eligibility = check_promo_plan_eligibility(session, user, plan)
        if not eligibility.eligible:
            return JSONResponse({"ok": False, "error": eligibility.reason}, status_code=400)

        now = datetime.now(timezone.utc)
        plan_amount = int(plan.price_amount)
        plan_currency = str(plan.currency or "INR").upper()
        payment = PaymentRecord(
            user_id=user.id,
            plan_id=plan.id,
            payment_method="razorpay",
            payment_provider="razorpay",
            amount=plan_amount,
            currency=plan_currency,
            status="created",
            provider_status="created",
            submitted_at=now,
            expires_at=now + timedelta(hours=1),
            payment_ref=f"rzp:{user.id}:{plan.id}:{int(time.time())}",
        )
        session.add(payment)
        session.commit()
        session.refresh(payment)
        payment_id = int(payment.id)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    order_payload = {
        "amount": plan_amount,
        "currency": plan_currency,
        "receipt": f"eazyfill_payment_{payment_id}",
        "notes": {
            "payment_id": str(payment_id),
            "user_id": str(user_id),
            "plan_id": str(plan_id),
        },
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "https://api.razorpay.com/v1/orders",
                auth=(key_id, key_secret),
                json=order_payload,
            )
        if response.status_code >= 400:
            session = get_session()
            try:
                payment = session.query(PaymentRecord).filter(PaymentRecord.id == payment_id).first()
                if payment:
                    payment.status = "failed"
                    payment.provider_status = "order_create_failed"
                    payment.provider_payload_json = response.text[:4000]
                    payment.updated_at = datetime.now(timezone.utc)
                    session.commit()
            finally:
                session.close()
            return JSONResponse({"ok": False, "error": "Razorpay order creation failed"}, status_code=502)
        order = response.json()
    except Exception as exc:
        logger.exception("razorpay_order_create_failed", extra={"context": {"payment_id": payment_id, "error": str(exc)}})
        return JSONResponse({"ok": False, "error": "Razorpay order creation failed"}, status_code=502)

    session = get_session()
    try:
        payment = session.query(PaymentRecord).filter(PaymentRecord.id == payment_id).first()
        if payment:
            payment.provider_order_id = str(order.get("id") or "")
            payment.provider_status = str(order.get("status") or "created")
            payment.provider_payload_json = json.dumps(order, separators=(",", ":"))
            payment.updated_at = datetime.now(timezone.utc)
            session.commit()
            payload = payment.to_dict()
        else:
            payload = {"id": payment_id}
    finally:
        session.close()

    return JSONResponse({
        "ok": True,
        "key_id": key_id,
        "payment": payload,
        "order": {
            "id": order.get("id"),
            "amount": order.get("amount"),
            "currency": order.get("currency"),
            "status": order.get("status"),
        },
    })


@router.get("/api/payments/{payment_id}/status")
async def get_public_payment_status(payment_id: int) -> JSONResponse:
    session = get_session()
    try:
        payment = session.query(PaymentRecord).filter(PaymentRecord.id == payment_id).first()
        if not payment:
            return JSONResponse({"ok": False, "error": "Payment not found"}, status_code=404)
        return JSONResponse({
            "ok": True,
            "payment": {
                "id": payment.id,
                "status": payment.status,
                "provider_status": payment.provider_status,
                "provider_order_id": payment.provider_order_id,
                "amount": payment.amount,
                "currency": payment.currency,
                "plan_id": payment.plan_id,
                "updated_at": payment.updated_at.isoformat() if payment.updated_at else None,
            },
        })
    finally:
        session.close()


@router.post("/api/webhooks/razorpay")
async def razorpay_webhook(request: Request) -> JSONResponse:
    raw_body = await request.body()
    secret = _webhook_secret(request)
    if not secret:
        return JSONResponse({"ok": False, "error": "Razorpay webhook is not configured"}, status_code=503)

    signature = request.headers.get("x-razorpay-signature", "")
    if not _valid_signature(raw_body, signature, secret):
        return JSONResponse({"ok": False, "error": "Invalid Razorpay signature"}, status_code=400)

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)

    event_id = str(request.headers.get("x-razorpay-event-id") or payload.get("id") or hashlib.sha256(raw_body).hexdigest())
    event_type = str(payload.get("event") or "")
    redis_client, redis_key, claimed = await _claim_redis_dedup(request, event_id)
    if not claimed:
        return JSONResponse({"ok": True, "duplicate": True, "scope": "redis"})

    session = get_session()
    try:
        existing = session.query(PaymentWebhookEvent).filter(
            PaymentWebhookEvent.event_id == event_id,
            PaymentWebhookEvent.provider == "razorpay",
        ).first()
        if existing and existing.status == "processed":
            return JSONResponse({"ok": True, "duplicate": True, "scope": "database"})

        if existing:
            webhook_event = existing
            webhook_event.event_type = event_type
            webhook_event.payload_json = json.dumps(payload, separators=(",", ":"))
            webhook_event.error_message = ""
        else:
            webhook_event = PaymentWebhookEvent(
                provider="razorpay",
                event_id=event_id,
                event_type=event_type,
                payload_json=json.dumps(payload, separators=(",", ":")),
                received_at=datetime.now(timezone.utc),
            )
            session.add(webhook_event)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                return JSONResponse({"ok": True, "duplicate": True, "scope": "database"})

        payment_entity = _payment_entity(payload)
        order_entity = _order_entity(payload)
        payment = _find_payment(session, payment_entity, order_entity)
        if not payment:
            webhook_event.status = "failed"
            webhook_event.error_message = "No matching local payment record"
            webhook_event.processed_at = datetime.now(timezone.utc)
            session.commit()
            return JSONResponse({"ok": False, "error": "No matching payment"}, status_code=202)

        provider_payment_id = str(payment_entity.get("id") or "").strip()
        provider_order_id = str(payment_entity.get("order_id") or order_entity.get("id") or "").strip()
        provider_status = str(payment_entity.get("status") or order_entity.get("status") or event_type)
        amount = int(payment_entity.get("amount") or order_entity.get("amount") or 0)
        currency = str(payment_entity.get("currency") or order_entity.get("currency") or payment.currency or "INR")

        payment.payment_provider = "razorpay"
        payment.payment_method = "razorpay"
        payment.provider_order_id = provider_order_id or payment.provider_order_id
        payment.provider_payment_id = provider_payment_id or payment.provider_payment_id
        payment.provider_signature = signature
        payment.provider_status = provider_status
        payment.provider_payload_json = json.dumps(payload, separators=(",", ":"))
        payment.updated_at = datetime.now(timezone.utc)
        webhook_event.payment_id = payment.id

        captured = event_type in {"payment.captured", "order.paid"} or provider_status in {"captured", "paid"}
        failed = event_type in {"payment.failed"} or provider_status == "failed"
        if captured:
            if int(payment.amount) != amount or str(payment.currency or "INR").upper() != currency.upper():
                webhook_event.status = "failed"
                webhook_event.error_message = "Amount or currency mismatch"
                webhook_event.processed_at = datetime.now(timezone.utc)
                session.commit()
                return JSONResponse({"ok": False, "error": "Amount or currency mismatch"}, status_code=202)

            local_payment_id = int(payment.id)
            session.commit()
            session.close()
            result = request.app.state.container.payment_service.activate_payment(
                local_payment_id,
                triggered_by="razorpay",
            )

            session = get_session()
            webhook_event = session.query(PaymentWebhookEvent).filter(
                PaymentWebhookEvent.event_id == event_id,
                PaymentWebhookEvent.provider == "razorpay",
            ).first()
            if webhook_event:
                webhook_event.status = "processed"
                webhook_event.processed_at = datetime.now(timezone.utc)
                session.commit()
            return JSONResponse({"ok": True, "payment": result["payment"] if result else None})

        if failed:
            payment.status = "rejected"
            payment.rejection_reason = str(payment_entity.get("error_description") or "Razorpay payment failed")

        webhook_event.status = "processed"
        webhook_event.processed_at = datetime.now(timezone.utc)
        session.commit()
        return JSONResponse({"ok": True, "event": event_type, "payment_id": payment.id})
    except Exception as exc:
        session.rollback()
        logger.exception("razorpay_webhook_failed", extra={"context": {"event_id": event_id, "error": str(exc)}})
        await _release_redis_dedup(redis_client, redis_key)
        return JSONResponse({"ok": False, "error": "Webhook processing failed"}, status_code=500)
    finally:
        session.close()
        if redis_client:
            try:
                await redis_client.aclose()
            except Exception:
                pass
