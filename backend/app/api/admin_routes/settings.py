from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from .utils import _admin_guard, _write_auto_backup

router = APIRouter(tags=["admin-settings"])


@router.post("/access")
async def update_access(request: Request, global_access: str = Form(None), new_domain: str = Form(None)):
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    container.db.set_global_access(global_access == "on")
    if new_domain and new_domain.strip():
        container.db.add_allowed_domain(new_domain.strip())
    _write_auto_backup(container, "update_access")
    return RedirectResponse(url="/admin/", status_code=303)


@router.post("/access/remove")
async def remove_domain(request: Request, domain: str = Form(...)):
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    container.db.remove_allowed_domain(domain)
    _write_auto_backup(container, "remove_domain")
    return RedirectResponse(url="/admin/", status_code=303)


@router.get("/api/settings")
async def get_settings(request: Request):
    denied = _admin_guard(request)
    if denied:
        return denied
    settings_list = request.app.state.container.db.get_all_settings()
    return {
        "settings": [
            {
                **dict(setting),
                "value_display": dict(setting).get("value", ""),
                "is_secret": False,
            }
            for setting in settings_list
        ]
    }


@router.get("/api/settings/{key:path}")
async def get_setting(request: Request, key: str):
    denied = _admin_guard(request)
    if denied:
        return denied
    value = request.app.state.container.db.get_setting(key)
    return {"key": key, "value": value or ""}


class SettingPayload(BaseModel):
    key: str
    value: str


@router.post("/api/settings")
async def save_setting(
    request: Request,
    key: str = Form(None),
    value: str = Form(None),
):
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container

    if key is None:
        try:
            body = await request.json()
            key = body.get("key", "")
            value = body.get("value", "")
        except Exception as exc:
            raise HTTPException(400, "key is required (form or JSON)") from exc

    key = key.strip()
    value = (value or "").strip()
    if not key:
        raise HTTPException(400, "key is required")
    container.db.set_setting(key, value)
    return {"ok": True, "key": key, "saved": True}


@router.post("/api/settings/bulk")
async def save_settings_bulk(request: Request):
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    try:
        body = await request.json()
        settings_dict = body.get("settings", {})
    except Exception as exc:
        raise HTTPException(400, "Invalid JSON body") from exc
    if not isinstance(settings_dict, dict):
        raise HTTPException(400, "settings must be an object")
    saved = []
    for key, value in settings_dict.items():
        normalized_key = str(key).strip()
        normalized_value = str(value).strip()
        if normalized_key:
            container.db.set_setting(normalized_key, normalized_value)
            saved.append(normalized_key)
    return {"ok": True, "saved_keys": saved}
