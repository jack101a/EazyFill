"""EazyFill v2 encrypted sync endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.v2_routes.deps import V2AuthContext, validate_v2_key
from app.core.db import get_session
from app.core.models import AuthChallenge
from app.services.account_auth_service import AccountAuthService
from app.services.sync_service import SyncBlobTooLargeError, SyncConflictError, SyncIntegrityError

router = APIRouter(prefix="/sync", tags=["v2-sync"])
account_auth_service = AccountAuthService()


class SyncPushRequest(BaseModel):
    device_id: str | None = None
    sync_version: int = Field(default=1, ge=1)
    encrypted_blob: str
    blob_hash: str


class SyncDeleteConfirmRequest(BaseModel):
    challenge_id: str = Field(min_length=8)
    otp: str = Field(min_length=4, max_length=12)


def _sync_allowed(ctx: V2AuthContext) -> bool:
    if not ctx.user_id or not ctx.plan:
        return False
    return bool((ctx.plan.allowed_services or {}).get("sync", False))


def _max_blob_bytes(ctx: V2AuthContext) -> int:
    entitlements = ctx.plan.allowed_services if ctx.plan else {}
    configured_mb = entitlements.get("sync_storage_mb") if entitlements else None
    if configured_mb:
        return max(1, int(configured_mb)) * 1024 * 1024
    if ctx.plan and str(ctx.plan.code or "").lower() in {"pro", "team", "enterprise"}:
        return 50 * 1024 * 1024
    return 10 * 1024 * 1024


def _require_sync(ctx: V2AuthContext) -> None:
    if not _sync_allowed(ctx):
        raise HTTPException(status_code=403, detail={"error": "sync_not_available", "message": "Cloud sync is not enabled for this key"})


def _sync_delete_email(ctx: V2AuthContext) -> str:
    email = str(getattr(ctx.user, "email", "") or "").strip().lower()
    if not email:
        raise HTTPException(
            status_code=409,
            detail={"error": "email_required", "message": "Add a verified email before deleting the cloud copy."},
        )
    return email


def _sync_delete_challenge_belongs_to_user(challenge_id: str, ctx: V2AuthContext) -> bool:
    email = _sync_delete_email(ctx)
    session = get_session()
    try:
        challenge = (
            session.query(AuthChallenge)
            .filter(AuthChallenge.challenge_id == challenge_id)
            .first()
        )
        return bool(
            challenge
            and challenge.identifier_type == "email"
            and str(challenge.identifier or "").strip().lower() == email
            and str(challenge.account_mode or "") == "sync_delete"
        )
    finally:
        session.close()


@router.post("/push")
async def push_sync(
    request: Request,
    payload: SyncPushRequest,
    ctx: V2AuthContext = Depends(validate_v2_key),
) -> dict:
    _require_sync(ctx)
    try:
        result = request.app.state.container.sync_service.push_blob(
            int(ctx.user_id),
            device_id=(payload.device_id or ctx.device_id),
            sync_version=payload.sync_version,
            encrypted_blob_base64=payload.encrypted_blob,
            blob_hash=payload.blob_hash,
            max_blob_bytes=_max_blob_bytes(ctx),
        )
        return {"ok": True, **result}
    except SyncConflictError as exc:
        raise HTTPException(status_code=409, detail={"error": "sync_conflict", "current_version": exc.current_version}) from exc
    except SyncBlobTooLargeError as exc:
        raise HTTPException(status_code=413, detail={"error": "blob_too_large", "message": str(exc)}) from exc
    except SyncIntegrityError as exc:
        raise HTTPException(status_code=400, detail={"error": "invalid_sync_blob", "message": str(exc)}) from exc


@router.get("/pull")
async def pull_sync(request: Request, ctx: V2AuthContext = Depends(validate_v2_key)) -> dict:
    _require_sync(ctx)
    return request.app.state.container.sync_service.pull_blob(int(ctx.user_id))


@router.get("/status")
async def sync_status(request: Request, ctx: V2AuthContext = Depends(validate_v2_key)) -> dict:
    _require_sync(ctx)
    return request.app.state.container.sync_service.status(int(ctx.user_id))


@router.delete("/delete")
async def delete_sync(request: Request, ctx: V2AuthContext = Depends(validate_v2_key)) -> dict:
    _require_sync(ctx)
    raise HTTPException(
        status_code=403,
        detail={
            "error": "otp_required",
            "message": "Email OTP is required before deleting your cloud copy.",
        },
    )


@router.post("/delete/request-otp")
async def request_delete_sync_otp(request: Request, ctx: V2AuthContext = Depends(validate_v2_key)) -> dict:
    _require_sync(ctx)
    email = _sync_delete_email(ctx)
    return await account_auth_service.send_action_otp(
        request,
        email=email,
        name=str(getattr(ctx.user, "full_name", "") or ""),
        plan_code=str(getattr(ctx.plan, "code", "") or "free"),
        account_mode="sync_delete",
    )


@router.post("/delete/confirm")
async def confirm_delete_sync(
    request: Request,
    payload: SyncDeleteConfirmRequest,
    ctx: V2AuthContext = Depends(validate_v2_key),
) -> dict:
    _require_sync(ctx)
    email = _sync_delete_email(ctx)
    if not _sync_delete_challenge_belongs_to_user(payload.challenge_id, ctx):
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_otp_challenge", "message": "OTP challenge is not valid for this account."},
        )
    account_auth_service.verify_action_otp(
        challenge_id=payload.challenge_id,
        otp=payload.otp,
        account_mode="sync_delete",
        email=email,
    )
    deleted = request.app.state.container.sync_service.delete_blob(int(ctx.user_id))
    return {"ok": True, **deleted}
