"""EazyFill v2 API routes."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v2_routes import auth, billing, captcha, credits, devices, keys, plans, sync, webhooks

router = APIRouter(prefix="/v2", tags=["v2"])

router.include_router(auth.router)
router.include_router(plans.router)
router.include_router(credits.router)
router.include_router(captcha.router)
router.include_router(sync.router)
router.include_router(billing.router)
router.include_router(keys.router)
router.include_router(devices.router)
router.include_router(webhooks.router)
