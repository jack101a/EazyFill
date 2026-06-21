"""Admin APIs for CAPTCHA model registry and routing maps."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from app.core.database import Database
from app.core.paths import get_project_root

from .utils import _admin_guard, _slug, _write_auto_backup

router = APIRouter(tags=["admin-captcha-models"])

_PROJECT_ROOT = get_project_root()
_MODELS_DIR = (_PROJECT_ROOT / "data" / "models").resolve()
CAPTCHA_TASK_TYPE = "image"


def _json_error(error: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": error}, status_code=status_code)


def _clean_task_type(value: Any) -> str:
    task_type = str(value or CAPTCHA_TASK_TYPE).strip().lower()
    if task_type != CAPTCHA_TASK_TYPE:
        raise HTTPException(status_code=400, detail="task_type must be image")
    return CAPTCHA_TASK_TYPE


def _clean_lifecycle_state(value: Any) -> str:
    state = str(value or "candidate").strip().lower()
    if state not in {"candidate", "staging", "production", "rolled_back"}:
        raise HTTPException(status_code=400, detail="invalid lifecycle_state")
    return state


def _model_in_use(container, model_id: int) -> list[dict[str, Any]]:
    return [
        mapping
        for mapping in container.db.get_all_field_mappings()
        if int(mapping.get("ai_model_id") or 0) == int(model_id)
    ]


@router.get("/api/captcha/models")
async def list_captcha_models(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    return JSONResponse({
        "models": container.db.get_model_registry(),
        "field_mappings": container.db.get_all_field_mappings(),
    })


@router.post("/api/captcha/models/upload")
async def upload_captcha_model(
    request: Request,
    file: UploadFile = File(...),
) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied

    form = await request.form()
    ai_model_name = str(form.get("ai_model_name") or form.get("model_name") or "").strip()
    version = str(form.get("version") or "v1").strip() or "v1"
    task_type = _clean_task_type(form.get("task_type") or "image")
    runtime = str(form.get("runtime") or "onnx").strip().lower()
    notes = str(form.get("notes") or "").strip() or None
    if runtime != "onnx":
        return _json_error("runtime must be onnx")
    if not ai_model_name:
        return _json_error("ai_model_name is required")
    if not file.filename or Path(file.filename).suffix.lower() != ".onnx":
        return _json_error("Only .onnx model uploads are supported")

    _MODELS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{_slug(ai_model_name)}_{_slug(version)}.onnx"
    candidate = _MODELS_DIR / filename
    suffix = 2
    while candidate.exists():
        filename = f"{_slug(ai_model_name)}_{_slug(version)}_{suffix}.onnx"
        candidate = _MODELS_DIR / filename
        suffix += 1

    bytes_written = 0
    try:
        with candidate.open("wb") as out_file:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                bytes_written += len(chunk)
                out_file.write(chunk)
        await file.close()
        if bytes_written <= 0:
            candidate.unlink(missing_ok=True)
            return _json_error("Uploaded model file is empty")
        model_id = request.app.state.container.db.add_model_registry_entry(
            ai_model_name=ai_model_name,
            version=version,
            task_type=task_type,
            ai_runtime=runtime,
            ai_model_filename=filename,
            notes=notes,
            status="active",
            lifecycle_state="candidate",
        )
    except sqlite3.IntegrityError:
        candidate.unlink(missing_ok=True)
        return _json_error("Model filename already exists")
    except Exception as exc:
        candidate.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}") from exc

    _write_auto_backup(request.app.state.container, "captcha_model_upload")
    return JSONResponse({"ok": True, "model_id": model_id, "filename": filename})


@router.patch("/api/captcha/models/{model_id}")
async def update_captcha_model(request: Request, model_id: int) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    body = await request.json()
    name = str(body.get("ai_model_name") or body.get("model_name") or "").strip()
    if not name:
        return _json_error("ai_model_name is required")
    request.app.state.container.db.update_model_registry_entry(
        ai_model_id=int(model_id),
        ai_model_name=name,
        version=str(body.get("version") or "v1").strip() or "v1",
        task_type=_clean_task_type(body.get("task_type") or "image"),
        notes=str(body.get("notes") or "").strip() or None,
        lifecycle_state=_clean_lifecycle_state(body.get("lifecycle_state") or "candidate"),
    )
    _write_auto_backup(request.app.state.container, "captcha_model_update")
    return JSONResponse({"ok": True})


@router.delete("/api/captcha/models/{model_id}")
async def delete_captcha_model(request: Request, model_id: int) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    entry = container.db.get_model_registry_entry(int(model_id))
    if not entry:
        return _json_error("model_not_found", status_code=404)
    dependent_mappings = _model_in_use(container, int(model_id))
    if dependent_mappings:
        return JSONResponse(
            {
                "ok": False,
                "error": "model_in_use",
                "mapping_count": len(dependent_mappings),
                "domains": sorted({str(mapping.get("domain") or "") for mapping in dependent_mappings}),
            },
            status_code=409,
        )
    filename = str(entry.get("ai_model_filename") or "")
    if str(entry.get("ai_runtime") or "") == "onnx" and filename:
        target = (_MODELS_DIR / filename).resolve()
        if target == _MODELS_DIR or _MODELS_DIR in target.parents:
            target.unlink(missing_ok=True)
    container.db.delete_model_registry_entry(int(model_id))
    _write_auto_backup(container, "captcha_model_delete")
    return JSONResponse({"ok": True})


@router.post("/api/captcha/mappings")
async def set_captcha_mapping(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    body = await request.json()
    domain = Database._normalize_domain(body.get("domain"))
    if not domain:
        return _json_error("domain is required")
    task_type = _clean_task_type(body.get("task_type") or body.get("source_data_type") or "image")
    field_name = str(body.get("field_name") or f"{task_type}_default").strip()
    ai_model_id = int(body.get("ai_model_id") or 0)
    if not field_name or ai_model_id <= 0:
        return _json_error("field_name and ai_model_id are required")
    request.app.state.container.db.set_field_mapping(
        domain=domain,
        field_name=field_name,
        task_type=task_type,
        ai_model_id=ai_model_id,
        source_data_type=str(body.get("source_data_type") or task_type),
        source_selector=str(body.get("source_selector") or ""),
        target_data_type=str(body.get("target_data_type") or "text"),
        target_selector=str(body.get("target_selector") or ""),
    )
    _write_auto_backup(request.app.state.container, "captcha_mapping_set")
    return JSONResponse({"ok": True})


@router.put("/api/captcha/mappings/{mapping_id}")
async def update_captcha_mapping(request: Request, mapping_id: int) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    body = await request.json()
    domain = Database._normalize_domain(body.get("domain"))
    if not domain:
        return _json_error("domain is required")
    task_type = _clean_task_type(body.get("task_type") or body.get("source_data_type") or "image")
    request.app.state.container.db.update_field_mapping(
        mapping_id=int(mapping_id),
        domain=domain,
        field_name=str(body.get("field_name") or f"{task_type}_default").strip(),
        task_type=task_type,
        source_data_type=str(body.get("source_data_type") or task_type),
        source_selector=str(body.get("source_selector") or ""),
        target_data_type=str(body.get("target_data_type") or "text"),
        target_selector=str(body.get("target_selector") or ""),
        ai_model_id=int(body.get("ai_model_id") or 0),
    )
    _write_auto_backup(request.app.state.container, "captcha_mapping_update")
    return JSONResponse({"ok": True})


@router.delete("/api/captcha/mappings/{mapping_id}")
async def delete_captcha_mapping(request: Request, mapping_id: int) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    request.app.state.container.db.remove_field_mapping(int(mapping_id))
    _write_auto_backup(request.app.state.container, "captcha_mapping_delete")
    return JSONResponse({"ok": True})
