"""Admin dashboard route definitions — Router Composition."""

from __future__ import annotations
from fastapi import APIRouter
from app.api.admin_routes import (
    auth, backups, settings, analytics, users, payments, subscriptions,
    keys, user_keys, system, eazyfill, models, captcha_proposals,
)

router = APIRouter(prefix="/admin", tags=["admin"])

# Include sub-routers — API routes first, then catch-all SPA fallback LAST
router.include_router(auth.router)
router.include_router(backups.router)
router.include_router(settings.router)
router.include_router(users.router)
router.include_router(payments.router)
router.include_router(subscriptions.router)
router.include_router(keys.router)
router.include_router(user_keys.router)
router.include_router(system.router)
router.include_router(eazyfill.router)
router.include_router(models.router)
router.include_router(captcha_proposals.router)
# Analytics MUST be last — its catch-all /{full_path:path} serves the SPA
router.include_router(analytics.router)
