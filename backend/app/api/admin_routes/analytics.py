from __future__ import annotations
import os
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse
from .utils import _admin_guard
from app.core.paths import get_project_root

router = APIRouter(tags=["admin-analytics"])

_PROJECT_ROOT = get_project_root()
_ADMIN_UI_INDEX = (_PROJECT_ROOT / "frontend" / "dist" / "index.html").resolve()

@router.get("/api/bootstrap")
async def admin_bootstrap(request: Request):
    """Minimal compatibility payload for the product admin UI."""
    denied = _admin_guard(request)
    if denied:
        return denied
    try:
        request.app.state.user_key_service.delete_revoked_keys()
    except Exception:
        pass
    return {
        "ok": True,
        "mode": "product-admin",
        "cloud_backup_configured": bool(os.getenv("BACKUP_CLOUD_UPLOAD_URL", "").strip()),
    }

@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    """Render main admin dashboard."""
    denied = _admin_guard(request)
    if denied:
        return denied
    if _ADMIN_UI_INDEX.exists():
        return FileResponse(str(_ADMIN_UI_INDEX))
    return HTMLResponse(content="<h1>Admin UI not built</h1>", status_code=404)


@router.get("/{full_path:path}", response_class=HTMLResponse)
async def admin_spa_fallback(request: Request, full_path: str):
    """Catch-all for SPA client-side routes — serve index.html."""
    denied = _admin_guard(request)
    if denied:
        return denied
    if _ADMIN_UI_INDEX.exists():
        return FileResponse(str(_ADMIN_UI_INDEX))
    return HTMLResponse(content="<h1>Admin UI not built</h1>", status_code=404)
