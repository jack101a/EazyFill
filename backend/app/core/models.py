"""Domain models — users, subscriptions, payments, usage cycles, audit logs.

These models use SQLAlchemy ORM and work with both SQLite and PostgreSQL.
They coexist with the existing raw-SQL tables (api_keys, usage_events, etc.).
"""

from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Float,
    LargeBinary,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════════════════════════════════
# USERS
# ═══════════════════════════════════════════════════════════════════════════════

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    full_name = Column(String(255), nullable=False, default="")
    email = Column(String(255), unique=True, nullable=True, index=True)
    mobile_number = Column(String(20), unique=True, nullable=True)
    status = Column(
        String(32),
        nullable=False,
        default="pending_payment",
        # Values: pending_payment, pending_approval, active, blocked, inactive, expired, deleted
    )
    notes = Column(Text, default="")
    sync_secret = Column(String(128), nullable=True)
    email_verified_at = Column(DateTime, nullable=True)
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    created_by_admin_id = Column(Integer, nullable=True)
    updated_by_admin_id = Column(Integer, nullable=True)

    # Relationships
    subscriptions = relationship("UserSubscription", back_populates="user", lazy="dynamic")
    payments = relationship("PaymentRecord", back_populates="user", lazy="dynamic")
    api_keys = relationship("UserApiKey", back_populates="user", lazy="dynamic")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "full_name": self.full_name,
            "email": self.email,
            "mobile_number": self.mobile_number,
            "status": self.status,
            "notes": self.notes,
            "email_verified_at": self.email_verified_at.isoformat() if self.email_verified_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class UserIdentity(Base):
    __tablename__ = "user_identities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    identity_type = Column(String(32), nullable=False, default="email")
    identifier = Column(String(255), nullable=False, index=True)
    provider = Column(String(64), nullable=False, default="email")
    is_primary = Column(Boolean, nullable=False, default=True)
    verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        UniqueConstraint("identity_type", "identifier", name="uq_user_identity_identifier"),
    )

    user = relationship("User")


# ═══════════════════════════════════════════════════════════════════════════════
# SUBSCRIPTION PLANS
# ═══════════════════════════════════════════════════════════════════════════════

class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(64), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, default="")
    monthly_limit = Column(Integer, nullable=False, default=3000)
    duration_days = Column(Integer, nullable=False, default=30)
    price_amount = Column(Integer, nullable=False, default=0)  # in smallest currency unit (e.g., paise)
    currency = Column(String(3), nullable=False, default="INR")
    is_active = Column(Boolean, nullable=False, default=True)
    show_in_checkout = Column(Boolean, nullable=False, default=True, server_default="1")
    is_promo = Column(Boolean, nullable=False, default=False, server_default="0")
    promo_audience = Column(String(32), nullable=False, default="both", server_default="both")
    max_devices = Column(Integer, default=1, nullable=False, server_default="1")
    allowed_services = Column(JSON, default=dict, nullable=True)  # e.g., {"captcha": true, "autofill": true, "sync": true}
    rate_limit_rpm = Column(Integer, default=60, nullable=False, server_default="60")
    rate_limit_burst = Column(Integer, default=10, nullable=False, server_default="10")
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "description": self.description,
            "monthly_limit": self.monthly_limit,
            "duration_days": self.duration_days,
            "price_amount": self.price_amount,
            "currency": self.currency,
            "is_active": self.is_active,
            "show_in_checkout": self.show_in_checkout,
            "is_promo": self.is_promo,
            "promo_audience": self.promo_audience or "both",
            "max_devices": self.max_devices,
            "allowed_services": self.allowed_services or {},
            "rate_limit_rpm": self.rate_limit_rpm,
            "rate_limit_burst": self.rate_limit_burst,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# USER SUBSCRIPTIONS
# ═══════════════════════════════════════════════════════════════════════════════

class UserSubscription(Base):
    __tablename__ = "user_subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    plan_id = Column(Integer, ForeignKey("subscription_plans.id"), nullable=False)
    status = Column(
        String(32),
        nullable=False,
        default="pending",
        # Values: pending, active, expired, cancelled, rejected
    )
    monthly_limit_snapshot = Column(Integer, nullable=False, default=0)
    start_at = Column(DateTime, nullable=True)
    end_at = Column(DateTime, nullable=True)
    billing_anchor_day = Column(Integer, nullable=True)  # day of month for billing
    current_cycle_start_at = Column(DateTime, nullable=True)
    current_cycle_end_at = Column(DateTime, nullable=True)
    auto_renew_enabled = Column(Boolean, nullable=False, default=False)
    approved_by_admin_id = Column(Integer, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    # Relationships
    user = relationship("User", back_populates="subscriptions")
    plan = relationship("SubscriptionPlan")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "plan_id": self.plan_id,
            "status": self.status,
            "monthly_limit_snapshot": self.monthly_limit_snapshot,
            "start_at": self.start_at.isoformat() if self.start_at else None,
            "end_at": self.end_at.isoformat() if self.end_at else None,
            "current_cycle_start_at": self.current_cycle_start_at.isoformat() if self.current_cycle_start_at else None,
            "current_cycle_end_at": self.current_cycle_end_at.isoformat() if self.current_cycle_end_at else None,
            "auto_renew_enabled": self.auto_renew_enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# PAYMENT RECORDS
# ═══════════════════════════════════════════════════════════════════════════════

class PaymentRecord(Base):
    __tablename__ = "payment_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    subscription_id = Column(Integer, ForeignKey("user_subscriptions.id"), nullable=True)
    plan_id = Column(Integer, ForeignKey("subscription_plans.id"), nullable=True)
    payment_method = Column(String(32), nullable=False, default="razorpay")
    payment_provider = Column(String(32), nullable=False, default="razorpay")
    provider_order_id = Column(String(255), nullable=True, unique=True)
    provider_payment_id = Column(String(255), nullable=True, unique=True)
    provider_signature = Column(String(255), nullable=True)
    provider_status = Column(String(64), nullable=True)
    provider_payload_json = Column(Text, nullable=True)
    amount = Column(Integer, nullable=False, default=0)
    currency = Column(String(3), nullable=False, default="INR")
    payment_ref = Column(String(255), nullable=True)  # generated payment reference/note
    payment_note = Column(Text, default="")
    status = Column(
        String(32),
        nullable=False,
        default="created",
        # Values: created, approved, rejected, expired, failed
    )
    submitted_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)  # payment request expiry
    verified_by_admin_id = Column(Integer, nullable=True)
    verified_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, default="")
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    # Relationships
    user = relationship("User", back_populates="payments")
    plan = relationship("SubscriptionPlan")

    def to_dict(self) -> dict:
        user_obj = self.__dict__.get("user")
        plan_obj = self.__dict__.get("plan")
        return {
            "id": self.id,
            "user_id": self.user_id,
            "subscription_id": self.subscription_id,
            "plan_id": self.plan_id,
            "user_full_name": user_obj.full_name if user_obj else None,
            "user_email": user_obj.email if user_obj else None,
            "user_mobile_number": user_obj.mobile_number if user_obj else None,
            "plan_name": plan_obj.name if plan_obj else None,
            "plan_code": plan_obj.code if plan_obj else None,
            "payment_method": self.payment_method,
            "payment_provider": self.payment_provider,
            "provider_order_id": self.provider_order_id,
            "provider_payment_id": self.provider_payment_id,
            "provider_status": self.provider_status,
            "amount": self.amount,
            "currency": self.currency,
            "payment_ref": self.payment_ref,
            "payment_note": self.payment_note,
            "status": self.status,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "rejection_reason": self.rejection_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# USER API KEYS (user-linked, extends existing api_keys concept)
# ═══════════════════════════════════════════════════════════════════════════════

class UserApiKey(Base):
    __tablename__ = "user_api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    key_hash = Column(String(255), unique=True, nullable=False)
    key_prefix_display = Column(String(16), nullable=False, default="")
    status = Column(
        String(32),
        nullable=False,
        default="active",
        # Values: active, revoked, expired, rotated
    )
    key_version = Column(Integer, nullable=False, default=1)
    issued_at = Column(DateTime, nullable=False, default=_utcnow)
    expires_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    usage_count = Column(Integer, nullable=False, default=0)
    revoked_at = Column(DateTime, nullable=True)
    revoked_reason = Column(String(255), default="")
    rotated_from_key_id = Column(Integer, nullable=True)
    created_by_admin_id = Column(Integer, nullable=True)

    # Relationships
    user = relationship("User", back_populates="api_keys")
    devices = relationship("UserApiKeyDevice", back_populates="api_key", lazy="dynamic")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "key_prefix_display": self.key_prefix_display,
            "status": self.status,
            "key_version": self.key_version,
            "issued_at": self.issued_at.isoformat() if self.issued_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "usage_count": self.usage_count,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# API KEY DEVICES
# ═══════════════════════════════════════════════════════════════════════════════

class UserApiKeyDevice(Base):
    __tablename__ = "user_api_key_devices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    api_key_id = Column(Integer, ForeignKey("user_api_keys.id"), nullable=False, index=True)
    device_fingerprint = Column(String(255), nullable=False)
    device_name = Column(String(255), default="")
    user_agent = Column(String(512), default="")
    first_seen_at = Column(DateTime, nullable=False, default=_utcnow)
    last_seen_at = Column(DateTime, nullable=False, default=_utcnow)
    status = Column(
        String(32),
        nullable=False,
        default="active",
        # Values: active, replaced, blocked
    )

    __table_args__ = (
        UniqueConstraint("api_key_id", "device_fingerprint", name="uq_key_device"),
    )

    # Relationships
    api_key = relationship("UserApiKey", back_populates="devices")


class AuthChallenge(Base):
    __tablename__ = "auth_challenges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    challenge_id = Column(String(128), unique=True, nullable=False, index=True)
    identifier_type = Column(String(32), nullable=False, default="email")
    identifier = Column(String(255), nullable=False, index=True)
    account_mode = Column(String(32), nullable=False, default="signup")
    name = Column(String(255), nullable=False, default="")
    plan_code = Column(String(64), nullable=False, default="free")
    otp_hash = Column(String(128), nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    expires_at = Column(DateTime, nullable=False)
    consumed_at = Column(DateTime, nullable=True)
    client_ip = Column(String(45), nullable=True)
    user_agent = Column(String(512), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    api_key_id = Column(Integer, ForeignKey("user_api_keys.id"), nullable=True, index=True)
    session_hash = Column(String(128), unique=True, nullable=False)
    device_id = Column(String(255), nullable=False, index=True)
    device_name = Column(String(255), default="")
    user_agent = Column(String(512), default="")
    ip_address = Column(String(45), nullable=True)
    status = Column(String(32), nullable=False, default="active")
    issued_at = Column(DateTime, nullable=False, default=_utcnow)
    expires_at = Column(DateTime, nullable=True)
    last_seen_at = Column(DateTime, nullable=False, default=_utcnow)
    revoked_at = Column(DateTime, nullable=True)
    revoke_reason = Column(String(255), default="")



# ═══════════════════════════════════════════════════════════════════════════════
# USAGE CYCLES
# ═══════════════════════════════════════════════════════════════════════════════

class UsageCycle(Base):
    __tablename__ = "usage_cycles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    subscription_id = Column(Integer, ForeignKey("user_subscriptions.id"), nullable=False)
    cycle_start_at = Column(DateTime, nullable=False)
    cycle_end_at = Column(DateTime, nullable=False)
    monthly_limit = Column(Integer, nullable=False, default=0)
    used_count = Column(Integer, nullable=False, default=0)
    blocked_at_limit = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


# ═══════════════════════════════════════════════════════════════════════════════
# AUDIT LOGS
# ═══════════════════════════════════════════════════════════════════════════════

class MeteringPolicy(Base):
    __tablename__ = "metering_policies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(128), unique=True, nullable=False, index=True)
    display_name = Column(String(255), nullable=False, default="")
    unit_cost = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    metadata_json = Column(JSON, default=dict, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "display_name": self.display_name,
            "unit_cost": int(self.unit_cost or 0),
            "is_active": bool(self.is_active),
            "metadata": self.metadata_json or {},
        }


class CreditLedgerEntry(Base):
    __tablename__ = "credit_ledger_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    subscription_id = Column(Integer, ForeignKey("user_subscriptions.id"), nullable=True, index=True)
    cycle_id = Column(Integer, ForeignKey("usage_cycles.id"), nullable=True, index=True)
    event_type = Column(String(128), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="reserved")
    credit_delta = Column(Integer, nullable=False, default=0)
    unit_cost = Column(Integer, nullable=False, default=0)
    amount = Column(Integer, nullable=False, default=1)
    idempotency_key = Column(String(128), unique=True, nullable=True)
    metadata_json = Column(JSON, default=dict, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "subscription_id": self.subscription_id,
            "cycle_id": self.cycle_id,
            "event_type": self.event_type,
            "status": self.status,
            "credit_delta": int(self.credit_delta or 0),
            "unit_cost": int(self.unit_cost or 0),
            "amount": int(self.amount or 0),
            "idempotency_key": self.idempotency_key,
            "metadata": self.metadata_json or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class EncryptedBackup(Base):
    __tablename__ = "encrypted_backups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    device_id = Column(String(255), nullable=False)
    sync_version = Column(Integer, nullable=False, default=1)
    encrypted_blob = Column(LargeBinary, nullable=False)
    blob_hash = Column(String(128), nullable=False)
    blob_size_bytes = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_encrypted_backups_user"),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    actor_type = Column(String(32), nullable=False)  # admin, system, user
    actor_id = Column(Integer, nullable=True)
    action = Column(String(128), nullable=False)
    target_type = Column(String(64), nullable=True)
    target_id = Column(Integer, nullable=True)
    before_json = Column(Text, nullable=True)
    after_json = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)


# ═══════════════════════════════════════════════════════════════════════════════
# REQUEST JOBS (for worker queue)
# ═══════════════════════════════════════════════════════════════════════════════

class RequestJob(Base):
    __tablename__ = "request_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    api_key_id = Column(Integer, nullable=True)
    request_id = Column(String(64), unique=True, nullable=True)
    job_type = Column(String(64), nullable=False)
    priority = Column(Integer, nullable=False, default=0)
    status = Column(
        String(32),
        nullable=False,
        default="queued",
        # Values: queued, running, done, failed, cancelled
    )
    payload_ref = Column(String(512), nullable=True)
    result_ref = Column(String(512), nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, default="")
    queued_at = Column(DateTime, nullable=False, default=_utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)


# ═══════════════════════════════════════════════════════════════════════════════
# BACKUP RUNS
# ═══════════════════════════════════════════════════════════════════════════════

class BackupRun(Base):
    __tablename__ = "backup_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    backup_type = Column(String(32), nullable=False)  # full, logical, snapshot
    status = Column(String(32), nullable=False, default="running")
    storage_target = Column(String(512), nullable=True)
    started_at = Column(DateTime, nullable=False, default=_utcnow)
    finished_at = Column(DateTime, nullable=True)
    file_path_or_uri = Column(String(1024), nullable=True)
    checksum = Column(String(128), nullable=True)
    error_message = Column(Text, default="")


class PaymentWebhookEvent(Base):
    __tablename__ = "payment_webhook_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(32), nullable=False)
    event_id = Column(String(255), nullable=False, unique=True)
    event_type = Column(String(128), nullable=False, default="")
    payment_id = Column(Integer, ForeignKey("payment_records.id"), nullable=True, index=True)
    status = Column(String(32), nullable=False, default="received")
    payload_json = Column(Text, nullable=False, default="")
    error_message = Column(Text, default="")
    received_at = Column(DateTime, nullable=False, default=_utcnow)
    processed_at = Column(DateTime, nullable=True)
