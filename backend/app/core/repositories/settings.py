from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from .base import BaseRepository

class SettingsRepository(BaseRepository):
    # Keys and their default values — used when no DB row exists yet
    _SETTING_DEFAULTS: dict[str, str] = {
        "platform.name": "EazyFill",
    }

    _SETTING_DESCRIPTIONS: dict[str, str] = {
        "platform.name": "Display name shown in admin dashboard",
    }

    def get_setting(self, key: str, default: str | None = None) -> str:
        """Read a single runtime setting from DB. Falls back to class default then param default."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT value FROM platform_settings WHERE key = ?", (key,)
            ).fetchone()
            if row:
                return str(row["value"])
        # Not in DB — return class default or param default
        return self._SETTING_DEFAULTS.get(key, default or "")

    def set_setting(self, key: str, value: str, description: str | None = None) -> None:
        """Upsert a runtime setting into the DB."""
        desc = description or self._SETTING_DESCRIPTIONS.get(key)
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with self.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO platform_settings (key, value, description, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        description = COALESCE(excluded.description, platform_settings.description),
                        updated_at = excluded.updated_at
                    """,
                    (key, value, desc, now),
                )
                conn.commit()

    def get_all_settings(self) -> list[dict]:
        """Return all settings rows for admin display, merging with defaults."""
        with self.connect() as conn:
            rows = {
                row["key"]: {"key": row["key"], "value": row["value"],
                             "description": row["description"], "updated_at": row["updated_at"]}
                for row in conn.execute("SELECT * FROM platform_settings ORDER BY key")
            }
        # Fill in any missing keys from defaults so admin sees all available settings
        result = []
        for key, default_val in self._SETTING_DEFAULTS.items():
            if key in rows:
                result.append(rows[key])
            else:
                result.append({
                    "key": key,
                    "value": default_val,
                    "description": self._SETTING_DESCRIPTIONS.get(key, ""),
                    "updated_at": None,
                })
        # Include any extra DB keys not in defaults
        for key, row in rows.items():
            if key not in self._SETTING_DEFAULTS:
                result.append(row)
        return result

    def get_global_access(self) -> bool:
        with self.connect() as conn:
            cursor = conn.execute("SELECT value FROM access_control WHERE key = 'global_access'")
            row = cursor.fetchone()
            return row["value"] == "true" if row else True

    def set_global_access(self, enabled: bool) -> None:
        with self._lock:
            with self.connect() as conn:
                val = "true" if enabled else "false"
                conn.execute(
                    "INSERT INTO access_control (key, value) VALUES ('global_access', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (val,)
                )
                conn.commit()

    def get_allowed_domains(self) -> list[str]:
        with self.connect() as conn:
            normalized = {
                self._normalize_domain(row["domain"])
                for row in conn.execute("SELECT domain FROM allowed_domains")
            }
            return sorted([d for d in normalized if d])

    def is_domain_allowed(self, domain: str | None) -> bool:
        candidate_set = set(self._domain_candidates(domain))
        if not candidate_set:
            return False
        allowed = set(self.get_allowed_domains())
        return bool(candidate_set & allowed)

    def add_allowed_domain(self, domain: str) -> None:
        clean_domain = self._normalize_domain(domain)
        if not clean_domain:
            return
        with self._lock:
            with self.connect() as conn:
                conn.execute("INSERT OR IGNORE INTO allowed_domains (domain) VALUES (?)", (clean_domain,))
                conn.commit()

    def remove_allowed_domain(self, domain: str) -> None:
        clean_domain = self._normalize_domain(domain)
        if not clean_domain:
            return
        with self._lock:
            with self.connect() as conn:
                conn.execute("DELETE FROM allowed_domains WHERE domain = ?", (clean_domain,))
                conn.commit()

    def export_master_setup(self) -> dict[str, Any]:
        """Export current admin setup for one-click migration."""
        # Note: This calls methods from other repositories.
        # In a strict refactor, we might want to pass them in or use the facade.
        # For now, we'll assume the facade 'self.db' has them.
        return {
            "global_access": self.get_global_access(),
            "allowed_domains": self.get_allowed_domains(),
            "platform_settings": self.get_all_settings(),
            "model_routes": self.db.models.get_all_model_routes(),
            "model_registry": self.db.models.get_model_registry(),
            "field_mappings": self.db.models.get_all_field_mappings(),
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }

    def import_master_setup(self, payload: dict[str, Any]) -> None:
        """Import setup snapshot (metadata only; model files must exist on disk)."""
        with self._lock:
            with self.connect() as conn:
                now = datetime.now(timezone.utc).isoformat()
                global_access = bool(payload.get("global_access", True))
                conn.execute(
                    "INSERT INTO access_control (key, value) VALUES ('global_access', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    ("true" if global_access else "false",),
                )

                conn.execute("DELETE FROM allowed_domains")
                for domain in payload.get("allowed_domains", []) or []:
                    d = self._normalize_domain(domain)
                    if d:
                        conn.execute("INSERT OR IGNORE INTO allowed_domains (domain) VALUES (?)", (d,))

                # Import platform_settings
                for s in payload.get("platform_settings", []) or []:
                    key = str(s.get("key") or "").strip()
                    val = str(s.get("value") or "").strip()
                    desc = s.get("description")
                    if key:
                        conn.execute(
                            """
                            INSERT INTO platform_settings (key, value, description, updated_at)
                            VALUES (?, ?, ?, ?)
                            ON CONFLICT(key) DO UPDATE SET
                                value = excluded.value,
                                description = COALESCE(excluded.description, platform_settings.description),
                                updated_at = excluded.updated_at
                            """,
                            (key, val, desc, now),
                        )

                model_id_by_filename: dict[str, int] = {}
                for item in payload.get("model_registry", []) or []:
                    filename = str(item.get("ai_model_filename") or "").strip()
                    if not filename:
                        continue
                    ai_model_name = str(item.get("ai_model_name") or "imported-model").strip() or "imported-model"
                    version = str(item.get("version") or "v1").strip() or "v1"
                    task_type = str(item.get("task_type") or "image").strip() or "image"
                    ai_runtime = str(item.get("ai_runtime") or "onnx").strip() or "onnx"
                    status = str(item.get("status") or "active").strip() or "active"
                    lifecycle_state = str(item.get("lifecycle_state") or "candidate").strip() or "candidate"
                    notes = item.get("notes")
                    conn.execute(
                        """
                        INSERT INTO model_registry (ai_model_name, version, task_type, ai_runtime, ai_model_filename, status, lifecycle_state, notes, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(ai_model_filename) DO UPDATE SET
                            ai_model_name = excluded.ai_model_name,
                            version = excluded.version,
                            task_type = excluded.task_type,
                            ai_runtime = excluded.ai_runtime,
                            status = excluded.status,
                            lifecycle_state = excluded.lifecycle_state,
                            notes = excluded.notes,
                            updated_at = excluded.updated_at
                        """,
                        (ai_model_name, version, task_type, ai_runtime, filename, status, lifecycle_state, notes, now, now),
                    )
                    row = conn.execute(
                        "SELECT id FROM model_registry WHERE ai_model_filename = ?",
                        (filename,),
                    ).fetchone()
                    if row:
                        model_id_by_filename[filename] = int(row["id"])

                conn.execute("DELETE FROM model_routes")
                for route in payload.get("model_routes", []) or []:
                    domain = self._normalize_domain(route.get("domain"))
                    filename = str(route.get("ai_model_filename") or "").strip()
                    if domain and filename:
                        conn.execute(
                            "INSERT OR REPLACE INTO model_routes (domain, ai_model_filename) VALUES (?, ?)",
                            (domain, filename),
                        )

                conn.execute("DELETE FROM field_mappings")
                for fm in payload.get("field_mappings", []) or []:
                    domain = self._normalize_domain(fm.get("domain"))
                    field_name = str(fm.get("field_name") or "").strip()
                    task_type = str(fm.get("task_type") or "image").strip() or "image"
                    source_data_type = str(fm.get("source_data_type") or task_type).strip() or task_type
                    source_selector = str(fm.get("source_selector") or "").strip()
                    target_data_type = str(fm.get("target_data_type") or "text_input").strip() or "text_input"
                    target_selector = str(fm.get("target_selector") or "").strip()
                    filename = str(fm.get("ai_model_filename") or "").strip()
                    if not (domain and field_name and filename):
                        continue
                    ai_model_id = model_id_by_filename.get(filename)
                    if not ai_model_id:
                        row = conn.execute("SELECT id FROM model_registry WHERE ai_model_filename = ?", (filename,)).fetchone()
                        if not row:
                            continue
                        ai_model_id = int(row["id"])
                    conn.execute(
                        """
                        INSERT INTO field_mappings (domain, field_name, task_type, source_data_type, source_selector, target_data_type, target_selector, ai_model_id, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (domain, field_name, task_type, source_data_type, source_selector, target_data_type, target_selector, ai_model_id, now),
                    )

                conn.commit()
