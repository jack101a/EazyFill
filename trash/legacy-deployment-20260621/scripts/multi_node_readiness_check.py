"""Check whether the repo is ready for multi-node production deployment.

This script is intentionally conservative. Code/config readiness is separate
from live staging validation; extra gateways should not receive real traffic
until live PostgreSQL, artifact, Razorpay replay, and failover/load tests pass.
"""

from __future__ import annotations

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
REPOSITORIES = ROOT / "backend" / "app" / "core" / "repositories"
MIGRATIONS = ROOT / "backend" / "migrations" / "versions"
LEGACY_POSTGRES_ADAPTER = ROOT / "backend" / "app" / "core" / "legacy_postgres.py"
NODE_A_ENV_EXAMPLE = ROOT / ".env.node-a.example"
NODE_B_ENV_EXAMPLE = ROOT / ".env.node-b.example"
NODE_A_COMPOSE = ROOT / "docker-compose.node-a.yml"
NODE_B_COMPOSE = ROOT / "docker-compose.node-b.yml"


def count_legacy_raw_sql() -> int:
    count = 0
    for path in REPOSITORIES.glob("*.py"):
        if path.name == "base.py":
            continue
        text = path.read_text(encoding="utf-8")
        count += text.count("conn.execute(")
    return count


def migration_heads() -> list[str]:
    revisions: dict[str, str | None] = {}
    referenced: set[str] = set()
    for path in MIGRATIONS.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        revision_match = re.search(r"^revision:\s*str\s*=\s*[\"']([^\"']+)[\"']", text, flags=re.MULTILINE)
        down_match = re.search(r"^down_revision:[^\n=]*=\s*([^\n]+)", text, flags=re.MULTILINE)
        if not revision_match:
            continue
        revision = revision_match.group(1)
        down_revision: str | None = None
        if down_match:
            raw = down_match.group(1).strip()
            quoted = re.findall(r"[\"']([^\"']+)[\"']", raw)
            if quoted:
                down_revision = quoted[0]
                referenced.update(quoted)
        revisions[revision] = down_revision
    return sorted(set(revisions) - referenced)


def legacy_baseline_uses_sqlite_only_ddl() -> bool:
    path = MIGRATIONS / "e6a1c9b2d101_full_schema_baseline.py"
    if not path.exists():
        return True
    text = path.read_text(encoding="utf-8")
    blocked_tokens = ["AUTOINCREMENT", "INSERT OR IGNORE", "sqlite_master", "PRAGMA table_info"]
    return any(token in text for token in blocked_tokens)


def file_contains(path: Path, token: str) -> bool:
    return path.exists() and token in path.read_text(encoding="utf-8")


def production_configs_default_to_postgres() -> bool:
    env_ready = (
        file_contains(NODE_A_ENV_EXAMPLE, "LEGACY_DB_TYPE=postgresql")
        and file_contains(NODE_B_ENV_EXAMPLE, "LEGACY_DB_TYPE=postgresql")
    )
    node_a_compose = NODE_A_COMPOSE.read_text(encoding="utf-8") if NODE_A_COMPOSE.exists() else ""
    node_b_compose = NODE_B_COMPOSE.read_text(encoding="utf-8") if NODE_B_COMPOSE.exists() else ""
    node_a_maps_legacy = (
        "LEGACY_DB_TYPE: ${LEGACY_DB_TYPE:-postgresql}" in node_a_compose
        or "LEGACY_DB_TYPE: ${LEGACY_DB_TYPE}" in node_a_compose
    )
    node_b_maps_legacy = (
        "LEGACY_DB_TYPE: ${LEGACY_DB_TYPE:-postgresql}" in node_b_compose
        or "LEGACY_DB_TYPE: ${LEGACY_DB_TYPE}" in node_b_compose
    )
    compose_ready = (
        "LEGACY_DB_TYPE: sqlite" not in node_a_compose
        and "LEGACY_DB_TYPE: sqlite" not in node_b_compose
        and node_a_maps_legacy
        and node_b_maps_legacy
    )
    return env_ready and compose_ready


def live_validation_marker_present() -> bool:
    return (ROOT / "reports" / "multi_node_live_validation.json").exists()


def main() -> int:
    raw_sql_call_sites = count_legacy_raw_sql()
    heads = migration_heads()
    migration_graph_ready = len(heads) == 1 and not legacy_baseline_uses_sqlite_only_ddl()
    legacy_postgres_adapter_present = LEGACY_POSTGRES_ADAPTER.exists()
    production_config_ready = production_configs_default_to_postgres()
    worker_ready = migration_graph_ready and production_config_ready and legacy_postgres_adapter_present
    staging_validated = live_validation_marker_present()
    ready = worker_ready and staging_validated
    payload = {
        "multi_gateway_ready": ready,
        "worker_node_ready": worker_ready,
        "migration_graph_ready": migration_graph_ready,
        "alembic_heads": heads,
        "legacy_baseline_postgres_portable": not legacy_baseline_uses_sqlite_only_ddl(),
        "legacy_postgres_adapter_present": legacy_postgres_adapter_present,
        "production_configs_default_to_postgres": production_config_ready,
        "live_validation_marker_present": staging_validated,
        "legacy_raw_sql_call_sites": raw_sql_call_sites,
        "required_before_multi_gateway": [
            "Live-test LEGACY_DB_TYPE=postgresql against real PostgreSQL before enabling gateway replicas",
            "Replay Razorpay captured-payment webhooks in staging",
            "Move runtime uploads/generated artifacts to shared storage",
            "Pass failover/load tests with at least two API gateways",
            "Write reports/multi_node_live_validation.json after the live validation run",
        ] if not ready else [],
    }
    print(json.dumps(payload, indent=2))
    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
