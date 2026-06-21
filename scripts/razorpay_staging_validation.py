"""Validate Razorpay staging wiring against a deployed EazyFill instance.

This script is intentionally staging-focused. It can:

1. Create a Razorpay order through the app's public order endpoint.
2. Fetch the local payment status endpoint.
3. Optionally replay signed Razorpay-shaped webhook payloads for:
   - captured payment
   - duplicate webhook delivery
   - amount mismatch rejection

It does not print secrets and refuses synthetic capture replays unless
RAZORPAY_VALIDATE_ALLOW_SYNTHETIC_CAPTURE=true is set.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


REQUIRED_ENV = (
    "RAZORPAY_KEY_ID",
    "RAZORPAY_KEY_SECRET",
    "RAZORPAY_WEBHOOK_SECRET",
    "RAZORPAY_ORDER_TOKEN",
)


@dataclass(frozen=True)
class ValidationConfig:
    base_url: str
    user_id: int
    plan_id: int
    timeout_seconds: float
    synthetic_webhooks: bool


class ValidationError(RuntimeError):
    pass


def _env_present(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def _require_env() -> None:
    missing = [name for name in REQUIRED_ENV if not _env_present(name)]
    if missing:
        raise ValidationError(f"Missing required env var(s): {', '.join(missing)}")
    key_id = os.getenv("RAZORPAY_KEY_ID", "").strip()
    if not key_id.startswith("rzp_test_"):
        raise ValidationError("RAZORPAY_KEY_ID must be a Razorpay test-mode key starting with rzp_test_")


def _json_request(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout_seconds: float = 15.0,
) -> tuple[int, dict[str, Any]]:
    body = None
    request_headers = {
        "Accept": "application/json",
        **(headers or {}),
    }
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
            return response.status, json.loads(raw.decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            data = {"error": raw.decode("utf-8", errors="replace")}
        return exc.code, data


def _sign(raw_body: bytes) -> str:
    secret = os.environ["RAZORPAY_WEBHOOK_SECRET"].encode("utf-8")
    return hmac.new(secret, raw_body, hashlib.sha256).hexdigest()


def _webhook_payload(
    *,
    event_type: str,
    order_id: str,
    payment_id: str,
    amount: int,
    currency: str,
    status: str,
) -> bytes:
    payload = {
        "event": event_type,
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "order_id": order_id,
                    "amount": amount,
                    "currency": currency,
                    "status": status,
                }
            }
        },
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _post_webhook(config: ValidationConfig, raw_body: bytes, event_id: str) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        f"{config.base_url}/api/webhooks/razorpay",
        data=raw_body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Razorpay-Signature": _sign(raw_body),
            "X-Razorpay-Event-Id": event_id,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
            return response.status, json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            data = {"error": raw.decode("utf-8", errors="replace")}
        return exc.code, data


def _create_order(config: ValidationConfig) -> dict[str, Any]:
    status, data = _json_request(
        "POST",
        f"{config.base_url}/api/payments/razorpay/order",
        payload={"user_id": config.user_id, "plan_id": config.plan_id},
        headers={"X-Payment-Init-Token": os.environ["RAZORPAY_ORDER_TOKEN"]},
        timeout_seconds=config.timeout_seconds,
    )
    if status != 200 or not data.get("ok"):
        raise ValidationError(f"Order creation failed with HTTP {status}: {data}")
    order = data.get("order") or {}
    payment = data.get("payment") or {}
    if not order.get("id") or not payment.get("id"):
        raise ValidationError(f"Order response is missing order/payment ids: {data}")
    return data


def _payment_status(config: ValidationConfig, payment_id: int) -> dict[str, Any]:
    status, data = _json_request(
        "GET",
        f"{config.base_url}/api/payments/{payment_id}/status",
        timeout_seconds=config.timeout_seconds,
    )
    if status != 200 or not data.get("ok"):
        raise ValidationError(f"Payment status failed with HTTP {status}: {data}")
    return data


def _run_synthetic_webhooks(config: ValidationConfig, order_data: dict[str, Any]) -> dict[str, Any]:
    if not config.synthetic_webhooks:
        return {"skipped": True}
    if os.getenv("RAZORPAY_VALIDATE_ALLOW_SYNTHETIC_CAPTURE", "").strip().lower() not in {"1", "true", "yes", "on"}:
        raise ValidationError(
            "Synthetic webhook replay requires RAZORPAY_VALIDATE_ALLOW_SYNTHETIC_CAPTURE=true. "
            "Use only against a disposable staging user/plan."
        )

    order = order_data["order"]
    payment = order_data["payment"]
    amount = int(order["amount"])
    currency = str(order.get("currency") or "INR").upper()
    stamp = int(time.time())

    captured_body = _webhook_payload(
        event_type="payment.captured",
        order_id=str(order["id"]),
        payment_id=f"pay_validation_{payment['id']}_{stamp}",
        amount=amount,
        currency=currency,
        status="captured",
    )
    captured_event_id = f"evt_validation_capture_{payment['id']}_{stamp}"
    captured_status, captured_data = _post_webhook(config, captured_body, captured_event_id)
    duplicate_status, duplicate_data = _post_webhook(config, captured_body, captured_event_id)

    mismatch_order_data = _create_order(config)
    mismatch_order = mismatch_order_data["order"]
    mismatch_body = _webhook_payload(
        event_type="payment.captured",
        order_id=str(mismatch_order["id"]),
        payment_id=f"pay_validation_mismatch_{mismatch_order_data['payment']['id']}_{stamp}",
        amount=amount + 100,
        currency=currency,
        status="captured",
    )
    mismatch_status, mismatch_data = _post_webhook(
        config,
        mismatch_body,
        f"evt_validation_mismatch_{mismatch_order_data['payment']['id']}_{stamp}",
    )

    if captured_status != 200 or not captured_data.get("ok"):
        raise ValidationError(f"Captured webhook failed with HTTP {captured_status}: {captured_data}")
    if duplicate_status != 200 or not duplicate_data.get("duplicate"):
        raise ValidationError(f"Duplicate webhook was not detected: HTTP {duplicate_status}: {duplicate_data}")
    if mismatch_status != 202 or mismatch_data.get("error") != "Amount or currency mismatch":
        raise ValidationError(f"Mismatch webhook was not safely rejected: HTTP {mismatch_status}: {mismatch_data}")

    return {
        "captured_webhook": captured_data,
        "duplicate_webhook": duplicate_data,
        "mismatch_webhook": mismatch_data,
        "mismatch_payment_id": mismatch_order_data["payment"]["id"],
    }


def parse_args(argv: list[str]) -> ValidationConfig:
    parser = argparse.ArgumentParser(description="Validate Razorpay staging integration.")
    parser.add_argument("--base-url", default=os.getenv("APP_BASE_URL", "").rstrip("/"))
    parser.add_argument("--user-id", type=int, default=int(os.getenv("RAZORPAY_VALIDATE_USER_ID", "0") or "0"))
    parser.add_argument("--plan-id", type=int, default=int(os.getenv("RAZORPAY_VALIDATE_PLAN_ID", "0") or "0"))
    parser.add_argument("--timeout-seconds", type=float, default=float(os.getenv("RAZORPAY_VALIDATE_TIMEOUT_SECONDS", "15")))
    parser.add_argument("--synthetic-webhooks", action="store_true", default=os.getenv("RAZORPAY_VALIDATE_SYNTHETIC_WEBHOOKS", "").strip().lower() in {"1", "true", "yes", "on"})
    args = parser.parse_args(argv)

    if not args.base_url:
        raise ValidationError("Provide --base-url or APP_BASE_URL")
    if not args.base_url.startswith("https://"):
        raise ValidationError("Use an HTTPS staging base URL for Razorpay validation")
    if args.user_id <= 0 or args.plan_id <= 0:
        raise ValidationError("Provide --user-id/--plan-id or RAZORPAY_VALIDATE_USER_ID/RAZORPAY_VALIDATE_PLAN_ID")
    return ValidationConfig(
        base_url=args.base_url.rstrip("/"),
        user_id=args.user_id,
        plan_id=args.plan_id,
        timeout_seconds=args.timeout_seconds,
        synthetic_webhooks=bool(args.synthetic_webhooks),
    )


def main(argv: list[str] | None = None) -> int:
    try:
        _require_env()
        config = parse_args(argv or sys.argv[1:])
        order_data = _create_order(config)
        status_data = _payment_status(config, int(order_data["payment"]["id"]))
        webhook_data = _run_synthetic_webhooks(config, order_data)
        result = {
            "ok": True,
            "base_url": config.base_url,
            "order_id": order_data["order"]["id"],
            "payment_id": order_data["payment"]["id"],
            "payment_status": status_data["payment"]["status"],
            "synthetic_webhooks": webhook_data,
            "next_manual_step": "Open admin UI Razorpay checkout and complete a Razorpay test payment to verify real webhook delivery.",
        }
        print(json.dumps(result, indent=2))
        return 0
    except ValidationError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
