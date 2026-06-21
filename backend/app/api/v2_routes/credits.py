"""EazyFill v2 credits and usage endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.api.v2_routes.deps import V2AuthContext, credits_payload, plan_payload, validate_v2_key

router = APIRouter(prefix="/credits", tags=["v2-credits"])


@router.get("/balance")
async def balance(request: Request, ctx: V2AuthContext = Depends(validate_v2_key)) -> dict:
    return {
        "plan_code": plan_payload(ctx)["code"],
        **credits_payload(ctx, request),
    }


@router.get("/policy")
async def policy(request: Request, ctx: V2AuthContext = Depends(validate_v2_key)) -> dict:
    credit_service = getattr(request.app.state.container, "credit_service", None)
    events = credit_service.get_policies(plan=ctx.plan) if credit_service is not None else {}
    return {
        "plan_code": plan_payload(ctx)["code"],
        "events": events,
    }


@router.get("/daily-summary")
async def daily_summary(request: Request, ctx: V2AuthContext = Depends(validate_v2_key)) -> dict:
    credits = credits_payload(ctx, request)["captcha"]
    return {
        "date": None,
        "captcha_used": credits["used_today"],
        "captcha_limit": credits["daily_limit"],
        "captcha_remaining": credits["remaining"],
        "resets_at": credits["resets_at"],
    }


@router.get("/history")
async def history(
    request: Request,
    ctx: V2AuthContext = Depends(validate_v2_key),
    limit: int = Query(12, ge=1, le=50),
) -> dict:
    service = request.app.state.container.usage_cycle_service
    items = service.get_usage_history(ctx.user_id, limit=limit) if ctx.user_id else []
    return {"items": items, "next_cursor": None}
