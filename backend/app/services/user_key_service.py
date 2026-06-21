"""User-linked API key lifecycle — create, rotate, revoke, device binding."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.models import SubscriptionPlan, UserApiKey, UserApiKeyDevice, User, UserSubscription
from app.core.security import generate_plain_api_key, hash_api_key, compute_expiry_datetime


class UserKeyService:
    """Manages user-linked API keys with device binding and rotation."""

    def __init__(self, session_factory, settings: Settings):
        self._session_factory = session_factory
        self._settings = settings
        self._lock = threading.Lock()

    def _session(self) -> Session:
        return self._session_factory()

    # ── Key Creation ──────────────────────────────────────────────────────

    def create_key(
        self,
        user_id: int,
        expiry_days: int | None = None,
        created_by_admin_id: int | None = None,
        revoke_existing: bool = False,
    ) -> tuple[UserApiKey, str]:
        """Create a new API key for a user.

        Normal account/device login creates an additional active key so multiple
        devices can remain connected. Explicit rotation passes
        ``revoke_existing=True`` or uses ``rotate_key``.

        Returns (key_record, plain_key)."""
        with self._lock:
            session = self._session()
            try:
                if revoke_existing:
                    session.query(UserApiKey).filter(
                        UserApiKey.user_id == user_id,
                        UserApiKey.status == "active",
                    ).update({"status": "rotated", "revoked_at": datetime.now(timezone.utc)})

                # Generate new key
                plain = generate_plain_api_key(self._settings)
                key_hash = hash_api_key(plain, self._settings.auth.hash_salt)
                expires_at = compute_expiry_datetime(expiry_days) if expiry_days else None

                key = UserApiKey(
                    user_id=user_id,
                    key_hash=key_hash,
                    key_prefix_display=plain[:10] + "...",
                    status="active",
                    key_version=1,
                    issued_at=datetime.now(timezone.utc),
                    expires_at=expires_at,
                    created_by_admin_id=created_by_admin_id,
                )
                session.add(key)
                session.commit()
                session.refresh(key)
                return key, plain
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

    def rotate_key(
        self,
        user_id: int,
        created_by_admin_id: int | None = None,
    ) -> tuple[UserApiKey, str]:
        """Rotate: revoke old key, issue new one with incremented version."""
        with self._lock:
            session = self._session()
            try:
                active_keys = (
                    session.query(UserApiKey)
                    .filter(UserApiKey.user_id == user_id, UserApiKey.status == "active")
                    .all()
                )
                old_version = max((int(key.key_version or 0) for key in active_keys), default=0)
                old_id = active_keys[0].id if active_keys else None

                for old in active_keys:
                    old.status = "rotated"
                    old.revoked_at = datetime.now(timezone.utc)
                    old.revoked_reason = "key_rotation"

                # Issue new
                plain = generate_plain_api_key(self._settings)
                key_hash = hash_api_key(plain, self._settings.auth.hash_salt)
                key = UserApiKey(
                    user_id=user_id,
                    key_hash=key_hash,
                    key_prefix_display=plain[:10] + "...",
                    status="active",
                    key_version=old_version + 1,
                    issued_at=datetime.now(timezone.utc),
                    expires_at=None,
                    rotated_from_key_id=old_id,
                    created_by_admin_id=created_by_admin_id,
                )
                session.add(key)
                session.commit()
                session.refresh(key)
                return key, plain
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

    def revoke_key(self, key_id: int, reason: str = "") -> UserApiKey | None:
        session = self._session()
        try:
            key = session.query(UserApiKey).filter(UserApiKey.id == key_id).first()
            if not key:
                return None
            key.status = "revoked"
            key.revoked_at = datetime.now(timezone.utc)
            key.revoked_reason = reason
            session.commit()
            session.refresh(key)
            return key
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def delete_key(self, key_id: int) -> bool:
        """Delete one user-linked key and its device bindings."""
        session = self._session()
        try:
            key = session.query(UserApiKey).filter(UserApiKey.id == key_id).first()
            if not key:
                return False
            session.query(UserApiKeyDevice).filter(UserApiKeyDevice.api_key_id == key_id).delete()
            session.delete(key)
            session.commit()
            return True
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def delete_revoked_keys(self) -> int:
        """Delete user-linked keys explicitly marked revoked."""
        session = self._session()
        try:
            keys = session.query(UserApiKey).filter(UserApiKey.status == "revoked").all()
            key_ids = [int(key.id) for key in keys]
            if not key_ids:
                return 0
            session.query(UserApiKeyDevice).filter(UserApiKeyDevice.api_key_id.in_(key_ids)).delete(synchronize_session=False)
            session.query(UserApiKey).filter(UserApiKey.id.in_(key_ids)).delete(synchronize_session=False)
            session.commit()
            return len(key_ids)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ── Validation ────────────────────────────────────────────────────────

    def validate_key(self, plain_key: str) -> dict | None:
        """Validate a user-linked API key against key, user, and subscription state.

        Unknown keys return None so legacy-key validation can still run. Known
        user keys with denied access return an auth_error code for client UX.
        """
        key_hash = hash_api_key(plain_key, self._settings.auth.hash_salt)
        session = self._session()
        try:
            key = (
                session.query(UserApiKey)
                .filter(UserApiKey.key_hash == key_hash)
                .first()
            )
            if not key:
                return None

            base_record = {
                "id": key.id,
                "user_id": key.user_id,
                "key_hash": key.key_hash,
                "name": f"User {key.user_id}",
                "key_type": "user_linked",
                "expires_at": key.expires_at.isoformat() if key.expires_at else None,
                "status": key.status,
                "key_version": key.key_version,
            }

            if key.status != "active":
                error_code = "expired_key" if key.status == "expired" else "revoked_key"
                return {**base_record, "auth_error": error_code}

            # Check expiry
            if key.expires_at:
                expires_at = key.expires_at
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if expires_at < datetime.now(timezone.utc):
                    return {**base_record, "auth_error": "expired_key"}

            # Check user status
            user = session.query(User).filter(User.id == key.user_id).first()
            if not user:
                return {**base_record, "auth_error": "inactive_user", "user_status": "missing"}
            base_record["name"] = user.full_name or f"User {user.id}"
            base_record["user_status"] = user.status

            if user.status == "blocked":
                return {**base_record, "auth_error": "blocked_user"}
            if user.status == "pending_payment":
                return {**base_record, "auth_error": "payment_pending"}
            if user.status != "active":
                return {**base_record, "auth_error": "expired_subscription"}

            now = datetime.now(timezone.utc)
            sub = (
                session.query(UserSubscription)
                .filter(
                    UserSubscription.user_id == key.user_id,
                    UserSubscription.status == "active",
                )
                .order_by(UserSubscription.created_at.desc())
                .first()
            )
            if not sub:
                return {**base_record, "auth_error": "expired_subscription"}
            if sub.end_at:
                end_at = sub.end_at
                if end_at.tzinfo is None:
                    end_at = end_at.replace(tzinfo=timezone.utc)
                if end_at < now:
                    return {**base_record, "auth_error": "expired_subscription"}

            # Update usage tracking
            key.last_used_at = now
            key.usage_count = (key.usage_count or 0) + 1
            session.commit()

            return base_record
        finally:
            session.close()

    def legacy_user_access(self, entitlements: dict | None) -> dict | None:
        """Return subscription-gated access for a legacy key linked to a user.

        Legacy keys predate the user/subscription tables. When a legacy key has
        a mobile number that clearly maps to a user, use the user's subscription
        as the source of truth so expired/downgraded plans cannot keep working
        through the old key path. Unlinked legacy keys return None and keep their
        existing legacy behavior.
        """
        session = self._session()
        try:
            user = self._find_user_for_legacy_entitlements(session, entitlements or {})
            if not user:
                return None

            base = {
                "user_id": user.id,
                "user_status": user.status,
            }
            if user.status == "blocked":
                return {**base, "auth_error": "blocked_user"}
            if user.status == "pending_payment":
                return {**base, "auth_error": "payment_pending"}
            if user.status != "active":
                return {**base, "auth_error": "expired_subscription"}

            now = datetime.now(timezone.utc)
            sub = (
                session.query(UserSubscription)
                .filter(
                    UserSubscription.user_id == user.id,
                    UserSubscription.status == "active",
                )
                .order_by(UserSubscription.created_at.desc())
                .first()
            )
            if not sub:
                return {**base, "auth_error": "expired_subscription"}
            if sub.end_at:
                end_at = sub.end_at if sub.end_at.tzinfo else sub.end_at.replace(tzinfo=timezone.utc)
                if end_at < now:
                    return {**base, "auth_error": "expired_subscription"}

            plan = session.query(SubscriptionPlan).filter(SubscriptionPlan.id == sub.plan_id).first()
            return {
                **base,
                "entitlements": {
                    "plan_name": plan.name if plan else str((entitlements or {}).get("plan_name") or "Standard"),
                    "mobile": user.mobile_number or str((entitlements or {}).get("mobile") or ""),
                    "services": (plan.allowed_services or {}) if plan else ((entitlements or {}).get("services") or {}),
                    "subscription_expires_at": sub.end_at.isoformat() if sub.end_at else None,
                },
            }
        finally:
            session.close()

    @staticmethod
    def _digits(value: object) -> str:
        return "".join(ch for ch in str(value or "") if ch.isdigit())

    def _find_user_for_legacy_entitlements(self, session: Session, entitlements: dict) -> User | None:
        mobile = str(entitlements.get("mobile") or "").strip()

        if mobile:
            user = session.query(User).filter(User.mobile_number == mobile).first()
            if user:
                return user
            wanted_digits = self._digits(mobile)
            if wanted_digits:
                candidates = session.query(User).filter(User.mobile_number.isnot(None)).all()
                for candidate in candidates:
                    candidate_digits = self._digits(candidate.mobile_number)
                    if candidate_digits == wanted_digits:
                        return candidate
                    if len(candidate_digits) >= 10 and len(wanted_digits) >= 10 and candidate_digits[-10:] == wanted_digits[-10:]:
                        return candidate

        return None

    def get_user_key(self, user_id: int) -> UserApiKey | None:
        session = self._session()
        try:
            return (
                session.query(UserApiKey)
                .filter(UserApiKey.user_id == user_id, UserApiKey.status == "active")
                .first()
            )
        finally:
            session.close()

    def list_user_keys(self, user_id: int) -> list[UserApiKey]:
        session = self._session()
        try:
            return (
                session.query(UserApiKey)
                .filter(UserApiKey.user_id == int(user_id))
                .order_by(UserApiKey.issued_at.desc())
                .all()
            )
        finally:
            session.close()

    def revoke_user_key(self, user_id: int, key_id: int, reason: str = "") -> UserApiKey | None:
        session = self._session()
        try:
            key = (
                session.query(UserApiKey)
                .filter(UserApiKey.id == int(key_id), UserApiKey.user_id == int(user_id))
                .first()
            )
            if not key:
                return None
            key.status = "revoked"
            key.revoked_at = datetime.now(timezone.utc)
            key.revoked_reason = reason
            session.commit()
            session.refresh(key)
            return key
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ── Device Binding ────────────────────────────────────────────────────

    def bind_device(
        self,
        api_key_id: int,
        device_fingerprint: str,
        device_name: str = "",
        user_agent: str = "",
    ) -> UserApiKeyDevice:
        session = self._session()
        try:
            now = datetime.now(timezone.utc)
            # Check if already bound
            existing = (
                session.query(UserApiKeyDevice)
                .filter(
                    UserApiKeyDevice.api_key_id == api_key_id,
                    UserApiKeyDevice.device_fingerprint == device_fingerprint,
                )
                .first()
            )
            if existing:
                existing.last_seen_at = now
                session.commit()
                return existing

            # Check device limit from user's plan
            max_devices = 1  # default
            try:
                from app.core.models import UserSubscription, SubscriptionPlan
                key = session.query(UserApiKey).filter(UserApiKey.id == api_key_id).first()
                if key and key.user_id:
                    sub = (
                        session.query(UserSubscription)
                        .filter(
                            UserSubscription.user_id == key.user_id,
                            UserSubscription.status == "active",
                        )
                        .order_by(UserSubscription.created_at.desc())
                        .first()
                    )
                    if sub and sub.plan_id:
                        plan = session.query(SubscriptionPlan).filter(
                            SubscriptionPlan.id == sub.plan_id
                        ).first()
                        if plan and plan.max_devices:
                            max_devices = plan.max_devices
            except Exception:
                pass  # Fall back to default of 1

            active_devices = (
                session.query(UserApiKeyDevice)
                .filter(
                    UserApiKeyDevice.api_key_id == api_key_id,
                    UserApiKeyDevice.status == "active",
                )
                .all()
            )
            # Check if this device is already bound
            for dev in active_devices:
                if dev.device_fingerprint == device_fingerprint:
                    dev.last_seen_at = now
                    session.commit()
                    return dev
            # Check if device limit reached
            if len(active_devices) >= max_devices:
                return None  # Caller should handle as "device_limit_reached"

            device = UserApiKeyDevice(
                api_key_id=api_key_id,
                device_fingerprint=device_fingerprint,
                device_name=device_name,
                user_agent=user_agent,
                first_seen_at=now,
                last_seen_at=now,
                status="active",
            )
            session.add(device)
            session.commit()
            session.refresh(device)
            return device
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def validate_device(self, api_key_id: int, device_fingerprint: str) -> bool:
        """Check if device is authorized for this key."""
        session = self._session()
        try:
            device = (
                session.query(UserApiKeyDevice)
                .filter(
                    UserApiKeyDevice.api_key_id == api_key_id,
                    UserApiKeyDevice.device_fingerprint == device_fingerprint,
                    UserApiKeyDevice.status == "active",
                )
                .first()
            )
            if device:
                device.last_seen_at = datetime.now(timezone.utc)
                session.commit()
                return True
            return False
        except Exception:
            session.rollback()
            return False
        finally:
            session.close()

    def reset_device_binding(self, api_key_id: int) -> None:
        """Admin override: clear all device bindings for a key."""
        session = self._session()
        try:
            session.query(UserApiKeyDevice).filter(
                UserApiKeyDevice.api_key_id == api_key_id
            ).update({"status": "replaced"})
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_user_devices(self, user_id: int) -> list[UserApiKeyDevice]:
        session = self._session()
        try:
            key = self.get_user_key(user_id)
            if not key:
                return []
            return (
                session.query(UserApiKeyDevice)
                .filter(UserApiKeyDevice.api_key_id == key.id)
                .order_by(UserApiKeyDevice.last_seen_at.desc())
                .all()
            )
        finally:
            session.close()

    def remove_user_device(self, user_id: int, device_id: int) -> bool:
        session = self._session()
        try:
            key_ids = [
                int(key.id)
                for key in session.query(UserApiKey).filter(UserApiKey.user_id == int(user_id)).all()
            ]
            if not key_ids:
                return False
            device = (
                session.query(UserApiKeyDevice)
                .filter(UserApiKeyDevice.id == int(device_id), UserApiKeyDevice.api_key_id.in_(key_ids))
                .first()
            )
            if not device:
                return False
            device.status = "replaced"
            device.last_seen_at = datetime.now(timezone.utc)
            session.commit()
            return True
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
