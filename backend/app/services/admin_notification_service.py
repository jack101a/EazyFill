"""Admin notification helpers for low-risk external alerts."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import httpx
from sqlalchemy import text
from sqlalchemy.orm import joinedload

from app.core.models import PaymentRecord

logger = logging.getLogger(__name__)


class AdminNotificationService:
    """Sends non-blocking admin notifications for important payment events."""

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def _session(self):
        return self._session_factory()

    def _read_setting(self, key: str) -> str:
        session = self._session()
        try:
            row = session.execute(
                text("SELECT value FROM platform_settings WHERE key = :key"),
                {"key": key},
            ).fetchone()
            return str(row[0]).strip() if row and row[0] else ""
        except Exception:
            return ""
        finally:
            session.close()

    def _webhook_url(self) -> str:
        return (
            os.getenv("DISCORD_WEBHOOK_URL", "").strip()
            or self._read_setting("notifications.discord_webhook_url")
            or self._read_setting("discord.webhook_url")
        )

    def _enabled(self) -> bool:
        raw = os.getenv("DISCORD_NOTIFY_ENABLED", "true").strip().lower()
        return raw not in {"0", "false", "no", "off"}

    def notify_payment(self, payment_id: int, event_type: str) -> bool:
        """Notify Discord about a payment event."""
        if event_type != "payment_submitted":
            return False
        webhook_url = self._webhook_url()
        if not webhook_url or not self._enabled():
            return False

        session = self._session()
        try:
            payment = (
                session.query(PaymentRecord)
                .options(joinedload(PaymentRecord.user), joinedload(PaymentRecord.plan))
                .filter(PaymentRecord.id == int(payment_id))
                .first()
            )
            if not payment:
                return False
            payload = self._build_payment_payload(payment, event_type)
        finally:
            session.close()

        try:
            response = httpx.post(webhook_url, json=payload, timeout=5.0)
            if response.status_code >= 400:
                logger.warning("discord_notification_failed", extra={"context": {
                    "event_type": event_type,
                    "payment_id": payment_id,
                    "status_code": response.status_code,
                    "body": response.text[:300],
                }})
                return False
            return True
        except Exception as exc:
            logger.warning("discord_notification_error", extra={"context": {
                "event_type": event_type,
                "payment_id": payment_id,
                "error": str(exc),
            }})
            return False

    def _build_payment_payload(self, payment: PaymentRecord, event_type: str) -> dict:
        user = payment.user
        plan = payment.plan
        title = "Payment Submitted"
        amount = f"{payment.currency or 'INR'} {payment.amount / 100:.2f}"
        fields = [
            {"name": "User", "value": user.full_name if user else "Unknown", "inline": True},
            {"name": "Email", "value": (user.email if user else None) or "N/A", "inline": True},
            {"name": "Mobile", "value": (user.mobile_number if user else None) or "N/A", "inline": True},
            {"name": "Plan", "value": plan.name if plan else "N/A", "inline": True},
            {"name": "Amount", "value": amount, "inline": True},
            {"name": "Payment Ref", "value": payment.payment_ref or "N/A", "inline": True},
            {"name": "Provider", "value": payment.payment_provider or "N/A", "inline": True},
            {"name": "Status", "value": payment.status or "N/A", "inline": True},
        ]
        return {
            "username": "EazyFill Admin Alerts",
            "allowed_mentions": {"parse": []},
            "embeds": [{
                "title": title,
                "color": 0x2F80ED,
                "fields": fields,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "footer": {"text": f"Payment ID #{payment.id}"},
            }],
        }
