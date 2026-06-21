"""Admin API key management routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .utils import _admin_guard


router = APIRouter(tags=["admin-keys"])


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


@router.post("/api/master-key/enabled")
async def set_master_key_enabled(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied

    payload = await request.json()
    enabled = _as_bool(payload.get("enabled") if isinstance(payload, dict) else payload)
    master_key = request.app.state.container.db.set_master_key_enabled(enabled)
    if not master_key:
        return JSONResponse({"error": "master key not available"}, status_code=404)
    return JSONResponse({"ok": True, "master_key": master_key})


@router.post("/api/keys/create")
async def create_api_key(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied

    form = await request.form()
    key_name = str(form.get("key_name") or form.get("name") or "Admin API Key").strip()
    key_type = str(form.get("key_type") or "user").strip().lower() or "user"
    try:
        expiry_days = int(str(form.get("expiry_days") or "0").strip() or "0")
    except ValueError:
        return JSONResponse({"error": "expiry_days must be an integer"}, status_code=400)

    key_id, plain_key, expires_at = request.app.state.container.key_service.create_key(
        name=key_name,
        expiry_days=expiry_days,
        key_type=key_type,
    )
    return JSONResponse(
        {
            "ok": True,
            "key_id": key_id,
            "api_key": plain_key,
            "expires_at": expires_at,
            "key_type": key_type,
        },
        status_code=201,
    )
