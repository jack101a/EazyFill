"""Admin API — System operations (backup, restore, usage, health)."""

from __future__ import annotations

from typing import Any

import json
import os, signal, subprocess, sys, shlex
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.services.readiness_service import readiness_payload

from .utils import _admin_guard

router = APIRouter(tags=["admin-system"])


# ── Backup ─────────────────────────────────────────────────────────────────

@router.get("/api/system/backups")
async def list_backups(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    svc = container.backup_service
    return JSONResponse({"backups": svc.list_backups()})


@router.post("/api/system/backup")
async def create_backup(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    svc = container.backup_service
    result = svc.full_backup()
    return JSONResponse(result)


@router.post("/api/system/restore/{backup_id}")
async def restore_backup(request: Request, backup_id: str) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    svc = container.backup_service
    result = svc.restore_from_backup(backup_id)
    return JSONResponse(result)


@router.get("/api/system/backup-health")
async def backup_health(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    svc = container.backup_service
    return JSONResponse(svc.get_backup_health())


# ── Usage / Quota ──────────────────────────────────────────────────────────

@router.get("/api/users/{user_id}/usage")
async def get_user_usage(request: Request, user_id: int) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    usage = container.usage_cycle_service.get_user_usage(user_id)
    return JSONResponse(usage)


@router.post("/api/users/{user_id}/usage/reset")
async def reset_user_cycle(request: Request, user_id: int) -> Any:
    """Admin override: reset the current usage cycle (grant bonus quota)."""
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    cycle = container.usage_cycle_service.reset_cycle(user_id)
    if not cycle:
        return JSONResponse({"error": "Failed to reset cycle"}, status_code=400)
    container.audit_service.log(
        actor_type="admin", action="usage_cycle_reset",
        target_type="user", target_id=user_id,
    )
    return JSONResponse({"ok": True, "new_cycle_id": cycle.id})


# ── System Health ──────────────────────────────────────────────────────────

@router.get("/api/system/health")
async def system_health(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container

    # Count totals
    from app.core.db import get_session
    from app.core.models import User, PaymentRecord, UserSubscription

    session = get_session()
    orm_stats = {"available": True, "error": ""}
    try:
        total_users = session.query(User).count()
        active_users = session.query(User).filter(User.status == "active").count()
        pending_payments = session.query(PaymentRecord).filter(
            PaymentRecord.status.in_(["created", "pending_payment"])
        ).count()
        active_subs = session.query(UserSubscription).filter(UserSubscription.status == "active").count()
    except SQLAlchemyError as exc:
        total_users = active_users = pending_payments = active_subs = 0
        orm_stats = {
            "available": False,
            "error": exc.__class__.__name__,
        }
    finally:
        session.close()

    readiness, _ = await readiness_payload(container, version="2.0.0")
    return JSONResponse({
        "service": "eazyfill",
        "version": "2.0.0",
        "db_type": container.settings.storage.db_type,
        "redis_enabled": container.settings.redis.enabled,
        "users": {"total": total_users, "active": active_users},
        "payments_pending": pending_payments,
        "active_subscriptions": active_subs,
        "orm_stats": orm_stats,
        "readiness": readiness,
    })


@router.get("/api/system/runtime")
async def system_runtime(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    script = Path(__file__).resolve().parents[4] / "scripts" / "start_backend.sh"
    in_container = Path("/.dockerenv").exists() or bool(os.getenv("KUBERNETES_SERVICE_HOST"))
    restart_supported = script.exists() and not in_container
    return JSONResponse({
        "in_container": in_container,
        "restart_supported": restart_supported,
        "restart_hint": (
            "Restart this service from Docker Compose or your container manager."
            if in_container else
            "Local restart script is available." if script.exists() else "Local restart script was not found."
        ),
    })


@router.get("/api/extension/error-reports")
async def extension_error_reports(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied

    reports_dir = Path(__file__).resolve().parents[4] / "data" / "extension_error_reports"
    summary_path = reports_dir / "latest_summary.json"
    events_path = reports_dir / "events.jsonl"
    summary = {}
    events: list[dict[str, Any]] = []

    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            summary = {}

    if events_path.exists():
        for line in events_path.read_text(encoding="utf-8").splitlines()[-100:]:
            try:
                events.append(json.loads(line))
            except Exception:
                continue

    return JSONResponse({"summary": summary, "events": events})


# ── Server Restart ───────────────────────────────────────────────────────────

@router.post("/api/system/restart")
async def restart_server(request: Request) -> Any:
    """Restart the backend server."""
    denied = _admin_guard(request)
    if denied:
        return denied

    script = Path(__file__).resolve().parents[4] / "scripts" / "start_backend.sh"
    if not script.exists():
        return JSONResponse({"ok": False, "error": "start script not found"}, status_code=500)

    # Spawn restart in a detached subprocess.
    # Use a shell command that waits 2s (to let the HTTP response be sent),
    # then kills old processes, then starts fresh ones.
    # start_new_session=True ensures the child survives even if parent is killed.
    cmd = (
        f"sleep 2; "
        f"pkill -9 -f 'uvicorn app.main' 2>/dev/null; "
        f"exec bash {shlex.quote(str(script))}"
    )
    subprocess.Popen(
        ["bash", "-c", cmd],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return {"ok": True, "message": "Server restarting..."}
