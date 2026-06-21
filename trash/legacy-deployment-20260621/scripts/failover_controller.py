#!/usr/bin/env python3
"""Automatic Node B failover controller.

This controller does not guess inside the application. It observes Node A and
Node B health, writes a runtime mode file consumed by the API, and optionally
runs fixed hook commands when entering a mode.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    try:
        value = int(_env(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, value)


@dataclass
class ProbeResult:
    ok: bool
    detail: str


def http_ok(url: str, timeout: int = 5) -> ProbeResult:
    if not url:
        return ProbeResult(False, "url not configured")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read(500).decode("utf-8", errors="replace")
            return ProbeResult(response.status < 500, f"HTTP {response.status}: {body[:180]}")
    except urllib.error.HTTPError as exc:
        return ProbeResult(False, f"HTTP {exc.code}")
    except Exception as exc:
        return ProbeResult(False, f"{type(exc).__name__}: {exc}")


def tcp_ok(host: str, port: int, timeout: int = 5) -> ProbeResult:
    if not host or not port:
        return ProbeResult(False, "tcp target not configured")
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return ProbeResult(True, f"{host}:{port} reachable")
    except Exception as exc:
        return ProbeResult(False, f"{host}:{port} {type(exc).__name__}: {exc}")


def read_mode(path: Path) -> str:
    try:
        if not path.exists():
            return _env("FAILOVER_DEFAULT_MODE", "standby")
        raw = path.read_text(encoding="utf-8").strip()
        if raw.startswith("{"):
            return str(json.loads(raw).get("mode") or "standby")
        return raw or "standby"
    except Exception:
        return "standby"


def write_mode(path: Path, mode: str, reason: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": mode,
        "reason": reason,
        "updated_at": int(time.time()),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def run_hook(mode: str) -> str:
    hook = _env(f"FAILOVER_HOOK_{mode.upper()}")
    if not hook:
        return "no hook configured"
    completed = subprocess.run(
        hook,
        shell=True,
        text=True,
        capture_output=True,
        timeout=_int_env("FAILOVER_HOOK_TIMEOUT_SECONDS", 120),
        check=False,
    )
    output = "\n".join(part for part in [completed.stdout.strip(), completed.stderr.strip()] if part)
    if completed.returncode != 0:
        raise RuntimeError(f"hook failed for {mode}: {output[:1000]}")
    return output[:1000] or "hook ok"


class FailoverController:
    def __init__(self) -> None:
        self.mode_file = Path(_env("FAILOVER_MODE_FILE", "/var/lib/sa-helper/failover-mode.json"))
        self.poll_seconds = _int_env("FAILOVER_POLL_SECONDS", 30)
        self.api_outage_seconds = _int_env("FAILOVER_API_OUTAGE_SECONDS", 600)
        self.full_outage_seconds = _int_env("FAILOVER_FULL_OUTAGE_SECONDS", 1800)
        self.restore_stable_seconds = _int_env("FAILOVER_RESTORE_STABLE_SECONDS", 600)
        self.primary_ready_url = _env("FAILOVER_PRIMARY_READY_URL", "https://tata-ocs.002529.xyz/ready")
        self.primary_health_url = _env("FAILOVER_PRIMARY_HEALTH_URL", "https://tata-ocs.002529.xyz/health")
        self.node_b_health_url = _env("FAILOVER_NODE_B_HEALTH_URL", "http://127.0.0.1:8080/health/public")
        self.primary_db_host = _env("FAILOVER_PRIMARY_DB_HOST", _env("POSTGRES_PRIMARY_HOST", _env("PGHOST")))
        self.primary_db_port = _int_env("FAILOVER_PRIMARY_DB_PORT", _int_env("POSTGRES_PRIMARY_PORT", 15432))
        self.local_db_host = _env("FAILOVER_LOCAL_DB_HOST", _env("EMERGENCY_PGHOST", "127.0.0.1"))
        self.local_db_port = _int_env("FAILOVER_LOCAL_DB_PORT", _int_env("EMERGENCY_PGPORT", 5432))
        now = time.time()
        self.api_down_since: float | None = None
        self.full_down_since: float | None = None
        self.primary_stable_since: float | None = now

    def decide_once(self) -> dict:
        now = time.time()
        primary_ready = http_ok(self.primary_ready_url)
        primary_health = http_ok(self.primary_health_url)
        node_b_health = http_ok(self.node_b_health_url)
        primary_db = tcp_ok(self.primary_db_host, self.primary_db_port)
        local_db = tcp_ok(self.local_db_host, self.local_db_port)

        api_ok = primary_ready.ok and primary_health.ok
        vps_reachable = primary_health.ok or primary_db.ok
        full_down = (not primary_health.ok) and (not primary_db.ok)

        if not api_ok:
            self.api_down_since = self.api_down_since or now
        else:
            self.api_down_since = None

        if full_down:
            self.full_down_since = self.full_down_since or now
        else:
            self.full_down_since = None

        if api_ok and primary_db.ok:
            self.primary_stable_since = self.primary_stable_since or now
        else:
            self.primary_stable_since = None

        current = read_mode(self.mode_file)
        target = current
        reason = "no change"

        if api_ok and primary_db.ok:
            stable_for = now - (self.primary_stable_since or now)
            if current != "standby" and stable_for >= self.restore_stable_seconds:
                target = "standby"
                reason = f"primary stable for {int(stable_for)}s"
            elif current in {"", "normal", "primary"}:
                target = "standby"
                reason = "node b default standby"
        elif full_down:
            down_for = now - (self.full_down_since or now)
            if down_for >= self.full_outage_seconds and local_db.ok and node_b_health.ok:
                target = "failover_readonly"
                reason = f"full vps outage for {int(down_for)}s"
        elif vps_reachable and primary_db.ok and not api_ok:
            down_for = now - (self.api_down_since or now)
            if down_for >= self.api_outage_seconds and node_b_health.ok:
                target = "remote_primary_db"
                reason = f"primary api outage for {int(down_for)}s while primary db reachable"

        hook_result = ""
        if target != current:
            hook_result = run_hook(target)
            write_mode(self.mode_file, target, reason)

        return {
            "current_mode": current,
            "target_mode": target,
            "changed": target != current,
            "reason": reason,
            "hook": hook_result,
            "checks": {
                "primary_ready": primary_ready.__dict__,
                "primary_health": primary_health.__dict__,
                "primary_db": primary_db.__dict__,
                "node_b_health": node_b_health.__dict__,
                "local_db": local_db.__dict__,
            },
            "timers": {
                "api_outage_seconds": self.api_outage_seconds,
                "full_outage_seconds": self.full_outage_seconds,
                "restore_stable_seconds": self.restore_stable_seconds,
                "api_down_for": int(now - self.api_down_since) if self.api_down_since else 0,
                "full_down_for": int(now - self.full_down_since) if self.full_down_since else 0,
                "primary_stable_for": int(now - self.primary_stable_since) if self.primary_stable_since else 0,
            },
        }

    def run_forever(self) -> None:
        while True:
            result = self.decide_once()
            print(json.dumps(result, sort_keys=True), flush=True)
            time.sleep(self.poll_seconds)


def main() -> int:
    controller = FailoverController()
    if _env("FAILOVER_CONTROLLER_ONCE", "").lower() in {"1", "true", "yes", "on"}:
        print(json.dumps(controller.decide_once(), indent=2))
        return 0
    controller.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
