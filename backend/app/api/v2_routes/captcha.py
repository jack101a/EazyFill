"""EazyFill v2 CAPTCHA solving endpoints."""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.v2_routes.deps import V2AuthContext, credits_payload, validate_v2_key
from app.core.database import Database
from app.core.paths import get_project_root
from app.core.security import is_valid_base64
from app.middleware.v2_captcha_throttle import enforce_v2_captcha_throttle
from app.services.credit_service import CAPTCHA_SOLVE_IMAGE

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/captcha", tags=["v2-captcha"])
_SAMPLES_DIR = (get_project_root() / "data" / "captcha_samples").resolve()
_MAX_LEARNING_SAMPLE_BYTES = 750_000


class CaptchaSolveRequest(BaseModel):
    type: str = Field(default="image")
    payload_base64: str = ""
    domain: str | None = None
    field_name: str | None = None
    source_selector: str | None = None
    target_selector: str | None = None
    metadata: dict = Field(default_factory=dict)


class CaptchaRouteProposalRequest(BaseModel):
    domain: str
    source_selector: str
    target_selector: str
    field_name: str | None = None
    page_url: str | None = None
    learning_consent: bool = False
    consent_version: str | None = None
    sample_payload_base64: str = ""
    user_label: str = ""
    metadata: dict = Field(default_factory=dict)


def _quota_error(result: dict) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail={
            "error": result.get("reason") or "daily_quota_exceeded",
            "message": "Daily CAPTCHA limit reached.",
            "credits_remaining": max(0, int(result.get("limit") or 0) - int(result.get("used") or 0)),
            "credits_required": int(result.get("credits_charged") or result.get("credits_used") or 0),
            "meter_event_type": result.get("event_type"),
            "resets_at": None,
        },
    )


def _clean_optional(value: object) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None


def _clean_selector(value: object) -> str:
    return str(value or "").strip()


def _route_field_name(domain: str, source_selector: str, target_selector: str, explicit: str | None = None) -> str:
    cleaned = str(explicit or "").strip()
    if cleaned:
        return cleaned[:120]
    digest = hashlib.sha256(f"{domain}|{source_selector}|{target_selector}".encode("utf-8")).hexdigest()[:16]
    return f"captcha_{digest}"


def _mapping_response(mapping: dict, status: str = "approved") -> dict:
    return {
        "status": status,
        "approved": status == "approved",
        "field_name": mapping.get("field_name"),
        "domain": mapping.get("domain"),
        "source_selector": mapping.get("source_selector"),
        "target_selector": mapping.get("target_selector"),
        "model": {
            "id": mapping.get("ai_model_id"),
            "name": mapping.get("ai_model_name"),
            "version": mapping.get("version"),
            "lifecycle_state": mapping.get("lifecycle_state"),
        },
    }


def _proposal_response(proposal: dict | None, field_name: str, sample_saved: bool = False) -> dict:
    status = str((proposal or {}).get("status") or "pending")
    return {
        "status": status,
        "approved": False,
        "proposal_id": (proposal or {}).get("id"),
        "field_name": str((proposal or {}).get("proposed_field_name") or field_name),
        "sample_saved": sample_saved,
    }


def _captcha_field_name(payload: CaptchaSolveRequest) -> str | None:
    metadata = payload.metadata or {}
    return _clean_optional(
        payload.field_name
        or metadata.get("field_name")
        or metadata.get("fieldName")
        or metadata.get("selector_id")
        or metadata.get("selectorId")
        or metadata.get("config_id")
        or metadata.get("configId")
    )


def _save_learning_sample(
    container,
    *,
    domain: str,
    field_name: str,
    reported_by: int,
    reported_by_kind: str = "legacy_api_key",
    reported_by_user_id: int | None = None,
    image_base64: str,
    label_text: str,
) -> int | None:
    if not image_base64 or not label_text.strip():
        return None
    if not is_valid_base64(image_base64):
        raise HTTPException(status_code=400, detail="sample_payload_base64 invalid")
    try:
        image_bytes = base64.b64decode(image_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="sample_payload_base64 invalid") from exc
    if not image_bytes:
        return None
    if len(image_bytes) > _MAX_LEARNING_SAMPLE_BYTES:
        raise HTTPException(status_code=413, detail="learning sample too large")

    _SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(image_bytes).hexdigest()
    target = (_SAMPLES_DIR / f"{domain}_{field_name}_{digest[:20]}.png").resolve()
    if target == _SAMPLES_DIR or _SAMPLES_DIR not in target.parents:
        raise HTTPException(status_code=400, detail="invalid sample path")
    target.write_bytes(image_bytes)
    relative_path = str(Path("data") / "captcha_samples" / target.name)
    if hasattr(container.db, "add_retrain_sample"):
        return container.db.add_retrain_sample(
            domain=domain,
            image_path=relative_path,
            reported_by=reported_by,
            reported_by_kind=reported_by_kind,
            reported_by_user_id=reported_by_user_id,
            task_type="image",
            field_name=field_name,
            label_text=label_text.strip()[:256],
        )
    return None


@router.post("/routes/propose")
async def propose_route(
    request: Request,
    payload: CaptchaRouteProposalRequest,
    ctx: V2AuthContext = Depends(validate_v2_key),
) -> dict:
    container = request.app.state.container
    normalized_domain = Database._normalize_domain(payload.domain)
    source_selector = _clean_selector(payload.source_selector)
    target_selector = _clean_selector(payload.target_selector)
    if not normalized_domain or not source_selector or not target_selector:
        raise HTTPException(status_code=400, detail="domain, source_selector, and target_selector are required")

    approved = (
        container.db.get_field_mapping_by_selectors(normalized_domain, source_selector, target_selector, "image")
        if hasattr(container.db, "get_field_mapping_by_selectors")
        else None
    )
    if approved:
        return _mapping_response(approved)

    field_name = _route_field_name(normalized_domain, source_selector, target_selector, payload.field_name)
    reported_by_kind = "user_api_key" if ctx.key_kind == "user" else "legacy_api_key"
    reported_by_user_id = ctx.user_id if ctx.key_kind == "user" else None
    proposal = None
    if hasattr(container.db, "propose_field_mapping"):
        proposal = container.db.propose_field_mapping(
            domain=normalized_domain,
            task_type="image",
            source_data_type="image",
            source_selector=source_selector,
            target_data_type="text",
            target_selector=target_selector,
            proposed_field_name=field_name,
            reported_by=ctx.key_id,
            reported_by_kind=reported_by_kind,
            reported_by_user_id=reported_by_user_id,
        )
    if proposal is None and hasattr(container.db, "get_field_mapping_proposal_by_selectors"):
        proposal = container.db.get_field_mapping_proposal_by_selectors(
            normalized_domain,
            source_selector,
            target_selector,
            "image",
        )

    sample_saved = False
    if payload.learning_consent:
        sample_saved = _save_learning_sample(
            container,
            domain=normalized_domain,
            field_name=field_name,
            reported_by=ctx.key_id,
            reported_by_kind=reported_by_kind,
            reported_by_user_id=reported_by_user_id,
            image_base64=payload.sample_payload_base64,
            label_text=payload.user_label,
        ) is not None

    return _proposal_response(proposal, field_name, sample_saved=sample_saved)


@router.get("/routes/status")
async def route_status(
    request: Request,
    domain: str,
    source_selector: str,
    target_selector: str,
    ctx: V2AuthContext = Depends(validate_v2_key),
) -> dict:
    del ctx
    container = request.app.state.container
    normalized_domain = Database._normalize_domain(domain)
    source_selector = _clean_selector(source_selector)
    target_selector = _clean_selector(target_selector)
    if not normalized_domain or not source_selector or not target_selector:
        raise HTTPException(status_code=400, detail="domain, source_selector, and target_selector are required")
    approved = (
        container.db.get_field_mapping_by_selectors(normalized_domain, source_selector, target_selector, "image")
        if hasattr(container.db, "get_field_mapping_by_selectors")
        else None
    )
    if approved:
        return _mapping_response(approved)
    proposal = (
        container.db.get_field_mapping_proposal_by_selectors(normalized_domain, source_selector, target_selector, "image")
        if hasattr(container.db, "get_field_mapping_proposal_by_selectors")
        else None
    )
    return _proposal_response(
        proposal,
        _route_field_name(normalized_domain, source_selector, target_selector),
    )


@router.post("/solve")
async def solve(
    request: Request,
    payload: CaptchaSolveRequest,
    ctx: V2AuthContext = Depends(validate_v2_key),
) -> dict:
    await enforce_v2_captcha_throttle(request, ctx)

    if payload.type != "image":
        raise HTTPException(status_code=400, detail="unsupported captcha type")
    payload_base64 = payload.payload_base64
    if not payload_base64:
        raise HTTPException(status_code=400, detail="payload_base64 is required")
    if not is_valid_base64(payload_base64):
        raise HTTPException(status_code=400, detail="payload_base64 invalid")

    container = request.app.state.container
    normalized_domain = Database._normalize_domain(payload.domain)
    field_name = _captcha_field_name(payload)
    if not normalized_domain or not field_name:
        raise HTTPException(status_code=400, detail="domain and field_name are required for captcha routing")
    mapped_model = (
        container.db.get_field_mapped_model(normalized_domain, field_name, "image")
        if hasattr(getattr(container, "db", None), "get_field_mapped_model")
        else None
    )
    if not mapped_model:
        raise HTTPException(status_code=404, detail="captcha model mapping not found")
    credit_service = getattr(container, "credit_service", None)
    reservation = None
    reservation_units = 1
    credits_used = 0
    reservation_metadata = {
        "domain": normalized_domain,
        "field_name": field_name,
        "source_selector": payload.source_selector or "",
        "target_selector": payload.target_selector or "",
    }
    if ctx.user_id:
        if credit_service is not None:
            reservation = credit_service.reserve_captcha(
                ctx.user_id,
                plan=ctx.plan,
                subscription_id=ctx.subscription.id if ctx.subscription else None,
                amount=reservation_units,
                metadata=reservation_metadata,
            )
        else:
            reservation = container.usage_cycle_service.increment_usage_atomic(ctx.user_id, amount=1)
        if not reservation.get("allowed"):
            raise _quota_error(reservation)
        credits_used = int(reservation.get("credits_charged") or reservation.get("credits_used") or 1)

    solved = None
    try:
        solved = await container.solver_service.submit_captcha(
            captcha_type="image",
            payload_base64=payload_base64,
            domain=normalized_domain or None,
            field_name=field_name,
        )
        try:
            container.usage_service.record(
                key_id=ctx.key_id,
                task_type=f"captcha:{payload.type}",
                status="ok",
                processing_ms=int(solved.get("processing_ms") or 0),
                model_used=solved.get("model_used"),
                domain=normalized_domain or None,
                ip=request.client.host if request.client else None,
            )
        except Exception:
            pass
        current_credits = credits_payload(ctx, request)["captcha"]
        return {
            "result": solved["result"],
            "confidence": solved.get("confidence", 1.0),
            "processing_ms": int(solved.get("processing_ms") or 0),
            "model_used": solved.get("model_used"),
            "routing": {
                "domain": normalized_domain or None,
                "field_name": field_name,
            },
            "meter_event_type": CAPTCHA_SOLVE_IMAGE,
            "credit_unit_cost": int(reservation.get("unit_cost") or credits_used or 0) if reservation else 0,
            "credits_used": credits_used,
            "used_today": current_credits["used_today"],
            "daily_limit": current_credits["daily_limit"],
            "credits_remaining": current_credits["remaining"],
            "resets_at": current_credits["resets_at"],
        }
    except HTTPException:
        if solved is None and reservation and ctx.user_id:
            if credit_service is not None:
                credit_service.refund_captcha(
                    ctx.user_id,
                    plan=ctx.plan,
                    subscription_id=ctx.subscription.id if ctx.subscription else None,
                    amount=reservation_units,
                    cycle_id=reservation.get("cycle_id"),
                    metadata={**reservation_metadata, "reason": "solve_http_exception"},
                )
            else:
                container.usage_cycle_service.refund_usage_atomic(
                    ctx.user_id,
                    amount=max(1, credits_used),
                    cycle_id=reservation.get("cycle_id"),
                )
        raise
    except Exception as exc:
        if solved is None and reservation and ctx.user_id:
            if credit_service is not None:
                credit_service.refund_captcha(
                    ctx.user_id,
                    plan=ctx.plan,
                    subscription_id=ctx.subscription.id if ctx.subscription else None,
                    amount=reservation_units,
                    cycle_id=reservation.get("cycle_id"),
                    metadata={**reservation_metadata, "reason": "solve_failed"},
                )
            else:
                container.usage_cycle_service.refund_usage_atomic(
                    ctx.user_id,
                    amount=max(1, credits_used),
                    cycle_id=reservation.get("cycle_id"),
                )
        logger.exception("v2_captcha_solve_failed")
        raise HTTPException(status_code=500, detail="captcha solve failed") from exc
