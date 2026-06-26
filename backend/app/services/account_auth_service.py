"""Account-first email OTP authentication for EazyFill."""

from __future__ import annotations

import hashlib
import logging
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import or_, text

from app.core.config import DEFAULT_OTP_ALLOWED_EMAIL_DOMAINS, DEFAULT_OTP_BLOCKED_EMAIL_DOMAINS
from app.core.db import get_session
from app.core.models import AuthChallenge, SubscriptionPlan, User, UserIdentity, UserSession, UserSubscription
from app.services.email_service import EmailDeliveryError

logger = logging.getLogger(__name__)

OTP_TTL_SECONDS = 10 * 60
OTP_REGISTER_WINDOW_SECONDS = 5 * 60
OTP_REGISTER_MAX_PER_IDENTIFIER = 3
OTP_REGISTER_MAX_PER_CLIENT = 12
SESSION_TTL_DAYS = 90
_OTP_REGISTER_EVENTS: dict[str, list[float]] = {}

SUPPORTED_EMAIL_MESSAGE = (
    "Use a supported personal email provider such as Gmail, Outlook, Hotmail, "
    "Proton Mail, Rediffmail, Yahoo, iCloud, Zoho, or Fastmail."
)


@dataclass
class AccountChallengeResult:
    challenge_id: str
    account_mode: str
    delivery: str
    expires_in_seconds: int = OTP_TTL_SECONDS
    dev_otp: str = ""


@dataclass
class AccountVerifyResult:
    user_id: int
    session_token: str
    session_info: dict[str, Any]
    device_id: str


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


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


def _clean_email(email: str) -> str:
    clean = str(email or "").strip().lower()
    _email_domain(clean)
    return clean


def _otp_hash(otp: str) -> str:
    return hashlib.sha256(str(otp).encode("utf-8")).hexdigest()


def _session_hash(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def _apply_logout_statement_timeout(session, milliseconds: int = 2500) -> None:
    try:
        bind = session.get_bind()
        if bind.dialect.name == "postgresql":
            session.execute(text(f"SET LOCAL statement_timeout = '{int(milliseconds)}ms'"))
    except Exception as exc:
        logger.debug(
            "account_logout_statement_timeout_not_applied",
            extra={"context": {"error_type": type(exc).__name__}},
        )


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    if forwarded:
        return f"ip:{forwarded}"
    if request.client and request.client.host:
        return f"ip:{request.client.host}"
    return "ip:unknown"


def _client_ip(request: Request) -> str:
    return _client_key(request).removeprefix("ip:")[:45]


def _device_id(request: Request, explicit: str = "") -> str:
    value = (
        str(explicit or "").strip()
        or request.headers.get("x-eazyfill-device-id", "").strip()
        or request.headers.get("x-flowpilot-device-id", "").strip()
        or request.headers.get("x-device-id", "").strip()
        or request.headers.get("x-client-device-id", "").strip()
    )
    if value:
        return value
    ua = request.headers.get("user-agent", "").strip()
    return f"ua:{ua[:180]}" if ua else "ua:unknown"


def _raise_otp_rate_limited() -> None:
    raise HTTPException(
        status_code=429,
        detail={
            "error": "otp_rate_limited",
            "message": "Too many verification code requests. Try again shortly.",
            "retry_after_seconds": OTP_REGISTER_WINDOW_SECONDS,
        },
    )


def _consume_otp_register_quota_memory(request: Request, identifier: str) -> None:
    now = time.time()
    cutoff = now - OTP_REGISTER_WINDOW_SECONDS
    scopes = [
        (f"identifier:email:{identifier}", OTP_REGISTER_MAX_PER_IDENTIFIER),
        (_client_key(request), OTP_REGISTER_MAX_PER_CLIENT),
    ]
    for scope, _limit in scopes:
        _OTP_REGISTER_EVENTS[scope] = [ts for ts in _OTP_REGISTER_EVENTS.get(scope, []) if ts >= cutoff]
    for scope, limit in scopes:
        if len(_OTP_REGISTER_EVENTS.get(scope, [])) >= limit:
            _raise_otp_rate_limited()
    for scope, _limit in scopes:
        _OTP_REGISTER_EVENTS.setdefault(scope, []).append(now)


async def _consume_otp_register_quota(request: Request, identifier: str) -> None:
    container = getattr(request.app.state, "container", None)
    limiter = getattr(container, "rate_limiter", None)
    if limiter and hasattr(limiter, "check"):
        try:
            client_allowed = await limiter.check(
                "account_otp_client",
                _client_key(request),
                OTP_REGISTER_MAX_PER_CLIENT,
                OTP_REGISTER_WINDOW_SECONDS,
            )
            identifier_allowed = await limiter.check(
                "account_otp_identifier",
                f"email:{identifier}",
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
                "account_otp_rate_limiter_failed_fallback_memory",
                extra={"context": {"error_type": type(exc).__name__}},
            )
    _consume_otp_register_quota_memory(request, identifier)


def _dev_otp_enabled(settings: Any) -> bool:
    if not getattr(getattr(settings, "server", None), "debug", False):
        return False
    email_config = getattr(settings, "email", None)
    return bool(getattr(email_config, "otp_dev_otp_enabled", False))


def _purge_expired_challenges(session) -> None:
    now = _utcnow()
    (
        session.query(AuthChallenge)
        .filter(AuthChallenge.status == "pending", AuthChallenge.expires_at <= now)
        .update({"status": "expired", "updated_at": now}, synchronize_session=False)
    )


def _drop_existing_identifier_challenges(session, email: str) -> None:
    now = _utcnow()
    (
        session.query(AuthChallenge)
        .filter(
            AuthChallenge.identifier_type == "email",
            AuthChallenge.identifier == email,
            AuthChallenge.status == "pending",
        )
        .update({"status": "replaced", "updated_at": now}, synchronize_session=False)
    )


def _find_user_by_email(session, email: str) -> User | None:
    existing = session.query(User).filter(User.email == email).first()
    if existing:
        return existing
    identity = (
        session.query(UserIdentity)
        .filter(UserIdentity.identity_type == "email", UserIdentity.identifier == email)
        .first()
    )
    if identity:
        return session.query(User).filter(User.id == identity.user_id).first()
    eazyfill_token = f"eazyfill_email:{email}"
    flowpilot_token = f"flowpilot_email:{email}"
    return session.query(User).filter(or_(
        User.notes.like(f"%{eazyfill_token}%"),
        User.notes.like(f"%{flowpilot_token}%"),
    )).first()


def _ensure_user_identity(session, user: User, email: str) -> UserIdentity:
    now = _utcnow()
    identity = (
        session.query(UserIdentity)
        .filter(UserIdentity.identity_type == "email", UserIdentity.identifier == email)
        .first()
    )
    if identity:
        identity.user_id = user.id
        identity.provider = identity.provider or "email"
        identity.is_primary = True
        identity.verified_at = identity.verified_at or now
        identity.updated_at = now
        return identity
    identity = UserIdentity(
        user_id=user.id,
        identity_type="email",
        identifier=email,
        provider="email",
        is_primary=True,
        verified_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(identity)
    session.flush()
    return identity


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


def _create_or_update_user(session, challenge: AuthChallenge) -> User:
    now = _utcnow()
    email = str(challenge.identifier or "").strip().lower()
    name = str(challenge.name or "").strip()
    user = _find_user_by_email(session, email)
    if user:
        user.email = email
        user.email_verified_at = now
        if name:
            user.full_name = name
        if user.status not in {"blocked", "active"}:
            user.status = "active"
        user.last_login_at = now
        user.updated_at = now
        _ensure_user_identity(session, user, email)
        return user

    user = User(
        full_name=name or "EazyFill User",
        email=email,
        status="active",
        notes="",
        email_verified_at=now,
        last_login_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    session.flush()
    _ensure_user_identity(session, user, email)
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


async def _send_otp(request: Request, email: str, otp: str) -> None:
    email_service = getattr(request.app.state.container, "email_service", None)
    email_enabled = bool(getattr(email_service, "enabled", False))
    dev_otp_enabled = _dev_otp_enabled(getattr(request.app.state.container, "settings", None))
    if not email_enabled and not dev_otp_enabled:
        raise HTTPException(
            status_code=503,
            detail={"error": "otp_email_not_configured", "message": "Email OTP is not configured on this server."},
        )
    if email_enabled:
        await email_service.send_otp_email(recipient=email, otp=otp, ttl_seconds=OTP_TTL_SECONDS)


def _create_challenge(
    session,
    request: Request,
    *,
    email: str,
    name: str,
    plan_code: str,
    otp: str,
    account_mode: str,
) -> AuthChallenge:
    now = _utcnow()
    challenge = AuthChallenge(
        challenge_id=secrets.token_urlsafe(24),
        identifier_type="email",
        identifier=email,
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


def _issue_session(
    request: Request,
    *,
    user_id: int,
    device_id: str,
    device_name: str,
) -> tuple[str, dict[str, Any]]:
    token = f"efs_{secrets.token_urlsafe(32)}"
    now = _utcnow()
    expires_at = now + timedelta(days=SESSION_TTL_DAYS)
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
            api_key_id=None,
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


class AccountAuthService:
    async def start(self, request: Request, *, email: str, plan_code: str = "free") -> dict[str, Any]:
        clean = _clean_email(email)
        settings = getattr(request.app.state.container, "settings", None)
        _validate_supported_email(settings, clean)
        session = get_session()
        try:
            _purge_expired_challenges(session)
            existing = _find_user_by_email(session, clean)
            if not existing:
                return {
                    "ok": True,
                    "next_step": "profile",
                    "account_mode": "signup",
                    "email": clean,
                    "profile_required": True,
                }
        finally:
            session.close()
        return await self._send_challenge(
            request,
            email=clean,
            name="",
            plan_code=plan_code,
            account_mode="login",
        )

    async def profile(self, request: Request, *, email: str, name: str, plan_code: str = "free") -> dict[str, Any]:
        clean = _clean_email(email)
        settings = getattr(request.app.state.container, "settings", None)
        _validate_supported_email(settings, clean)
        display_name = str(name or "").strip()
        if not display_name:
            raise HTTPException(status_code=422, detail={"error": "name_required", "message": "Name is required"})
        session = get_session()
        try:
            existing = _find_user_by_email(session, clean) is not None
        finally:
            session.close()
        return await self._send_challenge(
            request,
            email=clean,
            name=display_name,
            plan_code=plan_code,
            account_mode="login" if existing else "signup",
        )

    async def send_action_otp(
        self,
        request: Request,
        *,
        email: str,
        account_mode: str,
        name: str = "",
        plan_code: str = "free",
    ) -> dict[str, Any]:
        clean = _clean_email(email)
        settings = getattr(request.app.state.container, "settings", None)
        _validate_supported_email(settings, clean)
        return await self._send_challenge(
            request,
            email=clean,
            name=name,
            plan_code=plan_code,
            account_mode=account_mode,
        )

    async def _send_challenge(
        self,
        request: Request,
        *,
        email: str,
        name: str,
        plan_code: str,
        account_mode: str,
    ) -> dict[str, Any]:
        await _consume_otp_register_quota(request, email)
        otp = f"{secrets.randbelow(1000000):06d}"
        session = get_session()
        try:
            _purge_expired_challenges(session)
            _drop_existing_identifier_challenges(session, email)
            challenge = _create_challenge(
                session,
                request,
                email=email,
                name=name,
                plan_code=plan_code,
                otp=otp,
                account_mode=account_mode,
            )
            session.commit()
            challenge_id = str(challenge.challenge_id)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
        try:
            await _send_otp(request, email, otp)
        except EmailDeliveryError as exc:
            self.mark_challenge_status(challenge_id, "email_failed")
            raise HTTPException(
                status_code=502,
                detail={"error": "otp_email_failed", "message": "Could not send OTP email. Try again shortly."},
            ) from exc

        response = {
            "ok": True,
            "next_step": "verify",
            "challenge_id": challenge_id,
            "delivery": "email",
            "expires_in_seconds": OTP_TTL_SECONDS,
            "account_mode": account_mode,
            "email": email,
        }
        if _dev_otp_enabled(getattr(request.app.state.container, "settings", None)):
            response["dev_otp"] = otp
        return response

    def mark_challenge_status(self, challenge_id: str, status: str) -> None:
        session = get_session()
        try:
            now = _utcnow()
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

    def verify_action_otp(
        self,
        *,
        challenge_id: str,
        otp: str,
        account_mode: str,
        email: str,
    ) -> dict[str, Any]:
        clean_email = _clean_email(email)
        session = get_session()
        try:
            _purge_expired_challenges(session)
            challenge = _load_pending_challenge(session, challenge_id)
            now = _utcnow()
            if not challenge:
                raise HTTPException(status_code=400, detail={"error": "otp_expired", "message": "OTP challenge expired"})
            if challenge.expires_at <= now:
                challenge.status = "expired"
                challenge.updated_at = now
                session.commit()
                raise HTTPException(status_code=400, detail={"error": "otp_expired", "message": "OTP challenge expired"})
            if (
                str(challenge.account_mode or "") != str(account_mode or "")
                or str(challenge.identifier_type or "") != "email"
                or str(challenge.identifier or "").strip().lower() != clean_email
            ):
                raise HTTPException(
                    status_code=400,
                    detail={"error": "invalid_otp_challenge", "message": "OTP challenge is not valid for this action."},
                )
            challenge.attempts = int(challenge.attempts or 0) + 1
            challenge.updated_at = now
            if challenge.attempts > 5:
                challenge.status = "failed"
                session.commit()
                raise HTTPException(status_code=429, detail={"error": "otp_attempts_exceeded", "message": "Too many OTP attempts"})
            if not secrets.compare_digest(str(challenge.otp_hash), _otp_hash(otp)):
                session.commit()
                raise HTTPException(status_code=400, detail={"error": "invalid_otp", "message": "OTP is invalid"})
            challenge.status = "consumed"
            challenge.consumed_at = now
            challenge.updated_at = now
            session.commit()
            return {"ok": True, "challenge_id": str(challenge.challenge_id), "email": clean_email}
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def verify(
        self,
        request: Request,
        *,
        challenge_id: str,
        otp: str,
        device_id: str = "",
        device_name: str = "",
    ) -> AccountVerifyResult:
        session = get_session()
        try:
            _purge_expired_challenges(session)
            challenge = _load_pending_challenge(session, challenge_id)
            now = _utcnow()
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
            if not secrets.compare_digest(str(challenge.otp_hash), _otp_hash(otp)):
                session.commit()
                raise HTTPException(status_code=400, detail={"error": "invalid_otp", "message": "OTP is invalid"})
            user = _create_or_update_user(session, challenge)
            if user.status == "blocked":
                raise HTTPException(status_code=403, detail={"error": "account_blocked", "message": "Account access is not allowed"})
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

        resolved_device_id = _device_id(request, device_id)
        token, session_info = _issue_session(
            request,
            user_id=user_id,
            device_id=resolved_device_id,
            device_name=device_name or "EazyFill Extension",
        )
        return AccountVerifyResult(
            user_id=user_id,
            session_token=token,
            session_info=session_info,
            device_id=resolved_device_id,
        )

    def logout(self, session_token: str) -> bool:
        clean = str(session_token or "").strip()
        if not clean:
            return False
        session = get_session()
        try:
            now = _utcnow()
            _apply_logout_statement_timeout(session)
            updated = (
                session.query(UserSession)
                .filter(UserSession.session_hash == _session_hash(clean), UserSession.status == "active")
                .update(
                    {
                        "status": "revoked",
                        "revoked_at": now,
                        "revoke_reason": "logout",
                        "last_seen_at": now,
                    },
                    synchronize_session=False,
                )
            )
            session.commit()
            return bool(updated)
        except Exception as exc:
            session.rollback()
            logger.warning(
                "account_logout_revoke_db_failed",
                extra={"context": {"error_type": type(exc).__name__}},
            )
            return False
        finally:
            session.close()
