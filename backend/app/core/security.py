"""Security helpers for API keys and request payloads."""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from app.core.config import Settings


def generate_plain_api_key(settings: Settings) -> str:
    """Generate a new API key string."""

    token = secrets.token_urlsafe(settings.auth.key_length)
    return f"{settings.auth.key_prefix}{token}"


def hash_api_key(plain_key: str, salt: str) -> str:
    """Hash API key with SHA-256 + salt."""

    raw = f"{salt}:{plain_key}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def compute_expiry(days: int) -> str:
    """Return UTC ISO expiration timestamp string (for legacy TEXT columns)."""

    expires = datetime.now(timezone.utc) + timedelta(days=days)
    return expires.isoformat()


def compute_expiry_datetime(days: int) -> datetime | None:
    """Return UTC expiration as datetime (for SQLAlchemy DateTime columns)."""
    if days <= 0:
        return None
    return datetime.now(timezone.utc) + timedelta(days=days)


def is_expired(expires_at: str | None) -> bool:
    """Check expiration timestamp."""

    if not expires_at:
        return False
    return datetime.fromisoformat(expires_at) < datetime.now(timezone.utc)


def is_valid_base64(payload: str) -> bool:
    """
    Validate if payload is decodable base64.

    Handles data-URI prefixes (e.g. ``data:image/png;base64,<data>``) that
    browsers produce — the prefix is stripped before validation so callers
    do not need to pre-process the string.
    """
    try:
        raw = payload
        # Strip data-URI prefix before validating
        if raw.startswith("data:") and "," in raw:
            raw = raw.split(",", 1)[1]
        base64.b64decode(raw, validate=True)
        return True
    except Exception:
        return False
