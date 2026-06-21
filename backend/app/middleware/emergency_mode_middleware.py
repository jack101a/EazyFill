"""Restrict public traffic and durable writes based on runtime failover mode."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import Settings
from app.core.runtime_mode import get_runtime_mode


_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

_MODE_STATUS_PATHS = {
    "/health",
    "/ready",
    "/health/public",
    "/privacy",
    "/privacy-policy.html",
}

_FAILOVER_ALLOWED_EXACT = {
    "/v1/solve",
    "/v1/autofill/fill",
}

_FAILOVER_ALLOWED_PREFIXES = (
    "/v1/extension/",
    "/v1/userscripts/",
)


class EmergencyModeMiddleware(BaseHTTPMiddleware):
    """Enforce the public traffic contract for standby/failover modes.

    ``standby`` and ``recovery`` do not accept extension/public API traffic.
    ``failover_readonly`` and legacy ``emergency`` serve degraded traffic but
    block permanent account, payment, admin, learning, and upload writes.
    ``remote_primary_db`` is intentionally writable because the app should be
    pointed at the Oracle primary database in that mode.
    """

    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self._default_mode = str(getattr(settings, "app_mode", "normal") or "normal").lower()

    async def dispatch(self, request: Request, call_next):
        mode = get_runtime_mode(self._default_mode)
        if mode in {"normal", "primary", "remote_primary_db"}:
            return await call_next(request)

        path = request.url.path
        method = request.method.upper()

        if path in _MODE_STATUS_PATHS:
            return await call_next(request)

        if mode in {"standby", "recovery"}:
            return JSONResponse(
                {
                    "detail": "backup node is not accepting public traffic",
                    "error_code": "standby_not_active",
                    "mode": mode,
                },
                status_code=503,
                headers={"Retry-After": "60"},
            )

        if method in _SAFE_METHODS or self._is_failover_allowed(method, path):
            return await call_next(request)

        return JSONResponse(
            {
                "detail": "service is in failover read-only mode; permanent changes are temporarily disabled",
                "error_code": "emergency_mode_read_only" if mode == "emergency" else "failover_read_only",
                "mode": mode,
            },
            status_code=503,
            headers={"Retry-After": "300"},
        )

    @staticmethod
    def _is_failover_allowed(method: str, path: str) -> bool:
        if method != "POST":
            return False
        if path in _FAILOVER_ALLOWED_EXACT:
            return True
        return any(path.startswith(prefix) for prefix in _FAILOVER_ALLOWED_PREFIXES)
