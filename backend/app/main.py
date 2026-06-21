"""FastAPI entrypoint for EazyFill."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path as _Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.admin import router as admin_router
from app.api.routes import router as v1_router
from app.api.v2_routes import router as v2_router
from app.api.webhooks import router as webhooks_router
from app.background_tasks import backup_scheduler, subscription_expiry_loop
from app.core.config import get_settings, require_runtime_auth
from app.core.container import build_container
from app.core.logging import configure_logging
from app.core.runtime_mode import public_mode, get_runtime_mode
from app.middleware.auth_middleware import AuthMiddleware
from app.middleware.emergency_mode_middleware import EmergencyModeMiddleware
from app.middleware.logging_middleware import LoggingMiddleware
from app.middleware.rate_limit_middleware import RateLimitMiddleware
from app.middleware.security_headers_middleware import SecurityHeadersMiddleware
from app.services.readiness_service import readiness_payload

settings = get_settings()
require_runtime_auth(settings)
configure_logging(settings=settings)
container = build_container(settings=settings)
logger = logging.getLogger(__name__)

_API_VERSION = "2.0.0"


class PrivateNetworkAccessMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers.setdefault("Access-Control-Allow-Private-Network", "true")
        return response


def _env_enabled(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)) or default)
    except ValueError:
        return default


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Manage startup and shutdown lifecycle."""
    # ── Startup ───────────────────────────────────────────────────────────────
    await container.solver_service.start()
    # Wire user key service for auth middleware (from container)
    application.state.user_key_service = container.user_key_service

    background_tasks: list[asyncio.Task] = []
    if _env_enabled("RUN_BACKGROUND_TASKS"):
        background_tasks = [
            asyncio.create_task(backup_scheduler(container)),
            asyncio.create_task(subscription_expiry_loop(container)),
        ]

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    for task in background_tasks:
        task.cancel()
    await container.solver_service.stop()

    # Guard: retrain_service is optional — only wired when the feature is on
    retrain = getattr(container, "retrain_service", None)
    if retrain is not None:
        await retrain.stop()


app = FastAPI(
    title="EazyFill API",
    description="CAPTCHA solving, account, billing, credits, and encrypted extension sync",
    version=_API_VERSION,
    debug=settings.server.debug,
    lifespan=lifespan,
)
app.state.container = container

# Middleware (order: outermost added last executes first)
app.add_middleware(LoggingMiddleware)
app.add_middleware(AuthMiddleware, settings=settings, key_service=container.key_service)
app.add_middleware(EmergencyModeMiddleware, settings=settings)
app.add_middleware(RateLimitMiddleware, settings=settings)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.server.cors_origins,
    allow_origin_regex=settings.server.cors_origin_regex,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(PrivateNetworkAccessMiddleware)

app.include_router(v1_router)
app.include_router(v2_router)
app.include_router(admin_router)
app.include_router(webhooks_router)

# Static assets
_static_dir = _Path(__file__).resolve().parent / "static"
_static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

_admin_assets = _Path(__file__).resolve().parents[2] / "frontend" / "dist" / "assets"
if _admin_assets.exists():
    app.mount("/assets", StaticFiles(directory=str(_admin_assets)), name="admin_assets")

_admin_brand_dir = _Path(__file__).resolve().parents[2] / "frontend" / "dist" / "brand"
if not _admin_brand_dir.exists():
    _admin_brand_dir = _Path(__file__).resolve().parents[2] / "frontend" / "public" / "brand"
if _admin_brand_dir.exists():
    app.mount("/brand", StaticFiles(directory=str(_admin_brand_dir)), name="admin_brand")

_privacy_policy_path = _Path(__file__).resolve().parents[2] / "docs" / "privacy-policy.html"


@app.get("/privacy-policy.html", include_in_schema=False)
@app.get("/privacy", include_in_schema=False)
async def privacy_policy() -> FileResponse:
    return FileResponse(str(_privacy_policy_path), media_type="text/html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "eazyfill", "version": _API_VERSION}


@app.get("/health/public")
async def public_health() -> dict[str, object]:
    mode = get_runtime_mode(settings.app_mode)
    normalized_mode = public_mode(mode)
    accept_public = normalized_mode in {"primary", "remote_primary_db", "failover_readonly"}
    return {
        "ok": True,
        "service": "eazyfill",
        "version": _API_VERSION,
        "node": os.getenv("NODE_ROLE", os.getenv("INSTANCE_ID", "")).strip(),
        "mode": normalized_mode,
        "accept_public_traffic": accept_public,
        "read_only": normalized_mode == "failover_readonly",
        "database_target": os.getenv("DATABASE_TARGET", "primary" if normalized_mode in {"primary", "remote_primary_db"} else "local").strip(),
        "failover": {
            "full_vps_failure_after_seconds": _int_env("FAILOVER_FULL_OUTAGE_SECONDS", 1800),
            "api_offline_after_seconds": _int_env("FAILOVER_API_OUTAGE_SECONDS", 600),
            "restore_after_stable_seconds": _int_env("FAILOVER_RESTORE_STABLE_SECONDS", 600),
        },
    }


@app.get("/ready")
async def ready() -> JSONResponse:
    payload, status_code = await readiness_payload(container, version=_API_VERSION)
    return JSONResponse(payload, status_code=status_code)
