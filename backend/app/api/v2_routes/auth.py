"""EazyFill v2 authentication endpoints."""

from __future__ import annotations

import hashlib
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import or_

from app.api.v2_routes.deps import credits_payload, ensure_user_sync_secret, key_info_payload, plan_payload, user_payload, validate_v2_key
from app.core.config import DEFAULT_OTP_ALLOWED_EMAIL_DOMAINS, DEFAULT_OTP_BLOCKED_EMAIL_DOMAINS
from app.core.db import get_session
from app.core.models import AuthChallenge, SubscriptionPlan, User, UserSession, UserSubscription
from app.services.email_service import EmailDeliveryError

router = APIRouter(prefix="/auth", tags=["v2-auth"])
logger = logging.getLogger(__name__)

OTP_TTL_SECONDS = 10 * 60
OTP_REGISTER_WINDOW_SECONDS = 5 * 60
OTP_REGISTER_MAX_PER_IDENTIFIER = 3
OTP_REGISTER_MAX_PER_CLIENT = 12
_OTP_REGISTER_EVENTS: dict[str, list[float]] = {}

SUPPORTED_EMAIL_MESSAGE = (
    "Use a supported personal email provider such as Gmail, Outlook, Hotmail, "
    "Proton Mail, Rediffmail, Yahoo, iCloud, Zoho, or Fastmail."
)


class VerifyKeyRequest(BaseModel):
    api_key: str = Field(min_length=5)


class RegisterRequest(BaseModel):
    identifier: str = Field(default="", max_length=255)
    email: str = Field(default="", max_length=255)
    mobile: str = Field(default="", max_length=32)
    name: str = Field(default="", max_length=255)
    plan_code: str = Field(default="free", max_length=64)


class VerifyOtpRequest(BaseModel):
    challenge_id: str = Field(min_length=8)
    otp: str = Field(min_length=4, max_length=12)
    device_name: str = Field(default="", max_length=255)


class RefreshRequest(BaseModel):
    api_key: str = Field(default="", min_length=0)


def _clean_identifier(payload: RegisterRequest) -> tuple[str, str]:
    raw = (payload.email or payload.mobile or payload.identifier or "").strip()
    if not raw:
        raise HTTPException(status_code=422, detail={"error": "identifier_required", "message": "Email is required"})
    if "@" in raw:
        return "email", raw.lower()
    return "mobile", "".join(ch for ch in raw if ch.isdigit()) or raw


def _email_domain(email: str) -> str:
    parts = str(email or "").strip().lower().rsplit("@", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise HTTPException(status_code=422, detail={"error": "email_required", "message": "Enter a valid email address"})
    return parts[1].strip(".")


def _email_domain_set(settings: Any, name: str, fallback: list[str]) -> set[str]:
    email_config = getattr(settings, "email", None)
    value = getattr(email_config, name, fallback)
    if isinstance(value, str):
        return {part.strip().lower() for part in value.split(",") if part.strip()}
    return {str(part).strip().lower() for part in (value or fallback) if str(part).strip()}


def _validate_supported_email(settings: Any, email: str) -> None:
    domain = _email_domain(email)
    blocked = _email_domain_set(settings, "otp_blocked_email_domains", DEFAULT_OTP_BLOCKED_EMAIL_DOMAINS)
    if domain in blocked:
        raise HTTPException(
            status_code=422,
            detail={"error": "temporary_email_not_allowed", "message": "Temporary email addresses are not supported."},
        )
    allowed = _email_domain_set(settings, "otp_allowed_email_domains", DEFAULT_OTP_ALLOWED_EMAIL_DOMAINS)
    if allowed and domain not in allowed:
        raise HTTPException(
            status_code=422,
            detail={"error": "unsupported_email_domain", "message": SUPPORTED_EMAIL_MESSAGE},
        )


def _otp_hash(otp: str) -> str:
    return hashlib.sha256(str(otp).encode("utf-8")).hexdigest()


def _session_hash(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _purge_expired_challenges(session) -> None:
    now = _utcnow_naive()
    (
        session.query(AuthChallenge)
        .filter(AuthChallenge.status == "pending", AuthChallenge.expires_at <= now)
        .update({"status": "expired", "updated_at": now}, synchronize_session=False)
    )


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    if forwarded:
        return f"ip:{forwarded}"
    if request.client and request.client.host:
        return f"ip:{request.client.host}"
    return "ip:unknown"


def _raise_otp_rate_limited() -> None:
    raise HTTPException(
        status_code=429,
        detail={
            "error": "otp_rate_limited",
            "message": "Too many verification code requests. Try again shortly.",
            "retry_after_seconds": OTP_REGISTER_WINDOW_SECONDS,
        },
    )


def _consume_otp_register_quota_memory(request: Request, identifier_type: str, identifier: str) -> None:
    now = time.time()
    cutoff = now - OTP_REGISTER_WINDOW_SECONDS
    scopes = [
        (f"identifier:{identifier_type}:{identifier}", OTP_REGISTER_MAX_PER_IDENTIFIER),
        (_client_key(request), OTP_REGISTER_MAX_PER_CLIENT),
    ]
    for scope, _limit in scopes:
        _OTP_REGISTER_EVENTS[scope] = [ts for ts in _OTP_REGISTER_EVENTS.get(scope, []) if ts >= cutoff]
    for scope, limit in scopes:
        if len(_OTP_REGISTER_EVENTS.get(scope, [])) >= limit:
            _raise_otp_rate_limited()
    for scope, _limit in scopes:
        _OTP_REGISTER_EVENTS.setdefault(scope, []).append(now)


async def _consume_otp_register_quota(request: Request, identifier_type: str, identifier: str) -> None:
    container = getattr(request.app.state, "container", None)
    limiter = getattr(container, "rate_limiter", None)
    if limiter and hasattr(limiter, "check"):
        try:
            client_allowed = await limiter.check(
                "otp_register_client",
                _client_key(request),
                OTP_REGISTER_MAX_PER_CLIENT,
                OTP_REGISTER_WINDOW_SECONDS,
            )
            identifier_allowed = await limiter.check(
                "otp_register_identifier",
                f"{identifier_type}:{identifier}",
                OTP_REGISTER_MAX_PER_IDENTIFIER,
                OTP_REGISTER_WINDOW_SECONDS,
            )
            if not client_allowed or not identifier_allowed:
                _raise_otp_rate_limited()
            return
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning(
                "otp_register_rate_limiter_failed_fallback_memory",
                extra={"context": {"error_type": type(exc).__name__}},
            )
    _consume_otp_register_quota_memory(request, identifier_type, identifier)


def _client_ip(request: Request) -> str:
    return _client_key(request).removeprefix("ip:")[:45]


def _drop_existing_identifier_challenges(session, identifier_type: str, identifier: str) -> None:
    now = _utcnow_naive()
    (
        session.query(AuthChallenge)
        .filter(
            AuthChallenge.identifier_type == identifier_type,
            AuthChallenge.identifier == identifier,
            AuthChallenge.status == "pending",
        )
        .update({"status": "replaced", "updated_at": now}, synchronize_session=False)
    )


def _create_auth_challenge(
    session,
    request: Request,
    *,
    identifier_type: str,
    identifier: str,
    name: str,
    plan_code: str,
    otp: str,
    account_mode: str,
) -> AuthChallenge:
    now = _utcnow_naive()
    challenge = AuthChallenge(
        challenge_id=secrets.token_urlsafe(24),
        identifier_type=identifier_type,
        identifier=identifier,
        account_mode=account_mode,
        name=name.strip(),
        plan_code=(plan_code or "free").strip().lower(),
        otp_hash=_otp_hash(otp),
        status="pending",
        attempts=0,
        expires_at=now + timedelta(seconds=OTP_TTL_SECONDS),
        client_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent", "")[:512],
        created_at=now,
        updated_at=now,
    )
    session.add(challenge)
    session.flush()
    return challenge


def _load_pending_challenge(session, challenge_id: str) -> AuthChallenge | None:
    return (
        session.query(AuthChallenge)
        .filter(AuthChallenge.challenge_id == challenge_id, AuthChallenge.status == "pending")
        .first()
    )


def _challenge_payload(challenge: AuthChallenge) -> dict[str, Any]:
    return {
        "identifier_type": challenge.identifier_type,
        "identifier": challenge.identifier,
        "name": challenge.name,
        "plan_code": challenge.plan_code,
    }


def _mark_challenge_status(challenge_id: str, status: str) -> None:
    session = get_session()
    try:
        now = _utcnow_naive()
        (
            session.query(AuthChallenge)
            .filter(AuthChallenge.challenge_id == challenge_id)
            .update({"status": status, "updated_at": now}, synchronize_session=False)
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _dev_otp_enabled(settings: Any) -> bool:
    if not getattr(getattr(settings, "server", None), "debug", False):
        return False
    email_config = getattr(settings, "email", None)
    return bool(getattr(email_config, "otp_dev_otp_enabled", False))


def _find_plan(session, plan_code: str) -> SubscriptionPlan | None:
    wanted = (plan_code or "free").strip().lower()
    candidates = [wanted, "free", "basic"]
    for code in candidates:
        plan = (
            session.query(SubscriptionPlan)
            .filter(SubscriptionPlan.code == code, SubscriptionPlan.is_active == True)  # noqa: E712
            .first()
        )
        if plan:
            return plan
    return (
        session.query(SubscriptionPlan)
        .filter(SubscriptionPlan.is_active == True)  # noqa: E712
        .order_by(SubscriptionPlan.price_amount.asc(), SubscriptionPlan.id.asc())
        .first()
    )


def _login_plan(session, plan_code: str) -> SubscriptionPlan | None:
    plan = _find_plan(session, plan_code)
    if plan and int(plan.price_amount or 0) <= 0:
        return plan
    return _find_plan(session, "free")


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _user_for_identifier(session, identifier_type: str, identifier: str) -> User | None:
    if identifier_type == "mobile":
        return session.query(User).filter(User.mobile_number == identifier).first()
    existing = session.query(User).filter(User.email == identifier).first()
    if existing:
        return existing
    eazyfill_token = f"eazyfill_email:{identifier}"
    flowpilot_token = f"flowpilot_email:{identifier}"
    return session.query(User).filter(or_(
        User.notes.like(f"%{eazyfill_token}%"),
        User.notes.like(f"%{flowpilot_token}%"),
    )).first()


def _create_or_update_user(session, challenge: dict[str, Any]) -> User:
    identifier_type = str(challenge["identifier_type"])
    identifier = str(challenge["identifier"])
    user = _user_for_identifier(session, identifier_type, identifier)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    name = str(challenge.get("name") or "").strip()
    if user:
        if identifier_type == "email":
            user.email = identifier
            user.email_verified_at = now
        if name:
            user.full_name = name
        if user.status not in {"blocked", "active"}:
            user.status = "active"
        user.last_login_at = now
        user.updated_at = now
        return user

    notes = ""
    mobile = identifier if identifier_type == "mobile" else None
    user = User(
        full_name=name or "EazyFill User",
        email=identifier if identifier_type == "email" else None,
        mobile_number=mobile,
        status="active",
        notes=notes,
        email_verified_at=now if identifier_type == "email" else None,
        last_login_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    session.flush()
    return user


def _ensure_subscription(session, user: User, plan_code: str) -> UserSubscription | None:
    now = datetime.now(timezone.utc)
    existing = (
        session.query(UserSubscription)
        .filter(UserSubscription.user_id == user.id, UserSubscription.status == "active")
        .order_by(UserSubscription.created_at.desc())
        .first()
    )
    if existing:
        end_at = _as_utc(existing.end_at)
        if end_at is None or end_at >= now:
            return existing
        existing.status = "expired"
        existing.updated_at = now.replace(tzinfo=None)
        session.flush()

    plan = _login_plan(session, plan_code)
    if not plan:
        return None
    sub = UserSubscription(
        user_id=user.id,
        plan_id=plan.id,
        status="active",
        monthly_limit_snapshot=plan.monthly_limit,
        start_at=now,
        end_at=now + timedelta(days=int(plan.duration_days or 30)),
        billing_anchor_day=now.day,
        current_cycle_start_at=now,
        current_cycle_end_at=now + timedelta(days=30),
        approved_at=now,
    )
    session.add(sub)
    session.flush()
    return sub


def _issue_user_session(
    request: Request,
    *,
    user_id: int,
    api_key_id: int | None,
    device_id: str,
    device_name: str,
) -> tuple[str, dict[str, Any]]:
    token = f"efs_{secrets.token_urlsafe(32)}"
    now = _utcnow_naive()
    expires_at = now + timedelta(days=90)
    session = get_session()
    try:
        (
            session.query(UserSession)
            .filter(
                UserSession.user_id == user_id,
                UserSession.device_id == device_id,
                UserSession.status == "active",
            )
            .update(
                {
                    "status": "replaced",
                    "revoked_at": now,
                    "revoke_reason": "new_login",
                },
                synchronize_session=False,
            )
        )
        record = UserSession(
            user_id=user_id,
            api_key_id=api_key_id,
            session_hash=_session_hash(token),
            device_id=device_id,
            device_name=device_name[:255],
            user_agent=request.headers.get("user-agent", "")[:512],
            ip_address=_client_ip(request),
            status="active",
            issued_at=now,
            expires_at=expires_at,
            last_seen_at=now,
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        return token, {
            "id": record.id,
            "device_id": record.device_id,
            "status": record.status,
            "issued_at": record.issued_at.isoformat() if record.issued_at else None,
            "expires_at": record.expires_at.isoformat() if record.expires_at else None,
            "last_seen_at": record.last_seen_at.isoformat() if record.last_seen_at else None,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _auth_response(
    ctx,
    request: Request,
    *,
    api_key: str | None = None,
    session_token: str | None = None,
    session_info: dict[str, Any] | None = None,
) -> dict:
    body = {
        "valid": True,
        "user_id": ctx.user_id,
        "user": user_payload(ctx),
        "plan": plan_payload(ctx),
        "credits": credits_payload(ctx, request),
        "key_info": key_info_payload(ctx),
        "sync_secret": ensure_user_sync_secret(ctx.user),
        "device": {
            "device_id": ctx.device_id,
            "status": "active",
        },
    }
    if api_key:
        body["api_key"] = api_key
    if session_token:
        body["session_token"] = session_token
    if session_info:
        body["session"] = session_info
    return body


@router.post("/register")
async def register(request: Request, payload: RegisterRequest) -> dict:
    identifier_type, identifier = _clean_identifier(payload)
    if identifier_type != "email":
        raise HTTPException(
            status_code=422,
            detail={"error": "email_required", "message": "Email OTP is available now. SMS OTP is not enabled yet."},
        )

    settings = getattr(request.app.state.container, "settings", None)
    _validate_supported_email(settings, identifier)
    email_service = getattr(request.app.state.container, "email_service", None)
    email_enabled = bool(getattr(email_service, "enabled", False))
    dev_otp_enabled = _dev_otp_enabled(settings)
    if not email_enabled and not dev_otp_enabled:
        raise HTTPException(
            status_code=503,
            detail={"error": "otp_email_not_configured", "message": "Email OTP is not configured on this server."},
        )

    await _consume_otp_register_quota(request, identifier_type, identifier)
    otp = f"{secrets.randbelow(1000000):06d}"
    session = get_session()
    try:
        _purge_expired_challenges(session)
        existing_account = _user_for_identifier(session, identifier_type, identifier) is not None
        if not payload.name.strip() and not existing_account:
            raise HTTPException(
                status_code=422,
                detail={"error": "name_required", "message": "Name is required for new accounts"},
            )
        _drop_existing_identifier_challenges(session, identifier_type, identifier)
        challenge = _create_auth_challenge(
            session,
            request,
            identifier_type=identifier_type,
            identifier=identifier,
            name=payload.name.strip(),
            plan_code=payload.plan_code,
            otp=otp,
            account_mode="login" if existing_account else "signup",
        )
        session.commit()
        challenge_id = str(challenge.challenge_id)
        account_mode = str(challenge.account_mode)
    except HTTPException:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    if email_enabled:
        try:
            await email_service.send_otp_email(
                recipient=identifier,
                otp=otp,
                ttl_seconds=OTP_TTL_SECONDS,
            )
        except EmailDeliveryError as exc:
            _mark_challenge_status(challenge_id, "email_failed")
            raise HTTPException(
                status_code=502,
                detail={"error": "otp_email_failed", "message": "Could not send OTP email. Try again shortly."},
            ) from exc

    response = {
        "ok": True,
        "challenge_id": challenge_id,
        "delivery": "email",
        "expires_in_seconds": OTP_TTL_SECONDS,
        "account_mode": account_mode,
    }
    if dev_otp_enabled:
        response["dev_otp"] = otp
    return response


@router.post("/verify-otp")
async def verify_otp(
    request: Request,
    payload: VerifyOtpRequest,
    x_eazyfill_device_id: str = Header(default="", alias="X-EazyFill-Device-Id"),
    x_flowpilot_device_id: str = Header(default="", alias="X-FlowPilot-Device-Id"),
) -> dict:
    session = get_session()
    try:
        _purge_expired_challenges(session)
        challenge = _load_pending_challenge(session, payload.challenge_id)
        now = _utcnow_naive()
        if not challenge:
            raise HTTPException(status_code=400, detail={"error": "otp_expired", "message": "OTP challenge expired"})
        if challenge.expires_at <= now:
            challenge.status = "expired"
            challenge.updated_at = now
            session.commit()
            raise HTTPException(status_code=400, detail={"error": "otp_expired", "message": "OTP challenge expired"})

        challenge.attempts = int(challenge.attempts or 0) + 1
        challenge.updated_at = now
        if challenge.attempts > 5:
            challenge.status = "failed"
            session.commit()
            raise HTTPException(status_code=429, detail={"error": "otp_attempts_exceeded", "message": "Too many OTP attempts"})

        if not secrets.compare_digest(str(challenge.otp_hash), _otp_hash(payload.otp)):
            session.commit()
            raise HTTPException(status_code=400, detail={"error": "invalid_otp", "message": "OTP is invalid"})

        user = _create_or_update_user(session, _challenge_payload(challenge))
        _ensure_subscription(session, user, str(challenge.plan_code or "free"))
        challenge.status = "consumed"
        challenge.consumed_at = now
        challenge.updated_at = now
        session.commit()
        user_id = int(user.id)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    key, plain_key = request.app.state.container.user_key_service.create_key(user_id)
    device_id = (
        x_eazyfill_device_id
        or x_flowpilot_device_id
        or request.headers.get("x-eazyfill-device-id", "")
        or request.headers.get("x-flowpilot-device-id", "")
        or "otp-device"
    )
    request.app.state.container.user_key_service.bind_device(
        int(key.id),
        device_id,
        device_name=payload.device_name,
        user_agent=request.headers.get("user-agent", ""),
    )
    session_token, session_info = _issue_user_session(
        request,
        user_id=user_id,
        api_key_id=int(key.id),
        device_id=device_id,
        device_name=payload.device_name or "EazyFill Extension",
    )
    ctx = await validate_v2_key(
        request,
        x_api_key=plain_key,
        x_eazyfill_device_id=device_id,
    )
    return _auth_response(ctx, request, api_key=plain_key, session_token=session_token, session_info=session_info)


@router.post("/verify-key")
async def verify_key(
    request: Request,
    payload: VerifyKeyRequest,
    x_eazyfill_device_id: str = Header(default="", alias="X-EazyFill-Device-Id"),
    x_flowpilot_device_id: str = Header(default="", alias="X-FlowPilot-Device-Id"),
) -> dict:
    ctx = await validate_v2_key(
        request,
        x_api_key=payload.api_key,
        x_eazyfill_device_id=x_eazyfill_device_id,
        x_flowpilot_device_id=x_flowpilot_device_id,
    )
    return _auth_response(ctx, request)


@router.post("/refresh")
async def refresh(
    request: Request,
    payload: RefreshRequest | None = None,
    x_api_key: str = Header(default="", alias="X-Api-Key"),
    x_eazyfill_device_id: str = Header(default="", alias="X-EazyFill-Device-Id"),
    x_flowpilot_device_id: str = Header(default="", alias="X-FlowPilot-Device-Id"),
) -> dict:
    api_key = (x_api_key or (payload.api_key if payload else "") or "").strip()
    ctx = await validate_v2_key(
        request,
        x_api_key=api_key,
        x_eazyfill_device_id=x_eazyfill_device_id,
        x_flowpilot_device_id=x_flowpilot_device_id,
    )
    return _auth_response(ctx, request)


@router.post("/logout")
async def logout() -> dict:
    return {"ok": True}
