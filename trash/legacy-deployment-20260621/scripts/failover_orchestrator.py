#!/usr/bin/env python3
"""Local Node B failover orchestration for EazyFill.

This script keeps the public automation surface small while adding the local
steps required before Cloudflare is moved to the home tunnel:

- report standby database/cache state,
- promote the local PostgreSQL standby,
- promote the local Redis replica,
- verify the emergency API,
- switch Cloudflare DNS using the fixed DNS switch script.

It intentionally does not merge data back to Node A. After a failover, the Node
B database/cache are disposable and must be rebuilt from Node A before the next
standby window.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class OrchestratorError(RuntimeError):
    pass


@dataclass(frozen=True)
class StepResult:
    name: str
    ok: bool
    detail: str

    def line(self) -> str:
        status = "OK" if self.ok else "FAIL"
        return f"[{status}] {self.name}: {self.detail}"


def _env(name: str, *, default: str = "", required: bool = False) -> str:
    value = os.getenv(name, default).strip()
    if required and not value:
        raise OrchestratorError(f"{name} is required")
    return value


def _int_env(name: str, *, default: int, minimum: int = 1) -> int:
    raw = _env(name, default=str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise OrchestratorError(f"{name} must be an integer") from exc
    if value < minimum:
        raise OrchestratorError(f"{name} must be >= {minimum}")
    return value


def _repo_root() -> Path:
    configured = _env("FAILOVER_BOT_REPO_DIR")
    if configured:
        return Path(configured).resolve()
    return Path(__file__).resolve().parents[1]


def _postgres_dsn() -> str:
    host = _env("EMERGENCY_PGHOST", default="sahelper_emergency_postgres")
    port = _env("EMERGENCY_PGPORT", default="5432")
    database = _env("EMERGENCY_PGDATABASE", required=True)
    user = _env("EMERGENCY_PGUSER", required=True)
    password = _env("EMERGENCY_PGPASSWORD", required=True)
    return f"host={host} port={port} dbname={database} user={user} password={password} connect_timeout=5"


def postgres_status() -> StepResult:
    try:
        import psycopg2

        with psycopg2.connect(_postgres_dsn()) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("SELECT pg_is_in_recovery()")
                in_recovery = bool(cur.fetchone()[0])
                if in_recovery:
                    cur.execute(
                        """
                        SELECT
                            COALESCE(pg_wal_lsn_diff(pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn()), 0)::bigint,
                            pg_last_xact_replay_timestamp()
                        """
                    )
                    lag_bytes, replay_ts = cur.fetchone()
                    detail = f"standby, lag_bytes={lag_bytes}, replay_ts={replay_ts}"
                else:
                    detail = "primary/promoted"
        return StepResult("postgres", True, detail)
    except Exception as exc:
        return StepResult("postgres", False, f"{type(exc).__name__}: {exc}")


def promote_postgres() -> StepResult:
    try:
        import psycopg2

        deadline = time.time() + _int_env("FAILOVER_POSTGRES_PROMOTE_TIMEOUT_SECONDS", default=60)
        with psycopg2.connect(_postgres_dsn()) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("SELECT pg_is_in_recovery()")
                if not bool(cur.fetchone()[0]):
                    return StepResult("postgres_promote", True, "already primary/promoted")
                cur.execute("SELECT pg_promote(wait_seconds => 30)")
                promoted = bool(cur.fetchone()[0])
                if not promoted:
                    return StepResult("postgres_promote", False, "pg_promote returned false")
                while time.time() < deadline:
                    cur.execute("SELECT pg_is_in_recovery()")
                    if not bool(cur.fetchone()[0]):
                        return StepResult("postgres_promote", True, "promoted")
                    time.sleep(1)
        return StepResult("postgres_promote", False, "promotion did not finish before timeout")
    except Exception as exc:
        return StepResult("postgres_promote", False, f"{type(exc).__name__}: {exc}")


def _redis_url() -> str:
    host = _env("EMERGENCY_REDIS_HOST", default="sahelper_emergency_redis")
    port = _env("EMERGENCY_REDIS_PORT", default="6379")
    password = _env("EMERGENCY_REDIS_PASSWORD", required=True)
    return f"redis://:{password}@{host}:{port}/0"


def redis_status() -> StepResult:
    try:
        import redis

        client = redis.Redis.from_url(_redis_url(), socket_connect_timeout=5, socket_timeout=5, decode_responses=True)
        info = client.info("replication")
        role = info.get("role", "unknown")
        master_link = info.get("master_link_status", "n/a")
        offset = info.get("slave_repl_offset", info.get("master_repl_offset", "n/a"))
        return StepResult("redis", True, f"role={role}, master_link={master_link}, offset={offset}")
    except Exception as exc:
        return StepResult("redis", False, f"{type(exc).__name__}: {exc}")


def promote_redis() -> StepResult:
    try:
        import redis

        client = redis.Redis.from_url(_redis_url(), socket_connect_timeout=5, socket_timeout=5, decode_responses=True)
        client.execute_command("REPLICAOF", "NO", "ONE")
        info = client.info("replication")
        role = info.get("role", "unknown")
        if role != "master":
            return StepResult("redis_promote", False, f"expected master after promotion, got role={role}")
        marker = _env("EMERGENCY_REDIS_PROMOTED_MARKER", default="/var/lib/sa-helper-emergency-redis/SA_HELPER_REDIS_PROMOTED")
        marker_path = Path(marker)
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_text(f"promoted_at={int(time.time())}\n", encoding="utf-8")
        return StepResult("redis_promote", True, "promoted to master")
    except Exception as exc:
        return StepResult("redis_promote", False, f"{type(exc).__name__}: {exc}")


def emergency_ready() -> StepResult:
    url = _env("EMERGENCY_READY_URL", default="http://sahelper_emergency_api/ready")
    try:
        with urllib.request.urlopen(url, timeout=_int_env("FAILOVER_READY_TIMEOUT_SECONDS", default=10)) as response:
            body = response.read().decode("utf-8", errors="replace")
            if response.status >= 400:
                return StepResult("emergency_ready", False, f"HTTP {response.status}: {body[:300]}")
            if '"mode":"emergency"' not in body.replace(" ", ""):
                return StepResult("emergency_ready", False, f"ready response did not report emergency mode: {body[:300]}")
            return StepResult("emergency_ready", True, body[:500])
    except urllib.error.URLError as exc:
        return StepResult("emergency_ready", False, str(exc))
    except Exception as exc:
        return StepResult("emergency_ready", False, f"{type(exc).__name__}: {exc}")


def run_cloudflare(action: str, *, runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> StepResult:
    script = _repo_root() / "scripts" / "cloudflare_dns_switch.py"
    completed = runner(
        [sys.executable, str(script), action],
        cwd=str(_repo_root()),
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        timeout=_int_env("FAILOVER_CLOUDFLARE_TIMEOUT_SECONDS", default=60),
        check=False,
    )
    output = "\n".join(part for part in [completed.stdout.strip(), completed.stderr.strip()] if part) or "(no output)"
    return StepResult(f"cloudflare_{action}", completed.returncode == 0, output[:1200])


def _print_results(results: list[StepResult]) -> int:
    for result in results:
        print(result.line())
    return 0 if all(result.ok for result in results) else 2


def action_status() -> int:
    results = [
        postgres_status(),
        redis_status(),
        emergency_ready(),
        run_cloudflare("status"),
    ]
    return _print_results(results)


def action_failover() -> int:
    results = [
        promote_postgres(),
        promote_redis(),
        emergency_ready(),
        run_cloudflare("failover"),
    ]
    return _print_results(results)


def action_normal() -> int:
    results = [run_cloudflare("normal")]
    print(
        "[INFO] node_b_rebuild_required: Node B Postgres/Redis were temporary after failover. "
        "Rebuild the standby from Node A before relying on the next failover."
    )
    return _print_results(results)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EazyFill Node B failover orchestration")
    parser.add_argument("action", choices=["status", "failover", "normal"])
    args = parser.parse_args(argv)

    try:
        if args.action == "status":
            return action_status()
        if args.action == "failover":
            return action_failover()
        return action_normal()
    except OrchestratorError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
