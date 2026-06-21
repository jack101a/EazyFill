"""EazyFill v2 device management endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.api.v2_routes.deps import V2AuthContext, validate_v2_key

router = APIRouter(prefix="/devices", tags=["v2-devices"])


class DeviceRegisterRequest(BaseModel):
    device_id: str | None = None
    device_name: str = ""


def _require_user(ctx: V2AuthContext) -> int:
    if not ctx.user_id:
        raise HTTPException(status_code=403, detail={"error": "user_account_required"})
    return int(ctx.user_id)


def _device_payload(device: Any) -> dict:
    return {
        "id": device.id,
        "api_key_id": device.api_key_id,
        "device_fingerprint": device.device_fingerprint,
        "device_name": device.device_name or "",
        "user_agent": device.user_agent or "",
        "status": device.status,
        "first_seen_at": device.first_seen_at.isoformat() if device.first_seen_at else None,
        "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
    }


@router.get("/list")
async def list_devices(request: Request, ctx: V2AuthContext = Depends(validate_v2_key)) -> dict:
    user_id = _require_user(ctx)
    devices = request.app.state.container.user_key_service.get_user_devices(user_id)
    return {"items": [_device_payload(device) for device in devices]}


@router.post("/register")
async def register_device(
    request: Request,
    payload: DeviceRegisterRequest,
    ctx: V2AuthContext = Depends(validate_v2_key),
) -> dict:
    _require_user(ctx)
    device_id = str(payload.device_id or ctx.device_id or "").strip()
    if not device_id:
        raise HTTPException(status_code=400, detail={"error": "device_id_required"})
    device = request.app.state.container.user_key_service.bind_device(
        api_key_id=ctx.key_id,
        device_fingerprint=device_id,
        device_name=payload.device_name,
        user_agent=request.headers.get("user-agent", ""),
    )
    if device is None:
        raise HTTPException(status_code=403, detail={"error": "device_limit_reached"})
    return {"ok": True, "device": _device_payload(device)}


@router.delete("/{device_id}")
async def delete_device(
    request: Request,
    device_id: int,
    ctx: V2AuthContext = Depends(validate_v2_key),
) -> dict:
    user_id = _require_user(ctx)
    deleted = request.app.state.container.user_key_service.remove_user_device(user_id, device_id)
    if not deleted:
        raise HTTPException(status_code=404, detail={"error": "device_not_found"})
    return {"ok": True, "deleted": True}
