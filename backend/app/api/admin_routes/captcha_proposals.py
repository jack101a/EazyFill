"""Admin APIs for CAPTCHA field-mapping proposals."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.paths import get_project_root

from .utils import _admin_guard, _write_auto_backup

router = APIRouter(tags=["admin-captcha-proposals"])
_PROJECT_ROOT = get_project_root()


def _attach_sample_counts(container, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return rows
    with container.db.models.connect() as conn:
        for row in rows:
            sample = conn.execute(
                """
                SELECT COUNT(*) AS sample_count, MAX(created_at) AS latest_sample_at
                FROM retrain_samples
                WHERE domain = ? AND field_name = ? AND task_type = 'image'
                """,
                (row.get("domain"), row.get("proposed_field_name")),
            ).fetchone()
            row["sample_count"] = int(sample["sample_count"] or 0) if sample else 0
            row["latest_sample_at"] = sample["latest_sample_at"] if sample else None
    return rows


def _base_field_name(proposal: dict) -> str:
    return str(proposal.get("proposed_field_name") or "").strip() or "captcha"


def _exact_mapping_exists(conn, proposal: dict) -> bool:
    row = conn.execute(
        """
        SELECT id FROM field_mappings
        WHERE domain = ? AND task_type = ? AND source_selector = ? AND target_selector = ?
        LIMIT 1
        """,
        (
            proposal["domain"],
            proposal["task_type"],
            proposal.get("source_selector", ""),
            proposal.get("target_selector", ""),
        ),
    ).fetchone()
    return bool(row)


def _unique_field_name(conn, proposal: dict) -> str | None:
    base = _base_field_name(proposal)
    existing = conn.execute(
        """
        SELECT source_selector, target_selector FROM field_mappings
        WHERE domain = ? AND field_name = ? AND task_type = ?
        LIMIT 1
        """,
        (proposal["domain"], base, proposal["task_type"]),
    ).fetchone()
    if not existing:
        return base
    if (
        existing["source_selector"] == (proposal.get("source_selector") or "")
        and existing["target_selector"] == (proposal.get("target_selector") or "")
    ):
        return None

    proposal_id = int(proposal["id"])
    for suffix in [str(proposal_id), *[f"{proposal_id}_{index}" for index in range(2, 100)]]:
        candidate = f"{base}_{suffix}"
        conflict = conn.execute(
            """
            SELECT id FROM field_mappings
            WHERE domain = ? AND field_name = ? AND task_type = ?
            LIMIT 1
            """,
            (proposal["domain"], candidate, proposal["task_type"]),
        ).fetchone()
        if not conflict:
            return candidate
    raise HTTPException(status_code=400, detail=f"Could not allocate unique field name for proposal {proposal_id}")


def _active_models(container) -> list[dict[str, Any]]:
    return [
        {
            "id": model["id"],
            "ai_model_name": model["ai_model_name"],
            "version": model["version"],
            "task_type": model["task_type"],
            "lifecycle_state": model["lifecycle_state"],
        }
        for model in container.db.get_model_registry()
        if model.get("status") == "active"
    ]


def _select_model(container, model_id: int | None) -> dict[str, Any]:
    models = [item for item in container.db.get_model_registry() if item.get("status") == "active"]
    if model_id is not None:
        model = next((item for item in models if int(item["id"]) == int(model_id)), None)
        if not model:
            raise HTTPException(status_code=400, detail=f"Model {model_id} not found or not active")
        return model
    model = next((item for item in models if str(item.get("task_type") or "image") == "image"), None) or (models[0] if models else None)
    if not model:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "active_model_required",
                "message": "Upload or activate a CAPTCHA model before approving this route.",
            },
        )
    return model


def _latest_labeled_sample(container, proposal: dict, field_name: str) -> dict[str, Any] | None:
    names = [field_name]
    proposed = str(proposal.get("proposed_field_name") or "").strip()
    if proposed and proposed not in names:
        names.append(proposed)
    placeholders = ", ".join("?" for _ in names)
    with container.db.models.connect() as conn:
        row = conn.execute(
            f"""
            SELECT id, image_path, label_text
            FROM retrain_samples
            WHERE domain = ?
              AND task_type = ?
              AND field_name IN ({placeholders})
              AND COALESCE(label_text, '') != ''
            ORDER BY id DESC
            LIMIT 1
            """,
            (proposal["domain"], proposal["task_type"], *names),
        ).fetchone()
        return dict(row) if row else None


def _sample_payload_base64(sample: dict[str, Any]) -> str:
    raw_path = Path(str(sample.get("image_path") or ""))
    target = raw_path if raw_path.is_absolute() else _PROJECT_ROOT / raw_path
    target = target.resolve()
    if target == _PROJECT_ROOT or _PROJECT_ROOT not in target.parents:
        raise HTTPException(status_code=400, detail="learning sample path is invalid")
    if not target.exists():
        raise HTTPException(status_code=400, detail="learning sample image is missing")
    return base64.b64encode(target.read_bytes()).decode("ascii")


async def _verify_model_sample(container, proposal: dict, field_name: str, model: dict) -> None:
    sample = _latest_labeled_sample(container, proposal, field_name)
    if not sample:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "learning_sample_required",
                "message": "A labeled CAPTCHA sample is required before approving this route.",
            },
        )

    expected = str(sample.get("label_text") or "").strip()
    solved = await container.solver_service.solve_direct(
        task_type="image",
        payload_base64=_sample_payload_base64(sample),
        domain=proposal["domain"],
        field_name=field_name,
        model_filename=str(model.get("ai_model_filename") or ""),
    )
    actual = str(solved.get("result") or "").strip()
    if actual != expected:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "model_sample_mismatch",
                "message": "Selected model does not match the labeled CAPTCHA sample.",
                "sample_id": sample.get("id"),
                "expected": expected,
                "actual": actual,
                "model_used": solved.get("model_used"),
            },
        )


async def _approve_one(container, proposal_id: int, model_id: int | None = None, verify_sample: bool = False) -> None:
    with container.db.models.connect() as conn:
        row = conn.execute(
            "SELECT * FROM field_mapping_proposals WHERE id = ?",
            (proposal_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="proposal_not_found")
        proposal = dict(row)
        if _exact_mapping_exists(conn, proposal):
            container.db.mark_field_mapping_proposal_status(proposal_id, "approved")
            return
        field_name = _unique_field_name(conn, proposal)
    if not field_name:
        container.db.mark_field_mapping_proposal_status(proposal_id, "approved")
        return

    model = _select_model(container, model_id)
    if verify_sample:
        await _verify_model_sample(container, proposal, field_name, model)

    container.db.set_field_mapping(
        domain=proposal["domain"],
        field_name=field_name,
        task_type=proposal["task_type"],
        ai_model_id=int(model["id"]),
        source_data_type=proposal.get("source_data_type") or proposal["task_type"],
        source_selector=proposal.get("source_selector", ""),
        target_data_type=proposal.get("target_data_type") or "text",
        target_selector=proposal.get("target_selector", ""),
    )
    container.db.mark_field_mapping_proposal_status(proposal_id, "approved")


@router.get("/api/captcha/proposals")
async def list_captcha_proposals(request: Request) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    status = request.query_params.get("status", "pending")
    if status == "pending":
        return JSONResponse(_attach_sample_counts(container, container.db.get_pending_field_mapping_proposals()))
    if status not in {"all", "approved", "rejected"}:
        raise HTTPException(status_code=400, detail="status must be pending, approved, rejected, or all")
    with container.db.models.connect() as conn:
        if status == "all":
            rows = conn.execute("SELECT * FROM field_mapping_proposals ORDER BY id DESC LIMIT 500").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM field_mapping_proposals WHERE status = ? ORDER BY id DESC LIMIT 200",
                (status,),
            ).fetchall()
    return JSONResponse(_attach_sample_counts(container, [dict(row) for row in rows]))


@router.post("/api/captcha/proposals/{proposal_id}/approve")
async def approve_captcha_proposal(request: Request, proposal_id: int) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    container = request.app.state.container
    body = await request.json()
    raw_model_id = body.get("model_id")
    model_id = int(raw_model_id) if raw_model_id not in (None, "") else None
    await _approve_one(
        container,
        int(proposal_id),
        model_id,
        verify_sample=bool(body.get("verify_sample") or body.get("verifySample")),
    )
    _write_auto_backup(container, "captcha_proposal_approve")
    return JSONResponse({"ok": True})


@router.post("/api/captcha/proposals/{proposal_id}/reject")
async def reject_captcha_proposal(request: Request, proposal_id: int) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    request.app.state.container.db.mark_field_mapping_proposal_status(int(proposal_id), "rejected")
    _write_auto_backup(request.app.state.container, "captcha_proposal_reject")
    return JSONResponse({"ok": True})


@router.delete("/api/captcha/proposals/{proposal_id}")
async def delete_captcha_proposal(request: Request, proposal_id: int) -> Any:
    denied = _admin_guard(request)
    if denied:
        return denied
    deleted = request.app.state.container.db.delete_field_mapping_proposal(int(proposal_id))
    if not deleted:
        raise HTTPException(status_code=404, detail="proposal_not_found")
    _write_auto_backup(request.app.state.container, "captcha_proposal_delete")
    return JSONResponse({"ok": True})
