from __future__ import annotations

from fastapi import Request
from fastapi.responses import PlainTextResponse
from starlette.middleware.base import BaseHTTPMiddleware


_PROTECTED_STATIC_PREFIXES = (
    "/static/extensions/",
)
_PROTECTED_STATIC_PATHS = {
    "/static/extension.zip",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add conservative browser security headers without changing route behavior."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path in _PROTECTED_STATIC_PATHS or request.url.path.startswith(_PROTECTED_STATIC_PREFIXES):
            return PlainTextResponse("Not found", status_code=404)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if request.url.path.startswith("/admin"):
            response.headers.setdefault("Cache-Control", "no-store")
        if request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response
