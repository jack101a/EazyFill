"""EazyFill v2 API key lifecycle endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.api.v2_routes.deps import V2AuthContext, validate_v2_key

router = APIRouter(prefix="/keys", tags=["v2-keys"])


class KeyCreateRequest(BaseModel):
    expiry_days: int | None = None


class KeyRevokeRequest(BaseModel):
    key_id: int
    reason: str = "user_revoked"


def _require_user(ctx: V2AuthContext) -> int:
    if not ctx.user_id:
        raise HTTPException(status_code=403, detail={"error": "user_account_required"})
    return int(ctx.user_id)


def _key_payload(key: Any) -> dict:
    return {
        "id": key.id,
        "user_id": key.user_id,
        "key_prefix_display": key.key_prefix_display,
        "status": key.status,
        "key_version": key.key_version,
        "issued_at": key.issued_at.isoformat() if key.issued_at else None,
        "expires_at": key.expires_at.isoformat() if key.expires_at else None,
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
        "usage_count": int(key.usage_count or 0),
        "revoked_at": key.revoked_at.isoformat() if key.revoked_at else None,
    }


@router.get("/list")
async def list_keys(request: Request, ctx: V2AuthContext = Depends(validate_v2_key)) -> dict:
    user_id = _require_user(ctx)
    keys = request.app.state.container.user_key_service.list_user_keys(user_id)
    return {"items": [_key_payload(key) for key in keys]}


@router.post("/create")
async def create_key(
    request: Request,
    payload: KeyCreateRequest,
    ctx: V2AuthContext = Depends(validate_v2_key),
) -> dict:
    user_id = _require_user(ctx)
    key, plain = request.app.state.container.user_key_service.create_key(
        user_id=user_id,
        expiry_days=payload.expiry_days,
    )
    return {"ok": True, "api_key": plain, "key": _key_payload(key)}


@router.post("/rotate")
async def rotate_key(request: Request, ctx: V2AuthContext = Depends(validate_v2_key)) -> dict:
    user_id = _require_user(ctx)
    key, plain = request.app.state.container.user_key_service.rotate_key(user_id=user_id)
    return {"ok": True, "api_key": plain, "key": _key_payload(key)}


@router.post("/revoke")
async def revoke_key(
    request: Request,
    payload: KeyRevokeRequest,
    ctx: V2AuthContext = Depends(validate_v2_key),
) -> dict:
    user_id = _require_user(ctx)
    revoked = request.app.state.container.user_key_service.revoke_user_key(
        user_id=user_id,
        key_id=payload.key_id,
        reason=payload.reason,
    )
    if not revoked:
        raise HTTPException(status_code=404, detail={"error": "key_not_found"})
    return {"ok": True, "key": _key_payload(revoked)}
