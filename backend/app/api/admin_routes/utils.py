from __future__ import annotations
import hashlib
import hmac
import json
import os
import re
import logging
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus
from fastapi import Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

_TRUSTED_IDENTITY_HEADERS = (
    "cf-access-authenticated-user-email",
    "x-auth-request-email",
    "x-auth-request-user",
    "x-forwarded-user",
)
_ADMIN_SESSION_MAX_AGE_SECONDS = 60 * 60 * 12
_ADMIN_LOGIN_WINDOW_SECONDS = 5 * 60
_ADMIN_LOGIN_MAX_FAILURES = 5
_ADMIN_LOGIN_FAILURES: dict[str, list[float]] = {}

def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-")
    return normalized or "model"

def _safe_label(value: str) -> str:
    """Conservative token used in labeled dataset filenames."""
    normalized = re.sub(r"[^a-zA-Z0-9]+", "", value.strip())
    return (normalized[:32] or "unknown").lower()

def _default_field_for_task(task_type: str) -> str:
    return f"{task_type}_default"

def _fmt_dt(value: str | None) -> str:
    if not value:
        return "Never"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.strftime("%d-%b-%Y %H:%M")
    except Exception:
        return value

def _admin_session_cookie(request: Request) -> str:
    """Create a signed admin session token that survives multi-worker routing."""
    issued_at = str(int(time.time()))
    nonce = secrets.token_urlsafe(16)
    payload = f"{issued_at}.{nonce}"
    signature = hmac.new(
        _admin_session_secret(request),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}.{signature}"

def _admin_session_secret(request: Request) -> bytes:
    settings = request.app.state.container.settings
    secret = (
        settings.auth.admin_token
        or settings.auth.hash_salt
        or settings.auth.admin_password
        or "admin-session"
    )
    return str(secret).encode("utf-8")

def _admin_session_valid(request: Request, token: str) -> bool:
    """Return True when the signed admin session token is live and untampered."""
    parts = token.split(".")
    if len(parts) != 3:
        return False
    issued_at_raw, nonce, signature = parts
    try:
        issued_at = int(issued_at_raw)
    except ValueError:
        return False
    if issued_at <= 0 or issued_at + _ADMIN_SESSION_MAX_AGE_SECONDS <= time.time():
        return False
    payload = f"{issued_at_raw}.{nonce}"
    expected = hmac.new(
        _admin_session_secret(request),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False
    return True

def _admin_session_destroy(token: str) -> None:
    """Stateless signed sessions expire by age; logout clears the browser cookie."""
    return None

def _admin_login_client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    if forwarded:
        return forwarded
    if request.client and request.client.host:
        return request.client.host
    return "unknown"

def _admin_login_memory_key(request: Request) -> str:
    key = _admin_login_client_key(request)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()

def _admin_login_redis_key(request: Request) -> str:
    settings = request.app.state.container.settings
    prefix = getattr(settings.redis, "prefix", "up:") if hasattr(settings, "redis") else "up:"
    return f"{prefix}admin:login_failures:{_admin_login_memory_key(request)}"

def _admin_login_memory_rate_limited(request: Request) -> bool:
    key = _admin_login_memory_key(request)
    cutoff = time.time() - _ADMIN_LOGIN_WINDOW_SECONDS
    failures = [ts for ts in _ADMIN_LOGIN_FAILURES.get(key, []) if ts >= cutoff]
    _ADMIN_LOGIN_FAILURES[key] = failures
    return len(failures) >= _ADMIN_LOGIN_MAX_FAILURES

def _admin_login_memory_record_failure(request: Request) -> None:
    key = _admin_login_memory_key(request)
    _ADMIN_LOGIN_FAILURES.setdefault(key, []).append(time.time())

def _admin_login_memory_clear_failures(request: Request) -> None:
    _ADMIN_LOGIN_FAILURES.pop(_admin_login_memory_key(request), None)

async def _admin_login_redis_client(request: Request):
    settings = request.app.state.container.settings
    redis_cfg = getattr(settings, "redis", None)
    enabled = str(getattr(redis_cfg, "enabled", False)).strip().lower() in {"1", "true", "yes", "on"}
    if not redis_cfg or not enabled:
        return None
    try:
        import redis.asyncio as redis
        return redis.from_url(str(getattr(redis_cfg, "url", "")), decode_responses=True)
    except Exception as exc:
        logging.warning("admin_login_redis_init_failed", extra={"context": {"error_type": type(exc).__name__}})
        return None

async def _admin_login_rate_limited(request: Request) -> bool:
    client = await _admin_login_redis_client(request)
    if client is None:
        return _admin_login_memory_rate_limited(request)

    key = _admin_login_redis_key(request)
    cutoff = time.time() - _ADMIN_LOGIN_WINDOW_SECONDS
    try:
        async with client.pipeline() as pipe:
            pipe.zremrangebyscore(key, 0, cutoff)
            pipe.zcard(key)
            pipe.expire(key, _ADMIN_LOGIN_WINDOW_SECONDS + 30)
            _, count, _ = await pipe.execute()
        return int(count or 0) >= _ADMIN_LOGIN_MAX_FAILURES
    except Exception as exc:
        logging.warning(
            "admin_login_redis_check_failed_fallback_memory",
            extra={"context": {"error_type": type(exc).__name__}},
        )
        return _admin_login_memory_rate_limited(request)
    finally:
        await client.aclose()

async def _admin_login_record_failure(request: Request) -> None:
    client = await _admin_login_redis_client(request)
    if client is None:
        _admin_login_memory_record_failure(request)
        return

    key = _admin_login_redis_key(request)
    now = time.time()
    try:
        async with client.pipeline() as pipe:
            pipe.zadd(key, {str(now): now})
            pipe.zremrangebyscore(key, 0, now - _ADMIN_LOGIN_WINDOW_SECONDS)
            pipe.expire(key, _ADMIN_LOGIN_WINDOW_SECONDS + 30)
            await pipe.execute()
    except Exception as exc:
        logging.warning(
            "admin_login_redis_record_failed_fallback_memory",
            extra={"context": {"error_type": type(exc).__name__}},
        )
        _admin_login_memory_record_failure(request)
    finally:
        await client.aclose()

async def _admin_login_clear_failures(request: Request) -> None:
    _admin_login_memory_clear_failures(request)
    client = await _admin_login_redis_client(request)
    if client is None:
        return
    try:
        await client.delete(_admin_login_redis_key(request))
    except Exception as exc:
        logging.warning(
            "admin_login_redis_clear_failed",
            extra={"context": {"error_type": type(exc).__name__}},
        )
    finally:
        await client.aclose()

def _is_request_secure(request: Request) -> bool:
    proto = request.headers.get("x-forwarded-proto", "").strip().lower()
    if proto == "https":
        return True
    if request.url.scheme == "https":
        return True
    return False

def _trusted_admin_identity(request: Request) -> str | None:
    """Return trusted upstream identity when explicitly enabled."""
    enabled = os.getenv("ADMIN_TRUST_PROXY_IDENTITY", "").strip().lower() in {"1", "true", "yes"}
    if not enabled:
        return None
    for header in _TRUSTED_IDENTITY_HEADERS:
        value = request.headers.get(header, "").strip()
        if value:
            return value
    return None

def _admin_guard(request: Request) -> Response | None:
    """Return redirect response when admin auth is missing."""
    trusted_identity = _trusted_admin_identity(request)
    if trusted_identity:
        csrf_denied = _admin_api_csrf_guard(request)
        if csrf_denied:
            return csrf_denied
        return None

    settings = request.app.state.container.settings
    has_user_pass = bool((settings.auth.admin_username or "").strip() and settings.auth.admin_password)
    if not has_user_pass:
        message = "Admin auth is not configured. Set ADMIN_USERNAME + ADMIN_PASSWORD."
        if _wants_json(request):
            return JSONResponse({"error": message}, status_code=503)
        return HTMLResponse(message, status_code=503)

    cookie_token = request.cookies.get("admin_session", "")
    if cookie_token and _admin_session_valid(request, cookie_token):
        csrf_denied = _admin_api_csrf_guard(request)
        if csrf_denied:
            return csrf_denied
        return None

    if _wants_json(request):
        return JSONResponse({"error": "admin_auth_required"}, status_code=401)
    return RedirectResponse(url="/admin/login", status_code=303)

def _wants_json(request: Request) -> bool:
    if request.headers.get("x-admin-api", "").strip() == "1":
        return True
    return "application/json" in request.headers.get("accept", "").lower()

def _admin_api_csrf_guard(request: Request) -> Response | None:
    """Require a custom header for state-changing admin API calls."""
    if request.method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    if not request.url.path.startswith("/admin/api/"):
        return None
    if request.headers.get("x-admin-api", "").strip() == "1":
        return None
    return JSONResponse({"error": "admin_csrf_required"}, status_code=403)

def _model_upload_error(request: Request, message: str, status_code: int = 400) -> Response:
    if _wants_json(request):
        return JSONResponse(status_code=status_code, content={"ok": False, "message": message})
    return RedirectResponse(
        url=f"/admin/?test_status=error&test_message={quote_plus(message)}",
        status_code=303,
    )

def _model_upload_success(request: Request, message: str, filename_on_disk: str) -> Response:
    if _wants_json(request):
        return JSONResponse(
            status_code=200,
            content={"ok": True, "message": message, "filename": filename_on_disk},
        )
    return RedirectResponse(
        url=f"/admin/?test_status=ok&test_message={quote_plus(message)}",
        status_code=303,
    )

def _write_auto_backup(container, reason: str) -> None:
    """Persist periodic safety snapshot for admin configuration."""
    try:
        _BACKUPS_DIR = Path(container.settings.storage.sqlite_path).parent / "backups"
        _BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        payload = container.db.export_master_setup()
        payload["backup_reason"] = reason
        payload["backup_created_at"] = datetime.now(timezone.utc).isoformat()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        snapshot = _BACKUPS_DIR / f"master-setup-{stamp}.json"
        snapshot.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        (_BACKUPS_DIR / "latest-master-setup.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        snapshots = sorted(_BACKUPS_DIR.glob("master-setup-*.json"), reverse=True)
        for stale in snapshots[20:]:
            stale.unlink(missing_ok=True)
    except Exception as e:
        logging.exception("auto_backup_failed", extra={"context": {"reason": reason, "error": str(e)}})
