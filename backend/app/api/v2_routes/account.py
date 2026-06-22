"""Account-first EazyFill authentication endpoints."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field

from app.api.v2_routes.deps import credits_payload, ensure_user_sync_secret, key_info_payload, plan_payload, user_payload, validate_v2_key
from app.services.account_auth_service import AccountAuthService

router = APIRouter(prefix="/account", tags=["v2-account"])
account_auth_service = AccountAuthService()
logger = logging.getLogger(__name__)
LOGOUT_TIMEOUT_SECONDS = 3.0


class AccountStartRequest(BaseModel):
    email: str = Field(default="", max_length=255)
    identifier: str = Field(default="", max_length=255)
    plan_code: str = Field(default="free", max_length=64)


class AccountProfileRequest(BaseModel):
    email: str = Field(default="", max_length=255)
    identifier: str = Field(default="", max_length=255)
    name: str = Field(default="", max_length=255)
    plan_code: str = Field(default="free", max_length=64)


class AccountVerifyRequest(BaseModel):
    challenge_id: str = Field(min_length=8)
    otp: str = Field(min_length=4, max_length=12)
    device_name: str = Field(default="", max_length=255)


def _identifier(payload: AccountStartRequest | AccountProfileRequest) -> str:
    return (payload.email or payload.identifier or "").strip()


def _account_response(
    ctx,
    request: Request,
    *,
    session_token: str | None = None,
    session_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plan = plan_payload(ctx)
    body = {
        "ok": True,
        "valid": True,
        "user_id": ctx.user_id,
        "user": user_payload(ctx),
        "plan": plan,
        "entitlements": plan.get("features", {}),
        "credits": credits_payload(ctx, request),
        "key_info": key_info_payload(ctx),
        "sync_secret": ensure_user_sync_secret(ctx.user),
        "device": {
            "device_id": ctx.device_id,
            "status": "active",
        },
    }
    if session_token:
        body["session_token"] = session_token
    if session_info:
        body["session"] = session_info
    return body


@router.post("/start")
async def start(request: Request, payload: AccountStartRequest) -> dict[str, Any]:
    return await account_auth_service.start(
        request,
        email=_identifier(payload),
        plan_code=payload.plan_code,
    )


@router.post("/profile")
async def profile(request: Request, payload: AccountProfileRequest) -> dict[str, Any]:
    return await account_auth_service.profile(
        request,
        email=_identifier(payload),
        name=payload.name,
        plan_code=payload.plan_code,
    )


@router.post("/verify")
async def verify(
    request: Request,
    payload: AccountVerifyRequest,
    x_eazyfill_device_id: str = Header(default="", alias="X-EazyFill-Device-Id"),
    x_flowpilot_device_id: str = Header(default="", alias="X-FlowPilot-Device-Id"),
) -> dict[str, Any]:
    result = account_auth_service.verify(
        request,
        challenge_id=payload.challenge_id,
        otp=payload.otp,
        device_id=x_eazyfill_device_id or x_flowpilot_device_id,
        device_name=payload.device_name,
    )
    ctx = await validate_v2_key(
        request,
        x_eazyfill_session=result.session_token,
        x_eazyfill_device_id=result.device_id,
    )
    return _account_response(
        ctx,
        request,
        session_token=result.session_token,
        session_info=result.session_info,
    )


@router.post("/refresh")
async def refresh(
    request: Request,
    x_api_key: str = Header(default="", alias="X-Api-Key"),
    x_eazyfill_session: str = Header(default="", alias="X-EazyFill-Session"),
    x_eazyfill_device_id: str = Header(default="", alias="X-EazyFill-Device-Id"),
    x_flowpilot_device_id: str = Header(default="", alias="X-FlowPilot-Device-Id"),
) -> dict[str, Any]:
    ctx = await validate_v2_key(
        request,
        x_api_key=x_api_key,
        x_eazyfill_session=x_eazyfill_session,
        x_eazyfill_device_id=x_eazyfill_device_id or x_flowpilot_device_id,
    )
    return _account_response(ctx, request)


@router.post("/logout")
async def logout(
    request: Request,
    x_eazyfill_session: str = Header(default="", alias="X-EazyFill-Session"),
) -> dict[str, Any]:
    token = str(x_eazyfill_session or "").strip()
    auth_header = request.headers.get("authorization", "").strip()
    if not token and auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
    revoked = False
    if token:
        try:
            revoked = await asyncio.wait_for(
                asyncio.to_thread(account_auth_service.logout, token),
                timeout=LOGOUT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("account_logout_revoke_timed_out")
        except Exception as exc:
            logger.warning(
                "account_logout_revoke_failed",
                extra={"context": {"error_type": type(exc).__name__}},
            )
    return {"ok": True, "revoked": bool(revoked)}
