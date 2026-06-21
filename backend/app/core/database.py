"""Operational database access layer - facade pattern."""

from __future__ import annotations

import sqlite3
import threading
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit

from app.core.config import Settings
from app.core.repositories.api_keys import APIKeyRepository
from app.core.repositories.models import ModelRepository
from app.core.repositories.training import TrainingRepository
from app.core.repositories.settings import SettingsRepository
from app.core.sqlite import sqlite_connect
from app.core.legacy_postgres import legacy_postgres_connect

logger = logging.getLogger(__name__)


class Database:
    """Thread-safe database facade for operational repositories."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        raw_legacy_db_type = os.getenv("LEGACY_DB_TYPE")
        if raw_legacy_db_type is None:
            raw_setting_db_type = getattr(settings.storage, "db_type", "sqlite")
            raw_legacy_db_type = raw_setting_db_type if isinstance(raw_setting_db_type, str) else "sqlite"
        self._legacy_db_type = str(raw_legacy_db_type or "sqlite").strip().lower()
        self._path = Path(settings.storage.sqlite_path)
        self._lock = threading.Lock()
        if self._legacy_db_type == "sqlite":
            self._path.parent.mkdir(parents=True, exist_ok=True)

        self.api_keys = APIKeyRepository(self)
        self.models = ModelRepository(self)
        self.training = TrainingRepository(self)
        self.settings = SettingsRepository(self)

    @staticmethod
    def _normalize_domain(domain: str | None) -> str:
        token = str(domain or "").strip().lower()
        if not token:
            return ""
        if "://" in token:
            try:
                token = urlsplit(token).hostname or token
            except Exception:
                pass
        token = token.split("/", 1)[0].split(":", 1)[0].strip(".")
        if token.startswith("www."):
            token = token[4:]
        return token

    @classmethod
    def _domain_candidates(cls, domain: str | None) -> list[str]:
        normalized = cls._normalize_domain(domain)
        if not normalized:
            return []
        out: list[str] = []
        seen: set[str] = set()

        def _add(value: str) -> None:
            if value and value not in seen:
                seen.add(value)
                out.append(value)

        _add(normalized)
        _add(f"www.{normalized}")
        labels = normalized.split(".")
        for idx in range(1, len(labels) - 1):
            suffix = ".".join(labels[idx:])
            _add(suffix)
            _add(f"www.{suffix}")
        return out

    @contextmanager
    def connect(self) -> Iterator[Any]:
        """
        Yield a sqlite3 connection with row_factory set.

        WAL mode is enabled on each connection so concurrent readers never
        block a writer. Repositories are responsible for calling
        ``conn.commit()`` after writes; reads need no commit.
        """
        if self._legacy_db_type == "postgresql":
            database_url = self._settings.storage.database_url or os.getenv("DATABASE_URL", "")
            if not database_url:
                raise RuntimeError("DATABASE_URL is required when LEGACY_DB_TYPE=postgresql")
            connection = legacy_postgres_connect(database_url)
            try:
                yield connection
            finally:
                connection.close()
            return

        connection = sqlite_connect(self._path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def init(self) -> None:
        """Initialize database connection. Schema is managed by Alembic migrations."""
        instance_id = os.getenv("INSTANCE_ID", "").strip().lower()
        app_env = os.getenv("APP_ENV", "").strip().lower()
        production_sqlite_allowed = os.getenv("ALLOW_PRODUCTION_SQLITE_GATEWAY", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if (
            self._legacy_db_type == "sqlite"
            and app_env == "production"
            and "gateway" in instance_id
            and not production_sqlite_allowed
        ):
            raise RuntimeError(
                "Refusing to start a production gateway with LEGACY_DB_TYPE=sqlite. "
                "Use LEGACY_DB_TYPE=postgresql for multi-node production deployments."
            )
        if self._legacy_db_type == "postgresql":
            self._validate_postgres_legacy_schema()
            if not self._skip_master_key_ensure():
                self.api_keys.ensure_master_key()
            return
        if self._legacy_db_type != "sqlite":
            raise RuntimeError(
                "LEGACY_DB_TYPE must be either sqlite or postgresql."
            )
        replica_allowed = os.getenv("ALLOW_SQLITE_GATEWAY_REPLICA", "").strip().lower() in {"1", "true", "yes", "on"}
        if not replica_allowed and self._legacy_db_type == "sqlite" and any(token in instance_id for token in ("gateway-2", "gateway-3")):
            raise RuntimeError(
                "Refusing to start an extra gateway with LEGACY_DB_TYPE=sqlite. "
                "Use LEGACY_DB_TYPE=postgresql before running gateway replicas."
            )
        with self._lock:
            with self.connect() as conn:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }

                required = {"api_keys", "platform_settings", "model_routes"}
                missing = required - tables
                if missing:
                    logger.warning(
                        "missing_tables_fallback",
                        extra={"context": {"missing": sorted(missing)}},
                    )
                self._create_tables_fallback(conn)

        # Ensure the master key is created on first start
        if not self._skip_master_key_ensure():
            self.api_keys.ensure_master_key()

    @staticmethod
    def _skip_master_key_ensure() -> bool:
        raw = os.getenv(
            "EAZYFILL_SKIP_MASTER_KEY_ENSURE",
            os.getenv("SA_HELPER_SKIP_MASTER_KEY_ENSURE", ""),
        )
        return raw.strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    def _validate_postgres_legacy_schema(self) -> None:
        required = {
            "api_keys",
            "platform_settings",
            "model_routes",
            "model_registry",
            "field_mappings",
        }
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                """
            ).fetchall()
        present = {str(row["table_name"]) for row in rows}
        missing = required - present
        if missing:
            raise RuntimeError(
                "PostgreSQL legacy schema is missing required tables. "
                "Run `cd backend && python -m alembic upgrade head` first. "
                f"Missing: {', '.join(sorted(missing))}"
            )

    def _create_tables_fallback(self, conn: sqlite3.Connection) -> None:
        """Fallback table creation for dev environments without Alembic."""
        conn.executescript(
            """
                    CREATE TABLE IF NOT EXISTS api_keys (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        key_hash TEXT NOT NULL UNIQUE,
                        enabled INTEGER NOT NULL DEFAULT 1,
                        all_domains INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL,
                        expires_at TEXT,
                        revoked_at TEXT
                    );

                    CREATE TABLE IF NOT EXISTS api_key_allowed_domains (
                        key_id INTEGER NOT NULL,
                        domain TEXT NOT NULL,
                        PRIMARY KEY (key_id, domain),
                        FOREIGN KEY(key_id) REFERENCES api_keys(id)
                    );

                    CREATE TABLE IF NOT EXISTS api_key_rate_limits (
                        key_id INTEGER PRIMARY KEY,
                        requests_per_minute INTEGER NOT NULL,
                        burst INTEGER NOT NULL DEFAULT 0,
                        FOREIGN KEY(key_id) REFERENCES api_keys(id)
                    );

                    CREATE TABLE IF NOT EXISTS api_key_device_bindings (
                        key_id INTEGER PRIMARY KEY,
                        device_id TEXT NOT NULL,
                        user_agent TEXT,
                        first_seen_at TEXT NOT NULL,
                        last_seen_at TEXT NOT NULL,
                        FOREIGN KEY(key_id) REFERENCES api_keys(id)
                    );

                    CREATE TABLE IF NOT EXISTS usage_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        key_id INTEGER NOT NULL,
                        task_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        processing_ms INTEGER NOT NULL,
                        model_used TEXT,
                        domain TEXT,
                        ip TEXT,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(key_id) REFERENCES api_keys(id)
                    );

                    CREATE TABLE IF NOT EXISTS model_routes (
                        domain TEXT PRIMARY KEY,
                        ai_model_filename TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS model_registry (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ai_model_name TEXT NOT NULL,
                        version TEXT NOT NULL,
                        task_type TEXT NOT NULL,
                        ai_runtime TEXT NOT NULL DEFAULT 'onnx',
                        ai_model_filename TEXT NOT NULL UNIQUE,
                        status TEXT NOT NULL DEFAULT 'active',
                        lifecycle_state TEXT NOT NULL DEFAULT 'production',
                        notes TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS field_mappings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        domain TEXT NOT NULL,
                        field_name TEXT NOT NULL,
                        task_type TEXT NOT NULL,
                        source_data_type TEXT NOT NULL DEFAULT 'image',
                        source_selector TEXT NOT NULL DEFAULT '',
                        target_data_type TEXT NOT NULL DEFAULT 'text',
                        target_selector TEXT NOT NULL DEFAULT '',
                        ai_model_id INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        UNIQUE(domain, field_name, task_type),
                        FOREIGN KEY(ai_model_id) REFERENCES model_registry(id)
                    );

                    CREATE TABLE IF NOT EXISTS field_mapping_proposals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        domain TEXT NOT NULL,
                        task_type TEXT NOT NULL,
                        source_data_type TEXT NOT NULL,
                        source_selector TEXT NOT NULL,
                        target_data_type TEXT NOT NULL,
                        target_selector TEXT NOT NULL,
                        proposed_field_name TEXT NOT NULL,
                        reported_by INTEGER,
                        reported_by_kind TEXT NOT NULL DEFAULT 'legacy_api_key',
                        reported_by_user_id INTEGER,
                        status TEXT NOT NULL DEFAULT 'pending',
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS retrain_samples (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        domain TEXT NOT NULL,
                        image_path TEXT NOT NULL,
                        task_type TEXT NOT NULL DEFAULT 'image',
                        field_name TEXT,
                        reported_by INTEGER,
                        reported_by_kind TEXT NOT NULL DEFAULT 'legacy_api_key',
                        reported_by_user_id INTEGER,
                        status TEXT NOT NULL DEFAULT 'queued',
                        label_text TEXT,
                        labeled_by INTEGER,
                        labeled_at TEXT,
                        consumed_by_job_id INTEGER,
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS retrain_jobs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        status TEXT NOT NULL DEFAULT 'queued',
                        scheduled_for TEXT NOT NULL,
                        started_at TEXT,
                        finished_at TEXT,
                        requested_by INTEGER,
                        min_samples INTEGER NOT NULL DEFAULT 20,
                        notes TEXT,
                        error_message TEXT,
                        produced_ai_model_id INTEGER,
                        total_samples INTEGER NOT NULL DEFAULT 0
                    );

                    CREATE TABLE IF NOT EXISTS model_lifecycle_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ai_model_id INTEGER NOT NULL,
                        from_state TEXT,
                        to_state TEXT NOT NULL,
                        reason TEXT,
                        changed_by INTEGER,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(ai_model_id) REFERENCES model_registry(id)
                    );

                    CREATE TABLE IF NOT EXISTS active_learning (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        domain TEXT NOT NULL,
                        image_path TEXT NOT NULL,
                        reported_by INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(reported_by) REFERENCES api_keys(id)
                    );

                    CREATE TABLE IF NOT EXISTS access_control (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS allowed_domains (
                        domain TEXT PRIMARY KEY
                    );

                    CREATE TABLE IF NOT EXISTS failed_payload_labels (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        filename TEXT NOT NULL UNIQUE,
                        domain TEXT NOT NULL,
                        ai_guess TEXT,
                        corrected_text TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS platform_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL DEFAULT '',
                        description TEXT,
                        updated_at TEXT NOT NULL
                    );

                """
        )
        # ── Column migrations (idempotent) ─────────────────────────
        usage_columns = {row["name"] for row in conn.execute("PRAGMA table_info(usage_events)")}
        if "model_used" not in usage_columns:
            conn.execute("ALTER TABLE usage_events ADD COLUMN model_used TEXT")
        if "domain" not in usage_columns:
            conn.execute("ALTER TABLE usage_events ADD COLUMN domain TEXT")
        if "ip" not in usage_columns:
            conn.execute("ALTER TABLE usage_events ADD COLUMN ip TEXT")

        key_columns = {row["name"] for row in conn.execute("PRAGMA table_info(api_keys)")}
        if "all_domains" not in key_columns:
            conn.execute("ALTER TABLE api_keys ADD COLUMN all_domains INTEGER NOT NULL DEFAULT 1")
        if "key_type" not in key_columns:
            conn.execute("ALTER TABLE api_keys ADD COLUMN key_type TEXT NOT NULL DEFAULT 'user'")
        if "plan_name" not in key_columns:
            conn.execute("ALTER TABLE api_keys ADD COLUMN plan_name TEXT NOT NULL DEFAULT 'Standard'")
        if "mobile" not in key_columns:
            conn.execute("ALTER TABLE api_keys ADD COLUMN mobile TEXT NOT NULL DEFAULT ''")
        if "services_json" not in key_columns:
            conn.execute("ALTER TABLE api_keys ADD COLUMN services_json TEXT NOT NULL DEFAULT '{\"autofill\":true,\"captcha\":true,\"userscripts\":true,\"sync\":true,\"priority_solving\":false,\"unlimited_rules\":false,\"js_rules\":false}'")
        if "last_used_at" not in key_columns:
            conn.execute("ALTER TABLE api_keys ADD COLUMN last_used_at TEXT")
        if "usage_count" not in key_columns:
            conn.execute("ALTER TABLE api_keys ADD COLUMN usage_count INTEGER NOT NULL DEFAULT 0")

        plan_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='subscription_plans'"
        ).fetchone()
        if plan_table:
            plan_columns = {row["name"] for row in conn.execute("PRAGMA table_info(subscription_plans)")}
            legacy_visibility_column = "show_in_" + "bot"
            if legacy_visibility_column in plan_columns and "show_in_checkout" not in plan_columns:
                conn.execute(
                    f"ALTER TABLE subscription_plans RENAME COLUMN {legacy_visibility_column} TO show_in_checkout"
                )
                plan_columns = {row["name"] for row in conn.execute("PRAGMA table_info(subscription_plans)")}
            if "show_in_checkout" not in plan_columns:
                conn.execute("ALTER TABLE subscription_plans ADD COLUMN show_in_checkout INTEGER NOT NULL DEFAULT 1")
            if "is_promo" not in plan_columns:
                conn.execute("ALTER TABLE subscription_plans ADD COLUMN is_promo INTEGER NOT NULL DEFAULT 0")
            if "promo_audience" not in plan_columns:
                conn.execute("ALTER TABLE subscription_plans ADD COLUMN promo_audience TEXT NOT NULL DEFAULT 'both'")

        route_columns = {row["name"] for row in conn.execute("PRAGMA table_info(model_routes)")}
        if "model_filename" in route_columns and "ai_model_filename" not in route_columns:
            conn.execute("ALTER TABLE model_routes RENAME COLUMN model_filename TO ai_model_filename")

        registry_columns = {row["name"] for row in conn.execute("PRAGMA table_info(model_registry)")}
        if "model_name" in registry_columns and "ai_model_name" not in registry_columns:
            conn.execute("ALTER TABLE model_registry RENAME COLUMN model_name TO ai_model_name")
        if "runtime" in registry_columns and "ai_runtime" not in registry_columns:
            conn.execute("ALTER TABLE model_registry RENAME COLUMN runtime TO ai_runtime")
        if "filename" in registry_columns and "ai_model_filename" not in registry_columns:
            conn.execute("ALTER TABLE model_registry RENAME COLUMN filename TO ai_model_filename")
        # Re-read after possible renames
        registry_columns = {row["name"] for row in conn.execute("PRAGMA table_info(model_registry)")}
        if "lifecycle_state" not in registry_columns:
            conn.execute("ALTER TABLE model_registry ADD COLUMN lifecycle_state TEXT NOT NULL DEFAULT 'production'")

        mapping_columns = {row["name"] for row in conn.execute("PRAGMA table_info(field_mappings)")}
        if "model_id" in mapping_columns and "ai_model_id" not in mapping_columns:
            conn.execute("ALTER TABLE field_mappings RENAME COLUMN model_id TO ai_model_id")
        # Re-read after possible rename
        mapping_columns = {row["name"] for row in conn.execute("PRAGMA table_info(field_mappings)")}
        if "source_data_type" not in mapping_columns:
            conn.execute("ALTER TABLE field_mappings ADD COLUMN source_data_type TEXT NOT NULL DEFAULT 'image'")
        if "source_selector" not in mapping_columns:
            conn.execute("ALTER TABLE field_mappings ADD COLUMN source_selector TEXT NOT NULL DEFAULT ''")
        if "target_data_type" not in mapping_columns:
            conn.execute("ALTER TABLE field_mappings ADD COLUMN target_data_type TEXT NOT NULL DEFAULT 'text'")
        if "target_selector" not in mapping_columns:
            conn.execute("ALTER TABLE field_mappings ADD COLUMN target_selector TEXT NOT NULL DEFAULT ''")

        self._migrate_reporter_tables(conn)

        # ── Performance indexes ──────────────────────────────
        conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_task_status ON usage_events(task_type, status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_key_id ON usage_events(key_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_task_created ON usage_events(task_type, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_field_proposals_status ON field_mapping_proposals(status)")
        conn.execute("INSERT OR IGNORE INTO access_control (key, value) VALUES ('global_access', 'true')")
        conn.commit()

    def _migrate_reporter_tables(self, conn: sqlite3.Connection) -> None:
        """Allow route learning rows to be reported by legacy keys or v2 user keys."""
        self._migrate_reporter_table(
            conn,
            table_name="field_mapping_proposals",
            columns_sql="""
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT NOT NULL,
                task_type TEXT NOT NULL,
                source_data_type TEXT NOT NULL,
                source_selector TEXT NOT NULL,
                target_data_type TEXT NOT NULL,
                target_selector TEXT NOT NULL,
                proposed_field_name TEXT NOT NULL,
                reported_by INTEGER,
                reported_by_kind TEXT NOT NULL DEFAULT 'legacy_api_key',
                reported_by_user_id INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL
            """,
            copy_columns=[
                "id",
                "domain",
                "task_type",
                "source_data_type",
                "source_selector",
                "target_data_type",
                "target_selector",
                "proposed_field_name",
                "reported_by",
                "reported_by_kind",
                "reported_by_user_id",
                "status",
                "created_at",
            ],
        )
        self._migrate_reporter_table(
            conn,
            table_name="retrain_samples",
            columns_sql="""
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT NOT NULL,
                image_path TEXT NOT NULL,
                task_type TEXT NOT NULL DEFAULT 'image',
                field_name TEXT,
                reported_by INTEGER,
                reported_by_kind TEXT NOT NULL DEFAULT 'legacy_api_key',
                reported_by_user_id INTEGER,
                status TEXT NOT NULL DEFAULT 'queued',
                label_text TEXT,
                labeled_by INTEGER,
                labeled_at TEXT,
                consumed_by_job_id INTEGER,
                created_at TEXT NOT NULL
            """,
            copy_columns=[
                "id",
                "domain",
                "image_path",
                "task_type",
                "field_name",
                "reported_by",
                "reported_by_kind",
                "reported_by_user_id",
                "status",
                "label_text",
                "labeled_by",
                "labeled_at",
                "consumed_by_job_id",
                "created_at",
            ],
        )

    def _migrate_reporter_table(
        self,
        conn: sqlite3.Connection,
        *,
        table_name: str,
        columns_sql: str,
        copy_columns: list[str],
    ) -> None:
        table_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
            (table_name,),
        ).fetchone()
        if not table_exists:
            return

        existing_columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})")}
        for column_sql in (
            "reported_by_kind TEXT NOT NULL DEFAULT 'legacy_api_key'",
            "reported_by_user_id INTEGER",
        ):
            column_name = column_sql.split()[0]
            if column_name not in existing_columns:
                conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")
                existing_columns.add(column_name)

        foreign_keys = [
            dict(row) for row in conn.execute(f"PRAGMA foreign_key_list({table_name})")
        ]
        has_legacy_reporter_fk = any(
            row.get("from") == "reported_by" and row.get("table") == "api_keys"
            for row in foreign_keys
        )
        if not has_legacy_reporter_fk:
            return

        backup_name = f"{table_name}_legacy_reporter_fk"
        conn.execute(f"ALTER TABLE {table_name} RENAME TO {backup_name}")
        conn.execute(f"CREATE TABLE {table_name} ({columns_sql})")

        backup_columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({backup_name})")}
        select_parts = []
        for column in copy_columns:
            if column in backup_columns:
                select_parts.append(column)
            elif column == "reported_by_kind":
                select_parts.append("'legacy_api_key' AS reported_by_kind")
            else:
                select_parts.append(f"NULL AS {column}")
        conn.execute(
            f"""
            INSERT INTO {table_name} ({", ".join(copy_columns)})
            SELECT {", ".join(select_parts)}
            FROM {backup_name}
            """
        )
        conn.execute(f"DROP TABLE {backup_name}")

    # --- Proxy Methods for Backward Compatibility ---

    # Settings
    def get_setting(self, *args, **kwargs): return self.settings.get_setting(*args, **kwargs)
    def set_setting(self, *args, **kwargs): return self.settings.set_setting(*args, **kwargs)
    def get_all_settings(self, *args, **kwargs): return self.settings.get_all_settings(*args, **kwargs)
    def get_global_access(self, *args, **kwargs): return self.settings.get_global_access(*args, **kwargs)
    def set_global_access(self, *args, **kwargs): return self.settings.set_global_access(*args, **kwargs)
    def get_allowed_domains(self, *args, **kwargs): return self.settings.get_allowed_domains(*args, **kwargs)
    def is_domain_allowed(self, *args, **kwargs): return self.settings.is_domain_allowed(*args, **kwargs)
    def add_allowed_domain(self, *args, **kwargs): return self.settings.add_allowed_domain(*args, **kwargs)
    def remove_allowed_domain(self, *args, **kwargs): return self.settings.remove_allowed_domain(*args, **kwargs)
    def export_master_setup(self, *args, **kwargs): return self.settings.export_master_setup(*args, **kwargs)
    def import_master_setup(self, *args, **kwargs): return self.settings.import_master_setup(*args, **kwargs)

    # API Keys
    def insert_api_key(self, *args, **kwargs): return self.api_keys.insert_api_key(*args, **kwargs)
    def get_api_key_by_hash(self, *args, **kwargs): return self.api_keys.get_api_key_by_hash(*args, **kwargs)
    def revoke_api_key(self, *args, **kwargs): return self.api_keys.revoke_api_key(*args, **kwargs)
    def revoke_api_key_by_id(self, *args, **kwargs): return self.api_keys.revoke_api_key_by_id(*args, **kwargs)
    def delete_revoked_api_key_by_id(self, *args, **kwargs): return self.api_keys.delete_revoked_api_key_by_id(*args, **kwargs)
    def delete_revoked_api_keys(self, *args, **kwargs): return self.api_keys.delete_revoked_api_keys(*args, **kwargs)
    def insert_usage_event(self, *args, **kwargs): return self.api_keys.insert_usage_event(*args, **kwargs)
    def get_usage_summary(self, *args, **kwargs): return self.api_keys.get_usage_summary(*args, **kwargs)
    def get_all_api_keys(self, *args, **kwargs): return self.api_keys.get_all_api_keys(*args, **kwargs)
    def set_api_key_domain_scope(self, *args, **kwargs): return self.api_keys.set_api_key_domain_scope(*args, **kwargs)
    def get_api_key_allowed_domains(self, *args, **kwargs): return self.api_keys.get_api_key_allowed_domains(*args, **kwargs)
    def is_domain_allowed_for_key(self, *args, **kwargs): return self.api_keys.is_domain_allowed_for_key(*args, **kwargs)
    def set_api_key_rate_limit(self, *args, **kwargs): return self.api_keys.set_api_key_rate_limit(*args, **kwargs)
    def get_api_key_rate_limit(self, *args, **kwargs): return self.api_keys.get_api_key_rate_limit(*args, **kwargs)
    def set_api_key_entitlements(self, *args, **kwargs): return self.api_keys.set_api_key_entitlements(*args, **kwargs)
    def get_api_key_entitlements(self, *args, **kwargs): return self.api_keys.get_api_key_entitlements(*args, **kwargs)
    def validate_or_bind_key_device(self, *args, **kwargs): return self.api_keys.validate_or_bind_key_device(*args, **kwargs)
    def get_api_key_device_binding(self, *args, **kwargs): return self.api_keys.get_api_key_device_binding(*args, **kwargs)
    def ensure_master_key(self, *args, **kwargs): return self.api_keys.ensure_master_key(*args, **kwargs)
    def get_master_key_info(self, *args, **kwargs): return self.api_keys.get_master_key_info(*args, **kwargs)
    def set_master_key_enabled(self, *args, **kwargs): return self.api_keys.set_master_key_enabled(*args, **kwargs)
    def is_master_key_hash(self, *args, **kwargs): return self.api_keys.is_master_key_hash(*args, **kwargs)

    # Models
    def get_model_route(self, *args, **kwargs): return self.models.get_model_route(*args, **kwargs)
    def set_model_route(self, *args, **kwargs): return self.models.set_model_route(*args, **kwargs)
    def get_all_model_routes(self, *args, **kwargs): return self.models.get_all_model_routes(*args, **kwargs)
    def add_model_registry_entry(self, *args, **kwargs): return self.models.add_model_registry_entry(*args, **kwargs)
    def get_model_registry(self, *args, **kwargs): return self.models.get_model_registry(*args, **kwargs)
    def get_model_registry_entry(self, *args, **kwargs): return self.models.get_model_registry_entry(*args, **kwargs)
    def delete_model_registry_entry(self, *args, **kwargs): return self.models.delete_model_registry_entry(*args, **kwargs)
    def update_model_registry_entry(self, *args, **kwargs): return self.models.update_model_registry_entry(*args, **kwargs)
    def set_field_mapping(self, *args, **kwargs): return self.models.set_field_mapping(*args, **kwargs)
    def remove_field_mapping(self, *args, **kwargs): return self.models.remove_field_mapping(*args, **kwargs)
    def update_field_mapping(self, *args, **kwargs): return self.models.update_field_mapping(*args, **kwargs)
    def rename_domain_mappings(self, *args, **kwargs): return self.models.rename_domain_mappings(*args, **kwargs)
    def assign_model_to_domain(self, *args, **kwargs): return self.models.assign_model_to_domain(*args, **kwargs)
    def get_all_field_mappings(self, *args, **kwargs): return self.models.get_all_field_mappings(*args, **kwargs)
    def get_field_mapping_by_selectors(self, *args, **kwargs): return self.models.get_field_mapping_by_selectors(*args, **kwargs)
    def get_domain_field_mappings(self, *args, **kwargs): return self.models.get_domain_field_mappings(*args, **kwargs)
    def get_all_domain_field_mappings(self, *args, **kwargs): return self.models.get_all_domain_field_mappings(*args, **kwargs)
    def propose_field_mapping(self, *args, **kwargs): return self.models.propose_field_mapping(*args, **kwargs)
    def get_field_mapping_proposal_by_selectors(self, *args, **kwargs): return self.models.get_field_mapping_proposal_by_selectors(*args, **kwargs)
    def add_retrain_sample(self, *args, **kwargs): return self.models.add_retrain_sample(*args, **kwargs)
    def get_pending_field_mapping_proposals(self, *args, **kwargs): return self.models.get_pending_field_mapping_proposals(*args, **kwargs)
    def mark_field_mapping_proposal_status(self, *args, **kwargs): return self.models.mark_field_mapping_proposal_status(*args, **kwargs)
    def delete_field_mapping_proposal(self, *args, **kwargs): return self.models.delete_field_mapping_proposal(*args, **kwargs)
    def update_field_mapping_proposal(self, *args, **kwargs): return self.models.update_field_mapping_proposal(*args, **kwargs)
    def get_field_mapped_model(self, *args, **kwargs): return self.models.get_field_mapped_model(*args, **kwargs)
    def set_lifecycle_state(self, *args, **kwargs): return self.models.set_lifecycle_state(*args, **kwargs)
    def get_latest_model_by_state(self, *args, **kwargs): return self.models.get_latest_model_by_state(*args, **kwargs)

    # Training
    def insert_retrain_sample(self, *args, **kwargs): return self.training.insert_retrain_sample(*args, **kwargs)
    def get_retrain_samples(self, *args, **kwargs): return self.training.get_retrain_samples(*args, **kwargs)
    def label_retrain_sample(self, *args, **kwargs): return self.training.label_retrain_sample(*args, **kwargs)
    def reject_retrain_sample(self, *args, **kwargs): return self.training.reject_retrain_sample(*args, **kwargs)
    def get_retrain_sample_counts(self, *args, **kwargs): return self.training.get_retrain_sample_counts(*args, **kwargs)
    def upsert_failed_payload_label(self, *args, **kwargs): return self.training.upsert_failed_payload_label(*args, **kwargs)
    def get_failed_payload_labels(self, *args, **kwargs): return self.training.get_failed_payload_labels(*args, **kwargs)
    def create_retrain_job(self, *args, **kwargs): return self.training.create_retrain_job(*args, **kwargs)
    def get_due_retrain_jobs(self, *args, **kwargs): return self.training.get_due_retrain_jobs(*args, **kwargs)
    def mark_retrain_job_running(self, job_id: int): return self.training.mark_retrain_job_running(job_id)
    def mark_retrain_job_done(self, *args, **kwargs): return self.training.mark_retrain_job_done(*args, **kwargs)
    def mark_retrain_job_failed(self, *args, **kwargs): return self.training.mark_retrain_job_failed(*args, **kwargs)
    def get_retrain_jobs(self, *args, **kwargs): return self.training.get_retrain_jobs(*args, **kwargs)
    def claim_labeled_samples(self, *args, **kwargs): return self.training.claim_labeled_samples(*args, **kwargs)
    def release_job_claims(self, job_id: int): return self.training.release_job_claims(job_id)
    def insert_active_learning(self, *args, **kwargs): return self.training.insert_active_learning(*args, **kwargs)
    def get_active_learning_samples(self, *args, **kwargs): return self.training.get_active_learning_samples(*args, **kwargs)
