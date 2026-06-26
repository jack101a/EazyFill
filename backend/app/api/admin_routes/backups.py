from __future__ import annotations

import io
import json
import shutil
import urllib.error
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse

from .utils import _admin_guard, _wants_json, _write_auto_backup

router = APIRouter(tags=["admin-backups"])

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_BACKUPS_DIR = (_PROJECT_ROOT / "backend" / "backups").resolve()
ADMIN_BACKUP_TYPES = {"full", "system", "users"}
REMOTE_TARGETS = {"rclone", "r2"}

@router.get("/export/field-mappings.json")
async def export_field_mappings(request: Request):
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    payload = {
        "exported_at": datetime.now(UTC).isoformat(),
        "field_mappings": container.db.get_all_field_mappings(),
    }
    return Response(
        content=json.dumps(payload, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="field-mappings-export.json"'},
    )

@router.get("/export/master-setup.json")
async def export_master_setup(request: Request):
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    payload = container.db.export_master_setup()
    return Response(
        content=json.dumps(payload, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="master-setup-export.json"'},
    )

@router.post("/backups/create")
async def create_backup_now(request: Request):
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    _write_auto_backup(container, "manual_backup")
    if _wants_json(request):
        return JSONResponse(status_code=200, content={"ok": True})
    return RedirectResponse(url="/admin/?test_status=ok&test_message=Backup+created", status_code=303)

@router.get("/backups")
async def list_backups(request: Request):
    denied = _admin_guard(request)
    if denied:
        return denied
    _BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    backups = []
    for item in sorted(_BACKUPS_DIR.glob("master-setup-*.json"), reverse=True):
        stat = item.stat()
        backups.append(
            {
                "name": item.name,
                "size_bytes": int(stat.st_size),
                "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }
        )
    return {"backups": backups}

@router.post("/backups/restore-latest")
async def restore_latest_backup(request: Request):
    denied = _admin_guard(request)
    if denied:
        return denied
    latest = _BACKUPS_DIR / "latest-master-setup.json"
    if not latest.exists():
        raise HTTPException(status_code=404, detail="latest backup not found")
    payload = json.loads(latest.read_text(encoding="utf-8"))
    container = request.app.state.container
    container.db.import_master_setup(payload)
    _write_auto_backup(container, "restore_latest_backup")
    if _wants_json(request):
        return JSONResponse(status_code=200, content={"ok": True, "message": "Latest backup restored"})
    return RedirectResponse(url="/admin/?test_status=ok&test_message=Latest+backup+restored", status_code=303)

@router.post("/backups/cloud/push")
async def push_cloud_backup(request: Request):
    denied = _admin_guard(request)
    if denied:
        return denied
    import os
    upload_url = os.getenv("BACKUP_CLOUD_UPLOAD_URL", "").strip()
    if not upload_url:
        raise HTTPException(status_code=400, detail="cloud backup upload url not configured")
    token = os.getenv("BACKUP_CLOUD_TOKEN", "").strip()
    container = request.app.state.container
    payload = container.db.export_master_setup()
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(upload_url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if resp.status >= 400:
                raise HTTPException(status_code=502, detail=f"cloud backup failed ({resp.status})")
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"cloud backup failed ({exc.code})") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"cloud backup failed: {exc}") from exc
    _write_auto_backup(container, "cloud_backup_push")
    return JSONResponse(status_code=200, content={"ok": True})

@router.post("/backups/cloud/pull")
async def pull_cloud_backup(request: Request):
    denied = _admin_guard(request)
    if denied:
        return denied
    import os
    download_url = os.getenv("BACKUP_CLOUD_DOWNLOAD_URL", "").strip()
    if not download_url:
        raise HTTPException(status_code=400, detail="cloud backup download url not configured")
    token = os.getenv("BACKUP_CLOUD_TOKEN", "").strip()
    req = urllib.request.Request(download_url, method="GET")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read()
            payload = json.loads(body.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"cloud restore failed ({exc.code})") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"cloud restore failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="cloud payload invalid")
    container = request.app.state.container
    container.db.import_master_setup(payload)
    _write_auto_backup(container, "cloud_backup_pull")
    return JSONResponse(status_code=200, content={"ok": True})

@router.post("/import/master-setup")
async def import_master_setup(
    request: Request,
    setup_file: UploadFile = File(...),
):
    denied = _admin_guard(request)
    if denied:
        return denied
    try:
        raw = await setup_file.read()
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Invalid setup JSON")
    except Exception as exc:
        if _wants_json(request):
            return JSONResponse(status_code=400, content={"ok": False, "message": f"invalid setup file: {exc}"})
        raise HTTPException(status_code=400, detail=f"invalid setup file: {exc}") from exc
    container = request.app.state.container
    container.db.import_master_setup(payload)
    _write_auto_backup(container, "import_master_setup")
    if _wants_json(request):
        return JSONResponse(status_code=200, content={"ok": True, "message": "Master setup imported"})
    return RedirectResponse(url="/admin/?test_status=ok&test_message=Master+setup+imported", status_code=303)


@router.get("/export/master-backup.zip")
async def export_master_backup_zip(request: Request):
    """Export a full ZIP containing master-setup.json AND the models directory."""
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container

    # 1. Generate the JSON setup
    payload = container.db.export_master_setup()

    # 2. Create ZIP in memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add the JSON
        zf.writestr("master-setup.json", json.dumps(payload, indent=2))

        # Add the models directory
        models_dir = (_PROJECT_ROOT / "data" / "models").resolve()
        if models_dir.exists():
            for file in models_dir.glob("*.onnx"):
                zf.write(file, arcname=f"models/{file.name}")

    buf.seek(0)
    filename = f"master-backup-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.post("/import/master-backup.zip")
async def import_master_backup_zip(
    request: Request,
    backup_file: UploadFile = File(...),
):
    """Import a full ZIP backup. Extracts models and imports JSON setup."""
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container

    try:
        raw = await backup_file.read()
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            # 1. Check for master-setup.json
            if "master-setup.json" not in zf.namelist():
                raise ValueError("master-setup.json not found in ZIP")

            # 2. Extract models
            models_dir = (_PROJECT_ROOT / "data" / "models").resolve()
            models_dir.mkdir(parents=True, exist_ok=True)
            for name in zf.namelist():
                if name.startswith("models/") and name.endswith(".onnx"):
                    filename = Path(name).name
                    with zf.open(name) as source, (models_dir / filename).open("wb") as target:
                        shutil.copyfileobj(source, target)

            # 3. Import JSON setup
            payload_raw = zf.read("master-setup.json")
            payload = json.loads(payload_raw.decode("utf-8"))
            container.db.import_master_setup(payload)

        _write_auto_backup(container, "import_master_backup_zip")
        return JSONResponse({"ok": True, "message": "Full master backup imported (including models)"})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to import ZIP backup: {exc}")


@router.post("/api/backups/system")
async def create_system_backup(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    try:
        result = container.backup_service.create_system_backup()
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/backups/full")
async def create_full_backup(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    try:
        result = container.backup_service.full_backup()
        return JSONResponse(result, status_code=200 if result.get("status") == "completed" else 502)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/backups/users")
async def create_user_backup(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    try:
        result = container.backup_service.create_user_backup()
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/backups/postgres")
async def create_postgres_backup(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    try:
        result = container.backup_service.create_postgres_backup()
        return JSONResponse(result, status_code=200 if result.get("success") else 502)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.get("/api/backups/list")
async def list_backups_all(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    try:
        result = container.backup_service.list_all_backups()
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/backups/inspect")
async def inspect_backup(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    backup_type = str(request.query_params.get("type", "")).strip().lower()
    filename = str(request.query_params.get("filename", "")).strip()
    if backup_type not in ADMIN_BACKUP_TYPES:
        return JSONResponse({"error": "type must be 'full', 'system', or 'users'"}, status_code=400)
    if not filename:
        return JSONResponse({"error": "filename is required"}, status_code=400)
    try:
        if backup_type == "full":
            result = container.backup_service.inspect_full_backup(filename)
        elif backup_type == "system":
            result = container.backup_service.inspect_system_backup(filename)
        else:
            result = container.backup_service.inspect_user_backup(filename)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/backups/restore")
async def restore_split_backup(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    body = await request.json()
    backup_type = str(body.get("type", "")).strip().lower()
    filename = str(body.get("filename", "")).strip()
    if backup_type not in ADMIN_BACKUP_TYPES:
        return JSONResponse({"error": "type must be 'full', 'system', or 'users'"}, status_code=400)
    if not filename:
        return JSONResponse({"error": "filename is required"}, status_code=400)
    try:
        if backup_type == "full":
            result = container.backup_service.restore_full_backup(
                filename,
                confirm=str(body.get("confirm", "")),
            )
        elif backup_type == "system":
            result = container.backup_service.restore_system_backup(filename)
        else:
            result = container.backup_service.restore_user_backup(filename)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/backups/rclone-sync")
async def rclone_sync_latest(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body if isinstance(body, dict) else {}
    target = str(body.get("target") or "rclone").strip().lower()
    if target not in REMOTE_TARGETS:
        return JSONResponse({"success": False, "error": "target must be 'rclone' or 'r2'"}, status_code=400)
    results = []
    for category in ["full", "system", "users"]:
        r = container.backup_service.rclone_sync_latest_category(category, target=target)
        results.append({**r, "category": category})
    return JSONResponse({"results": results})


@router.post("/api/backups/rclone-pull-latest")
async def rclone_pull_latest(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    body = await request.json()
    category = str(body.get("type", "")).strip().lower()
    target = str(body.get("target") or "rclone").strip().lower()
    if category not in ADMIN_BACKUP_TYPES:
        return JSONResponse({"success": False, "error": "type must be 'full', 'system', or 'users'"}, status_code=400)
    if target not in REMOTE_TARGETS:
        return JSONResponse({"success": False, "error": "target must be 'rclone' or 'r2'"}, status_code=400)
    result = container.backup_service.rclone_pull_latest(category, target=target)
    return JSONResponse(result, status_code=200 if result.get("success") else 502)


@router.post("/api/backups/rclone-restore-latest")
async def rclone_restore_latest(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    body = await request.json()
    category = str(body.get("type", "")).strip().lower()
    target = str(body.get("target") or "rclone").strip().lower()
    if category not in ADMIN_BACKUP_TYPES:
        return JSONResponse({"success": False, "error": "type must be 'full', 'system', or 'users'"}, status_code=400)
    if target not in REMOTE_TARGETS:
        return JSONResponse({"success": False, "error": "target must be 'rclone' or 'r2'"}, status_code=400)
    if category == "full" and str(body.get("confirm", "")) != "RESTORE FULL SNAPSHOT":
        return JSONResponse({"success": False, "error": "confirmation phrase required"}, status_code=400)
    result = container.backup_service.rclone_restore_latest(category, target=target, confirm=str(body.get("confirm", "")))
    return JSONResponse(result, status_code=200 if result.get("success") else 502)


@router.post("/api/backups/telegram-sync")
async def telegram_sync_latest(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    results = []
    for category in ["full", "system", "users"]:
        r = container.backup_service.telegram_sync_latest_category(category)
        results.append({**r, "category": category})
    return JSONResponse({"results": results})


@router.post("/api/backups/telegram-pull-latest")
async def telegram_pull_latest(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    body = await request.json()
    category = str(body.get("type", "")).strip().lower()
    if category not in ADMIN_BACKUP_TYPES:
        return JSONResponse({"success": False, "error": "type must be 'full', 'system', or 'users'"}, status_code=400)
    result = container.backup_service.telegram_pull_latest(category)
    return JSONResponse(result, status_code=200 if result.get("success") else 502)


@router.post("/api/backups/telegram-restore-latest")
async def telegram_restore_latest(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    body = await request.json()
    category = str(body.get("type", "")).strip().lower()
    if category not in ADMIN_BACKUP_TYPES:
        return JSONResponse({"success": False, "error": "type must be 'full', 'system', or 'users'"}, status_code=400)
    if category == "full" and str(body.get("confirm", "")) != "RESTORE FULL SNAPSHOT":
        return JSONResponse({"success": False, "error": "confirmation phrase required"}, status_code=400)
    result = container.backup_service.telegram_restore_latest(category, confirm=str(body.get("confirm", "")))
    return JSONResponse(result, status_code=200 if result.get("success") else 502)


@router.get("/api/backups/remote-config")
async def get_remote_backup_config(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    try:
        return JSONResponse(container.backup_service.get_remote_backup_config())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/backups/remote-config")
async def save_remote_backup_config(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    try:
        body = await request.json()
        if not isinstance(body, dict):
            return JSONResponse({"error": "request body must be a JSON object"}, status_code=400)
        return JSONResponse(container.backup_service.save_remote_backup_config(body))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/backups/test-rclone")
async def test_rclone_backup_target(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    try:
        try:
            body = await request.json()
        except Exception:
            body = {}
        body = body if isinstance(body, dict) else {}
        target = str(body.get("target") or "rclone").strip().lower()
        if target == "r2" and not (body.get("rclone_remote") or body.get("rclone_path")):
            config = container.backup_service.get_remote_backup_config()
            bucket_path = "/".join(
                part for part in [
                    str(config.get("cloudflare_r2_bucket") or "").strip().strip("/"),
                    str(config.get("cloudflare_r2_prefix") or "").strip().strip("/"),
                ]
                if part
            )
            body["rclone_remote"] = config.get("cloudflare_r2_remote")
            body["rclone_path"] = bucket_path
        result = container.backup_service.test_rclone_remote(
            remote=body.get("rclone_remote"),
            remote_path=body.get("rclone_path"),
        )
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
