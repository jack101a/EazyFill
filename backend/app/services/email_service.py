"""Transactional email delivery for account verification."""

from __future__ import annotations

import html
import logging
import os
from dataclasses import dataclass

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)


class EmailDeliveryError(RuntimeError):
    """Raised when a transactional email cannot be accepted by the provider."""


@dataclass
class EmailDeliveryResult:
    provider: str
    message_id: str = ""


class EmailService:
    """Send branded EazyFill transactional emails."""

    def __init__(self, settings: Settings):
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self._settings.email.otp_email_enabled)

    async def send_otp_email(self, *, recipient: str, otp: str, ttl_seconds: int) -> EmailDeliveryResult:
        config = self._settings.email
        provider = (config.otp_email_provider or "brevo").strip().lower()
        if not config.otp_email_enabled:
            raise EmailDeliveryError("OTP email delivery is disabled")
        if provider != "brevo":
            raise EmailDeliveryError(f"Unsupported OTP email provider: {provider}")
        if not config.brevo_api_key.strip():
            raise EmailDeliveryError("BREVO_API_KEY is not configured")
        if not config.otp_email_from.strip():
            raise EmailDeliveryError("OTP_EMAIL_FROM is not configured")

        payload = self._brevo_otp_payload(
            recipient=recipient,
            otp=otp,
            ttl_seconds=ttl_seconds,
        )
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    "https://api.brevo.com/v3/smtp/email",
                    headers={
                        "accept": "application/json",
                        "api-key": config.brevo_api_key,
                        "content-type": "application/json",
                    },
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise EmailDeliveryError("Could not reach Brevo email API") from exc

        if response.status_code >= 400:
            logger.warning("brevo_otp_email_rejected", extra={"context": {
                "status_code": response.status_code,
                "body": response.text[:500],
            }})
            raise EmailDeliveryError("Brevo rejected the OTP email")

        data = response.json() if response.content else {}
        return EmailDeliveryResult(provider="brevo", message_id=str(data.get("messageId") or ""))

    def _brevo_otp_payload(self, *, recipient: str, otp: str, ttl_seconds: int) -> dict:
        config = self._settings.email
        reply_to = (config.otp_email_reply_to or config.otp_email_from).strip()
        ttl_minutes = max(1, int(ttl_seconds // 60))
        escaped_otp = html.escape(str(otp))
        escaped_reply_to = html.escape(reply_to)
        logo_url = self._brand_logo_url()
        logo_html = ""
        if logo_url:
            logo_html = f"""
                  <img src="{html.escape(logo_url, quote=True)}" width="170" alt="EazyFill" style="display:block;width:170px;max-width:100%;height:auto;border:0;outline:none;text-decoration:none;">"""
        html_content = f"""<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#f4f7fb;font-family:Arial,Helvetica,sans-serif;color:#172033;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f4f7fb;padding:32px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:520px;background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;">
            <tr>
              <td style="padding:24px 32px 20px;background:#120827;border-bottom:1px solid #2b1554;">
                {logo_html}
                <div style="margin-top:10px;font-size:14px;color:#d8d1ff;">Secure account verification</div>
              </td>
            </tr>
            <tr>
              <td style="padding:28px 32px;">
                <h1 style="margin:0 0 12px;font-size:22px;line-height:1.3;color:#0f172a;">Your verification code</h1>
                <p style="margin:0 0 22px;font-size:15px;line-height:1.6;color:#475569;">Use this code to finish signing in to EazyFill. The code expires in {ttl_minutes} minutes.</p>
                <div style="background:#0f172a;color:#ffffff;font-size:34px;font-weight:700;letter-spacing:8px;text-align:center;border-radius:10px;padding:18px 12px;margin:0 0 22px;">{escaped_otp}</div>
                <p style="margin:0 0 18px;font-size:14px;line-height:1.6;color:#64748b;">If you did not request this code, you can safely ignore this email.</p>
                <p style="margin:0;font-size:14px;line-height:1.6;color:#64748b;">Need help? Contact <a href="mailto:{escaped_reply_to}" style="color:#2563eb;text-decoration:none;">{escaped_reply_to}</a>.</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""
        text_content = f"Your EazyFill verification code is {otp}. It expires in {ttl_minutes} minutes."
        payload = {
            "sender": {
                "name": config.otp_email_from_name or "EazyFill",
                "email": config.otp_email_from,
            },
            "to": [{"email": recipient}],
            "replyTo": {"email": reply_to, "name": "EazyFill Support"},
            "subject": "Your EazyFill verification code",
            "htmlContent": html_content,
            "textContent": text_content,
            "tags": ["otp"],
        }
        return payload

    @staticmethod
    def _brand_logo_url() -> str:
        base_url = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
        if not base_url.lower().startswith(("https://", "http://")):
            return ""
        return f"{base_url}/static/brand/email-logo-light.png"
