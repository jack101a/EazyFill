"""Production readiness checks for the API process."""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from sqlalchemy import text


def _check_database(container: Any) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        with container.db.connect() as conn:
            conn.execute("SELECT 1").fetchone()
        return {
            "status": "ok",
            "critical": True,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
    except Exception as exc:
        return {
            "status": "error",
            "critical": True,
            "error_type": type(exc).__name__,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }


def _check_orm_database(container: Any) -> dict[str, Any]:
    settings = getattr(container, "settings", None)
    storage = getattr(settings, "storage", None)
    db_type = str(getattr(storage, "db_type", "sqlite") or "sqlite").lower()
    if db_type != "postgresql":
        return {"status": "disabled", "critical": False, "backend": db_type}

    started = time.perf_counter()
    try:
        from app.core.db import get_session

        session = get_session()
        try:
            session.execute(text("SELECT 1")).fetchone()
        finally:
            session.close()
        return {
            "status": "ok",
            "critical": True,
            "backend": "postgresql",
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
    except Exception as exc:
        return {
            "status": "error",
            "critical": True,
            "backend": "postgresql",
            "error_type": type(exc).__name__,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }


async def _check_optional_service(container: Any, attr: str, fallback: dict[str, Any]) -> dict[str, Any]:
    service = getattr(container, attr, None)
    health = getattr(service, "health", None)
    if health is None:
        return fallback
    try:
        result = health()
        if hasattr(result, "__await__"):
            result = await result
        return dict(result)
    except Exception as exc:
        return {"status": "error", "critical": False, "error_type": type(exc).__name__}


async def readiness_payload(container: Any, *, version: str) -> tuple[dict[str, Any], int]:
    """Build a non-secret readiness payload and HTTP status code."""
    settings = getattr(container, "settings", None)
    mode = str(getattr(settings, "app_mode", os.getenv("APP_MODE", "normal")) or "normal").lower()
    checks = {
        "database": await asyncio.to_thread(_check_database, container),
        "orm_database": await asyncio.to_thread(_check_orm_database, container),
        "solver_queue": await _check_optional_service(
            container,
            "solver_service",
            {"status": "unknown", "critical": False},
        ),
        "rate_limiter": await _check_optional_service(
            container,
            "rate_limiter",
            {"status": "unknown", "critical": False},
        ),
    }

    critical_failed = any(
        bool(check.get("critical")) and check.get("status") not in {"ok", "disabled"}
        for check in checks.values()
    )
    degraded = any(check.get("status") not in {"ok", "disabled"} for check in checks.values())
    status = "error" if critical_failed else "degraded" if degraded else "ok"
    code = 503 if critical_failed else 200
    return {
        "status": status,
        "service": "eazyfill",
        "version": version,
        "mode": mode,
        "checks": checks,
    }, code
