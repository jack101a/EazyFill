import asyncio
from types import SimpleNamespace

from app.services.email_service import EmailDeliveryError, EmailService
import pytest


def _settings(**overrides):
    defaults = {
        "otp_email_enabled": True,
        "otp_email_provider": "brevo",
        "brevo_api_key": "test-key",
        "otp_email_from": "no-reply.eazyfill@002529.xyz",
        "otp_email_from_name": "EazyFill",
        "otp_email_reply_to": "support.eazyfill@002529.xyz",
        "otp_dev_otp_enabled": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(email=SimpleNamespace(**defaults))


class _FakeResponse:
    status_code = 201
    content = b"{}"
    text = "{}"

    def json(self):
        return {"messageId": "message-123"}


def test_brevo_otp_email_payload_uses_eazyfill_sender(monkeypatch):
    calls = []
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://eazyfill.test")

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            self.timeout = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, *, headers, json):
            calls.append({"url": url, "headers": headers, "json": json})
            return _FakeResponse()

    monkeypatch.setattr("app.services.email_service.httpx.AsyncClient", FakeAsyncClient)

    result = asyncio.run(
        EmailService(_settings()).send_otp_email(
            recipient="user@example.com",
            otp="123456",
            ttl_seconds=600,
        )
    )

    assert result.message_id == "message-123"
    payload = calls[0]["json"]
    assert payload["sender"] == {"name": "EazyFill", "email": "no-reply.eazyfill@002529.xyz"}
    assert payload["replyTo"] == {"email": "support.eazyfill@002529.xyz", "name": "EazyFill Support"}
    assert payload["to"] == [{"email": "user@example.com"}]
    assert "123456" in payload["htmlContent"]
    assert "https://eazyfill.test/static/brand/server-avatar-256.png" in payload["htmlContent"]
    assert "Secure account verification" in payload["htmlContent"]
    assert "Sent by EazyFill at" not in payload["htmlContent"]
    assert payload["textContent"] == "Your EazyFill verification code is 123456. It expires in 10 minutes."
    assert calls[0]["headers"]["api-key"] == "test-key"


def test_brevo_otp_email_requires_api_key():
    with pytest.raises(EmailDeliveryError, match="BREVO_API_KEY"):
        asyncio.run(
            EmailService(_settings(brevo_api_key="")).send_otp_email(
                recipient="user@example.com",
                otp="123456",
                ttl_seconds=600,
            )
        )
