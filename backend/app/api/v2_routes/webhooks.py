"""EazyFill v2 payment webhook endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.webhooks import razorpay_webhook

router = APIRouter(prefix="/webhooks", tags=["v2-webhooks"])


@router.post("/razorpay")
async def v2_razorpay_webhook(request: Request) -> JSONResponse:
    return await razorpay_webhook(request)
