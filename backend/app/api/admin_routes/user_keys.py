"""Admin API — User key lifecycle (rotate, revoke, device reset)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse

from .utils import _admin_guard

router = APIRouter(tags=["admin-user-keys"])


@router.post("/api/users/{user_id}/key/create")
async def create_user_key(request: Request, user_id: int) -> Any:
    """Create an additional API key for a user's device."""
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    svc = request.app.state.user_key_service

    try:
        key, plain = svc.create_key(user_id=user_id)
        container.audit_service.log(
            actor_type="admin", action="user_key_created",
            target_type="user_api_key", target_id=key.id,
        )
        return JSONResponse({
            "ok": True,
            "key_id": key.id,
            "api_key": plain,
            "key_prefix": key.key_prefix_display,
            "expires_at": key.expires_at.isoformat() if key.expires_at else None,
        }, status_code=201)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/api/users/{user_id}/key/rotate")
async def rotate_user_key(request: Request, user_id: int) -> Any:
    """Rotate the user's key: revoke old, issue new."""
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    svc = request.app.state.user_key_service

    try:
        key, plain = svc.rotate_key(user_id=user_id)
        container.audit_service.log(
            actor_type="admin", action="user_key_rotated",
            target_type="user_api_key", target_id=key.id,
        )
        return JSONResponse({
            "ok": True,
            "key_id": key.id,
            "api_key": plain,
            "key_prefix": key.key_prefix_display,
            "key_version": key.key_version,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/api/users/{user_id}/key/revoke")
async def revoke_user_key(request: Request, user_id: int) -> Any:
    """Revoke the user's active key."""
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    svc = request.app.state.user_key_service

    key = svc.get_user_key(user_id)
    if not key:
        return JSONResponse({"error": "No active key found"}, status_code=404)

    svc.revoke_key(key.id, reason="admin_revoked")
    svc.delete_key(key.id)
    container.audit_service.log(
        actor_type="admin", action="user_key_revoked",
        target_type="user_api_key", target_id=key.id,
    )
    return JSONResponse({"ok": True})


@router.post("/api/users/{user_id}/key/reset-device")
async def reset_device_binding(request: Request, user_id: int) -> Any:
    """Reset device binding — allows key to be used on a new device."""
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    svc = request.app.state.user_key_service

    key = svc.get_user_key(user_id)
    if not key:
        return JSONResponse({"error": "No active key found"}, status_code=404)

    svc.reset_device_binding(key.id)
    container.audit_service.log(
        actor_type="admin", action="device_binding_reset",
        target_type="user_api_key", target_id=key.id,
    )
    return JSONResponse({"ok": True, "message": "Device binding reset — next request will bind new device"})


@router.get("/api/users/{user_id}/key")
async def get_user_key_info(request: Request, user_id: int) -> Any:
    """Get key info (prefix, status, version) — never returns plain key."""
    denied = _admin_guard(request)
    if denied:
        return denied
    svc = request.app.state.user_key_service

    key = svc.get_user_key(user_id)
    if not key:
        return JSONResponse({"has_key": False})
    return JSONResponse({
        "has_key": True,
        "key_id": key.id,
        "key_prefix": key.key_prefix_display,
        "status": key.status,
        "key_version": key.key_version,
        "issued_at": key.issued_at.isoformat() if key.issued_at else None,
        "expires_at": key.expires_at.isoformat() if key.expires_at else None,
    })


@router.get("/api/users/{user_id}/devices")
async def get_user_devices(request: Request, user_id: int) -> Any:
    """List devices bound to this user's key."""
    denied = _admin_guard(request)
    if denied:
        return denied
    svc = request.app.state.user_key_service

    devices = svc.get_user_devices(user_id)
    return JSONResponse({
        "devices": [
            {
                "id": d.id,
                "device_fingerprint": d.device_fingerprint[:20] + "...",
                "device_name": d.device_name,
                "user_agent": d.user_agent[:80] if d.user_agent else "",
                "status": d.status,
                "first_seen": d.first_seen_at.isoformat() if d.first_seen_at else None,
                "last_seen": d.last_seen_at.isoformat() if d.last_seen_at else None,
            }
            for d in devices
        ],
    })


@router.get("/api/user-keys")
async def list_all_user_keys(
    request: Request,
    status: str | None = Query("active"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> Any:
    """List all user-linked API keys across all users (for global key overview)."""
    denied = _admin_guard(request)
    if denied:
        return denied
    from app.core.models import UserApiKey, User
    from app.core.db import get_session
    session = get_session()
    try:
        q = session.query(UserApiKey)
        if status:
            q = q.filter(UserApiKey.status == status)
        total = q.count()
        keys = q.order_by(UserApiKey.issued_at.desc()).offset(offset).limit(limit).all()

        result = []
        for k in keys:
            user = session.query(User).filter(User.id == k.user_id).first()
            result.append({
                "id": k.id,
                "user_id": k.user_id,
                "user_name": user.full_name if user else "Unknown",
                "user_email": user.email if user else None,
                "user_mobile": user.mobile_number if user else None,
                "key_prefix": k.key_prefix_display,
                "status": k.status,
                "key_version": k.key_version,
                "issued_at": k.issued_at.isoformat() if k.issued_at else None,
                "expires_at": k.expires_at.isoformat() if k.expires_at else None,
                "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
                "usage_count": k.usage_count,
                "revoked_at": k.revoked_at.isoformat() if k.revoked_at else None,
            })
        return JSONResponse({
            "keys": result,
            "total": total,
            "offset": offset,
            "limit": limit,
        })
    finally:
        session.close()
