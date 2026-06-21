"""API key management service."""

from __future__ import annotations

from app.core.config import Settings
from app.core.database import Database
from app.core.security import compute_expiry, generate_plain_api_key, hash_api_key, is_expired


class KeyService:
    """Create, validate, and revoke API keys."""

    def __init__(self, db: Database, settings: Settings) -> None:
        self._db = db
        self._settings = settings

    def create_key(self, name: str, expiry_days: int | None, key_type: str = "user") -> tuple[int, str, str | None]:
        """Generate and persist key. Return row id + plain key once."""

        plain = generate_plain_api_key(self._settings)
        key_hash = hash_api_key(plain, self._settings.auth.hash_salt)
        days = expiry_days or self._settings.auth.default_expiry_days
        expires_at = compute_expiry(days) if days > 0 else None
        key_id = self._db.insert_api_key(name=name, key_hash=key_hash, expires_at=expires_at, key_type=key_type)
        return key_id, plain, expires_at

    def revoke_key(self, plain_key: str) -> bool:
        """Revoke key by plain value."""

        key_hash = hash_api_key(plain_key, self._settings.auth.hash_salt)
        return self._db.revoke_api_key(key_hash=key_hash)

    def revoke_key_by_id(self, key_id: int) -> bool:
        """Revoke key by integer id (admin dashboard flow)."""
        return self._db.revoke_api_key_by_id(key_id=key_id)

    def delete_revoked_key_by_id(self, key_id: int) -> bool:
        """Delete revoked key by integer id (admin dashboard flow)."""
        return self._db.delete_revoked_api_key_by_id(key_id=key_id)

    def validate_key(self, plain_key: str) -> dict | None:
        """Return key record when valid/enabled/not-expired."""

        key_hash = hash_api_key(plain_key, self._settings.auth.hash_salt)
        record = self._db.get_api_key_by_hash(key_hash=key_hash)
        if not record:
            return None
        if int(record.get("enabled") or 0) != 1:
            return None
        if is_expired(record.get("expires_at")):
            return None
        # Legacy-key usage tracking for admin visibility.
        try:
            self._db.api_keys.touch_usage(int(record["id"]))
        except Exception:
            pass
        return record

    def get_entitlements(self, key_id: int) -> dict:
        """Return legacy key entitlements."""
        return self._db.get_api_key_entitlements(key_id)

    def validate_or_bind_device(self, key_id: int, device_id: str, user_agent: str | None = None) -> bool:
        """Bind key to first-seen device and reject different devices later."""
        return self._db.validate_or_bind_key_device(
            key_id=key_id,
            device_id=device_id,
            user_agent=user_agent,
        )
