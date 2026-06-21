"""Request logging middleware."""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import reset_request_id, set_request_id

logger = logging.getLogger("request")


class LoggingMiddleware(BaseHTTPMiddleware):
    """Log request metadata and duration."""

    @staticmethod
    def _request_id_from_headers(request: Request) -> str:
        raw = request.headers.get("x-request-id", "").strip()
        if raw and len(raw) <= 96 and all(ch.isalnum() or ch in {"-", "_", "."} for ch in raw):
            return raw
        return uuid.uuid4().hex

    async def dispatch(self, request: Request, call_next):
        """Log request after response completes."""

        started = time.perf_counter()
        ip = request.client.host if request.client else "unknown"
        request_id = self._request_id_from_headers(request)
        request.state.request_id = request_id
        token = set_request_id(request_id)
        logger.info(
            "request_incoming",
            extra={
                "context": {
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "ip": ip,
                }
            },
        )
        try:
            response = await call_next(request)
            elapsed = int((time.perf_counter() - started) * 1000)
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Process-Time-Ms"] = str(elapsed)
            logger.info(
                "request_complete",
                extra={
                    "context": {
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                        "status": response.status_code,
                        "ip": ip,
                        "elapsed_ms": elapsed,
                    }
                },
            )
            return response
        except Exception as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            logger.exception(
                "request_failed",
                extra={
                    "context": {
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                        "status": 500,
                        "ip": ip,
                        "elapsed_ms": elapsed,
                        "error_type": type(exc).__name__,
                    }
                },
            )
            raise
        finally:
            reset_request_id(token)
