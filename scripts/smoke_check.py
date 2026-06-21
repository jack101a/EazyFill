#!/usr/bin/env python3
"""Production smoke checks for a deployed EazyFill stack.

This script uses only the Python standard library so it can run on a fresh
server without installing project dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from typing import Any


class SmokeFailure(RuntimeError):
    pass


def _base_url(value: str) -> str:
    return value.strip().rstrip("/")


def _request_json(
    opener: urllib.request.OpenerDirector,
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: float = 5.0,
) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return int(response.status), json.loads(raw or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            payload = {"error": raw[:200]}
        return int(exc.code), payload


def _request_form(
    opener: urllib.request.OpenerDirector,
    url: str,
    fields: dict[str, str],
    *,
    timeout: float = 5.0,
) -> int:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            response.read()
            return int(response.status)
    except urllib.error.HTTPError as exc:
        exc.read()
        return int(exc.code)


def _status_line(name: str, state: str, detail: str = "") -> None:
    suffix = f" - {detail}" if detail else ""
    print(f"[{state}] {name}{suffix}")


def _require_http_ok(name: str, status_code: int, payload: dict[str, Any]) -> None:
    if status_code < 200 or status_code >= 300:
        raise SmokeFailure(f"{name} returned HTTP {status_code}: {payload}")


def _check_public_health(opener: urllib.request.OpenerDirector, base_url: str, timeout: float) -> None:
    status_code, payload = _request_json(opener, f"{base_url}/health", timeout=timeout)
    _require_http_ok("/health", status_code, payload)
    if payload.get("status") != "ok":
        raise SmokeFailure(f"/health returned unexpected status: {payload}")
    _status_line("/health", "OK", f"service={payload.get('service', '-')}")


def _check_readiness(opener: urllib.request.OpenerDirector, base_url: str, timeout: float) -> dict[str, Any]:
    status_code, payload = _request_json(opener, f"{base_url}/ready", timeout=timeout)
    if status_code == 503:
        raise SmokeFailure(f"/ready reports critical failure: {payload}")
    _require_http_ok("/ready", status_code, payload)

    status = str(payload.get("status") or "unknown")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if status == "ok":
        _status_line("/ready", "OK", "all critical checks healthy")
    elif status == "degraded":
        _status_line("/ready", "WARN", "noncritical service degraded")
    else:
        raise SmokeFailure(f"/ready returned unexpected status: {payload}")

    for name, check in checks.items():
        if not isinstance(check, dict):
            continue
        bits = [str(check.get("status") or "unknown")]
        if check.get("backend"):
            bits.append(f"backend={check['backend']}")
        if check.get("mode"):
            bits.append(f"mode={check['mode']}")
        if check.get("pending_jobs") is not None:
            bits.append(f"pending={check['pending_jobs']}")
        if check.get("latency_ms") is not None:
            bits.append(f"{check['latency_ms']}ms")
        _status_line(f"ready.{name}", "OK" if check.get("status") == "ok" else "WARN", ", ".join(bits))
    return payload


def _check_admin_health(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    timeout: float,
    username: str,
    password: str,
) -> None:
    if not username or not password:
        _status_line("admin health", "SKIP", "set ADMIN_USERNAME and ADMIN_PASSWORD to enable")
        return

    login_status = _request_form(
        opener,
        f"{base_url}/admin/login",
        {"admin_username": username, "admin_password": password},
        timeout=timeout,
    )
    if login_status not in {200, 303}:
        raise SmokeFailure(f"admin login failed with HTTP {login_status}")

    status_code, payload = _request_json(
        opener,
        f"{base_url}/admin/api/system/health",
        headers={"Accept": "application/json", "X-Admin-API": "1"},
        timeout=timeout,
    )
    _require_http_ok("admin system health", status_code, payload)
    readiness_status = (payload.get("readiness") or {}).get("status", "unknown")
    _status_line(
        "admin system health",
        "OK" if readiness_status in {"ok", "degraded"} else "WARN",
        f"users={payload.get('users', {}).get('total', '-')}, readiness={readiness_status}",
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test a deployed EazyFill stack.")
    parser.add_argument("--base-url", default=os.getenv("EAZYFILL_BASE_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--admin-username", default=os.getenv("ADMIN_USERNAME", ""))
    parser.add_argument("--admin-password", default=os.getenv("ADMIN_PASSWORD", ""))
    parser.add_argument("--timeout", type=float, default=float(os.getenv("SMOKE_TIMEOUT_SECONDS", "5") or "5"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    base_url = _base_url(args.base_url)
    cookie_jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    started = time.perf_counter()

    try:
        _check_public_health(opener, base_url, args.timeout)
        _check_readiness(opener, base_url, args.timeout)
        _check_admin_health(opener, base_url, args.timeout, args.admin_username, args.admin_password)
    except (SmokeFailure, urllib.error.URLError, TimeoutError, OSError) as exc:
        _status_line("smoke check", "FAIL", str(exc))
        return 1

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    _status_line("smoke check", "OK", f"completed in {elapsed_ms}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
