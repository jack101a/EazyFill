from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from .base import BaseRepository
from app.core.config import get_settings
from app.core.security import hash_api_key

class APIKeyRepository(BaseRepository):
    DEFAULT_SERVICES = {
        "autofill": True,
        "captcha": True,
        "userscripts": True,
        "sync": True,
        "priority_solving": False,
        "unlimited_rules": False,
        "js_rules": False,
    }

    def _parse_services(self, value: str | None) -> dict[str, bool]:
        try:
            raw = json.loads(value or "{}")
            if not isinstance(raw, dict):
                raw = {}
        except Exception:
            raw = {}
        services = dict(self.DEFAULT_SERVICES)
        for key, enabled in raw.items():
            services[str(key)] = bool(enabled)
        return services

    def _persistent_master_key_id(self, conn) -> int | None:
        row = conn.execute(
            "SELECT value FROM platform_settings WHERE key = 'master_api_key_id'"
        ).fetchone()
        if not row:
            return None
        try:
            return int(row["value"])
        except Exception:
            return None

    def insert_api_key(self, name: str, key_hash: str, expires_at: str | None, key_type: str = "user") -> int:
        """Insert API key and return row id."""
        with self._lock:
            with self.connect() as conn:
                now = datetime.now(timezone.utc).isoformat()
                cursor = conn.execute(
                    """
                    INSERT INTO api_keys (name, key_hash, key_type, enabled, created_at, expires_at, revoked_at)
                    VALUES (?, ?, ?, 1, ?, ?, NULL)
                    """,
                    (name, key_hash, key_type, now, expires_at),
                )
                conn.commit()
                return int(cursor.lastrowid)

    def get_api_key_by_hash(self, key_hash: str) -> dict[str, Any] | None:
        """Fetch API key record by hash."""
        with self.connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM api_keys WHERE key_hash = ?",
                (key_hash,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def touch_usage(self, key_id: int) -> None:
        """Increment usage_count and update last_used_at for a legacy API key."""
        with self._lock:
            with self.connect() as conn:
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    """
                    UPDATE api_keys
                    SET usage_count = COALESCE(usage_count, 0) + 1,
                        last_used_at = ?
                    WHERE id = ?
                    """,
                    (now, key_id),
                )
                conn.commit()

    def revoke_api_key(self, key_hash: str) -> bool:
        """Disable API key hash."""
        with self._lock:
            with self.connect() as conn:
                key_row = conn.execute(
                    "SELECT id, key_type FROM api_keys WHERE key_hash = ?",
                    (key_hash,),
                ).fetchone()
                if (
                    key_row
                    and key_row["key_type"] == "master"
                    and int(key_row["id"]) == self._persistent_master_key_id(conn)
                ):
                    return False
                now = datetime.now(timezone.utc).isoformat()
                result = conn.execute(
                    """
                    UPDATE api_keys
                    SET enabled = 0, revoked_at = ?
                    WHERE key_hash = ?
                    """,
                    (now, key_hash),
                )
                conn.commit()
                return result.rowcount > 0

    def revoke_api_key_by_id(self, key_id: int) -> bool:
        """Disable API key by integer id."""
        with self._lock:
            with self.connect() as conn:
                key_row = conn.execute("SELECT key_type FROM api_keys WHERE id = ?", (key_id,)).fetchone()
                if key_row and key_row["key_type"] == "master" and int(key_id) == self._persistent_master_key_id(conn):
                    return False
                now = datetime.now(timezone.utc).isoformat()
                result = conn.execute(
                    """
                    UPDATE api_keys
                    SET enabled = 0, revoked_at = ?
                    WHERE id = ?
                    """,
                    (now, key_id),
                )
                conn.commit()
                return result.rowcount > 0

    def delete_revoked_api_key_by_id(self, key_id: int) -> bool:
        """Delete revoked key and dependent rows. Active keys cannot be deleted."""
        with self._lock:
            with self.connect() as conn:
                row = conn.execute(
                    "SELECT id, enabled, revoked_at, key_type FROM api_keys WHERE id = ?",
                    (key_id,),
                ).fetchone()
                if not row:
                    return False
                if row["key_type"] == "master" and int(key_id) == self._persistent_master_key_id(conn):
                    return False
                if int(row["enabled"]) == 1:
                    return False
                if not row["revoked_at"]:
                    return False

                conn.execute("DELETE FROM usage_events WHERE key_id = ?", (key_id,))
                conn.execute("DELETE FROM field_mapping_proposals WHERE reported_by = ?", (key_id,))
                conn.execute("DELETE FROM active_learning WHERE reported_by = ?", (key_id,))
                conn.execute("UPDATE retrain_jobs SET requested_by = NULL WHERE requested_by = ?", (key_id,))
                conn.execute(
                    "UPDATE retrain_samples SET labeled_by = NULL WHERE labeled_by = ?",
                    (key_id,),
                )
                conn.execute("DELETE FROM retrain_samples WHERE reported_by = ?", (key_id,))
                result = conn.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
                conn.commit()
                return result.rowcount > 0

    def delete_revoked_api_keys(self) -> int:
        """Delete all revoked legacy keys and dependent metadata."""
        with self._lock:
            with self.connect() as conn:
                rows = conn.execute(
                    "SELECT id FROM api_keys WHERE key_type != 'master' AND (enabled = 0 OR revoked_at IS NOT NULL)"
                ).fetchall()
                key_ids = [int(row["id"]) for row in rows]
                for key_id in key_ids:
                    conn.execute("DELETE FROM usage_events WHERE key_id = ?", (key_id,))
                    conn.execute("DELETE FROM api_key_allowed_domains WHERE key_id = ?", (key_id,))
                    conn.execute("DELETE FROM api_key_rate_limits WHERE key_id = ?", (key_id,))
                    conn.execute("DELETE FROM api_key_device_bindings WHERE key_id = ?", (key_id,))
                    conn.execute("DELETE FROM field_mapping_proposals WHERE reported_by = ?", (key_id,))
                    conn.execute("DELETE FROM active_learning WHERE reported_by = ?", (key_id,))
                    conn.execute("UPDATE retrain_jobs SET requested_by = NULL WHERE requested_by = ?", (key_id,))
                    conn.execute(
                        "UPDATE retrain_samples SET labeled_by = NULL WHERE labeled_by = ?",
                        (key_id,),
                    )
                    conn.execute("DELETE FROM retrain_samples WHERE reported_by = ?", (key_id,))
                    conn.execute("DELETE FROM platform_settings WHERE key = ?", (f"api_key_plain_{key_id}",))
                    conn.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
                conn.commit()
                return len(key_ids)

    def insert_usage_event(
        self,
        key_id: int,
        task_type: str,
        status: str,
        processing_ms: int,
        model_used: str | None,
        domain: str | None,
        ip: str | None,
    ) -> None:
        """Persist usage event row."""
        with self._lock:
            with self.connect() as conn:
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    """
                    INSERT INTO usage_events (key_id, task_type, status, processing_ms, model_used, domain, ip, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (key_id, task_type, status, processing_ms, model_used, domain, ip, now),
                )
                conn.commit()

    @staticmethod
    def _percentile(values: list[int], percentile: float) -> int:
        if not values:
            return 0
        ordered = sorted(values)
        index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * percentile))))
        return int(ordered[index])

    def _get_service_performance(
        self,
        *,
        task_type: str,
        task_like: bool = False,
        key_id: int | None = None,
        since: datetime | None = None,
    ) -> dict[str, Any]:
        where = ["task_type LIKE ?" if task_like else "task_type = ?"]
        params: list[Any] = [task_type]
        if key_id is not None:
            where.append("key_id = ?")
            params.append(key_id)
        if since is not None:
            where.append("created_at >= ?")
            params.append(since.isoformat())

        where_sql = " AND ".join(where)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT status, processing_ms
                FROM usage_events
                WHERE {where_sql}
                """,
                tuple(params),
            ).fetchall()

        total = len(rows)
        ok = sum(1 for row in rows if str(row["status"]) == "ok")
        errors = sum(1 for row in rows if str(row["status"]) == "error")
        measured = [
            int(row["processing_ms"] or 0)
            for row in rows
            if str(row["status"]) != "error" and int(row["processing_ms"] or 0) > 0
        ]
        avg_ms = round(sum(measured) / len(measured), 1) if measured else 0.0
        return {
            "total_requests": total,
            "successful_requests": ok,
            "failed_requests": total - ok,
            "error_requests": errors,
            "measured_requests": len(measured),
            "avg_processing_ms": avg_ms,
            "p50_processing_ms": self._percentile(measured, 0.50),
            "p95_processing_ms": self._percentile(measured, 0.95),
        }

    def _get_service_performance_summary(self, key_id: int | None = None) -> dict[str, Any]:
        since_15m = datetime.now(timezone.utc) - timedelta(minutes=15)
        return {
            "window_minutes": 15,
            "captcha": {
                "recent": self._get_service_performance(
                    task_type="captcha:%",
                    task_like=True,
                    key_id=key_id,
                    since=since_15m,
                ),
                "all_time": self._get_service_performance(
                    task_type="captcha:%",
                    task_like=True,
                    key_id=key_id,
                ),
            },
        }

    def get_usage_summary(self, key_id: int | None = None) -> dict[str, Any]:
        """Get usage summary, optionally filtered by key."""
        with self.connect() as conn:
            query_base = "FROM usage_events"
            params: tuple[Any, ...] = ()
            if key_id is not None:
                query_base += " WHERE key_id = ?"
                params = (key_id,)

            total = conn.execute(f"SELECT COUNT(*) AS total {query_base}", params).fetchone()["total"]

            success_query = f"SELECT COUNT(*) AS success {query_base}"
            if key_id is not None:
                success_query += " AND status = 'ok'"
            else:
                success_query += " WHERE status = 'ok'"

            success = conn.execute(success_query, params).fetchone()["success"]

            avg_ms = conn.execute(f"SELECT COALESCE(AVG(processing_ms), 0) AS avg_ms {query_base}", params).fetchone()["avg_ms"]

            return {
                "total_requests": int(total),
                "successful_requests": int(success),
                "failed_requests": int(total - success),
                "avg_processing_ms": float(avg_ms),
                "performance": self._get_service_performance_summary(key_id=key_id),
            }

    def get_all_api_keys(self) -> list[dict[str, Any]]:
        """Get all API keys for admin view."""
        with self.connect() as conn:
            rows = []
            for row in conn.execute(
                """
                SELECT id, name, key_type, enabled, all_domains, created_at, expires_at, revoked_at,
                       plan_name, mobile, services_json
                FROM api_keys
                ORDER BY id DESC
                """
            ):
                item = dict(row)
                item["services"] = self._parse_services(item.get("services_json"))
                item.pop("services_json", None)
                rows.append(item)
            return rows

    def set_api_key_domain_scope(self, key_id: int, all_domains: bool, domains: list[str] | None = None) -> None:
        clean_domains = sorted({self._normalize_domain(d) for d in (domains or []) if self._normalize_domain(d)})
        with self._lock:
            with self.connect() as conn:
                conn.execute("UPDATE api_keys SET all_domains = ? WHERE id = ?", (1 if all_domains else 0, key_id))
                conn.execute("DELETE FROM api_key_allowed_domains WHERE key_id = ?", (key_id,))
                if not all_domains:
                    for domain in clean_domains:
                        conn.execute(
                            "INSERT INTO api_key_allowed_domains (key_id, domain) VALUES (?, ?)",
                            (key_id, domain),
                        )
                conn.commit()

    def get_api_key_allowed_domains(self, key_id: int) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT domain FROM api_key_allowed_domains WHERE key_id = ? ORDER BY domain ASC",
                (key_id,),
            )
            return [str(row["domain"]) for row in rows]

    def is_domain_allowed_for_key(self, key_id: int, domain: str | None) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT all_domains FROM api_keys WHERE id = ?", (key_id,)).fetchone()
            if not row:
                return False
            if int(row["all_domains"]) == 1:
                return True
            for candidate in self._domain_candidates(domain):
                hit = conn.execute(
                    "SELECT 1 FROM api_key_allowed_domains WHERE key_id = ? AND domain = ? LIMIT 1",
                    (key_id, candidate),
                ).fetchone()
                if hit:
                    return True
            return False

    def set_api_key_rate_limit(self, key_id: int, requests_per_minute: int, burst: int = 0) -> None:
        rpm = max(1, int(requests_per_minute))
        b = max(0, int(burst))
        with self._lock:
            with self.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO api_key_rate_limits (key_id, requests_per_minute, burst)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key_id) DO UPDATE SET
                        requests_per_minute = excluded.requests_per_minute,
                        burst = excluded.burst
                    """,
                    (key_id, rpm, b),
                )
                conn.commit()

    def get_api_key_rate_limit(self, key_id: int) -> dict[str, int] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT requests_per_minute, burst FROM api_key_rate_limits WHERE key_id = ?",
                (key_id,),
            ).fetchone()
            if not row:
                return None
            return {
                "requests_per_minute": int(row["requests_per_minute"]),
                "burst": int(row["burst"]),
            }

    def set_api_key_entitlements(
        self,
        key_id: int,
        plan_name: str = "",
        mobile: str = "",
        services: dict[str, bool] | None = None,
    ) -> None:
        clean_services = dict(self.DEFAULT_SERVICES)
        for name, enabled in (services or {}).items():
            clean_services[str(name)] = bool(enabled)
        with self._lock:
            with self.connect() as conn:
                conn.execute(
                    """
                    UPDATE api_keys
                    SET plan_name = ?, mobile = ?, services_json = ?
                    WHERE id = ?
                    """,
                    (
                        str(plan_name or "Standard").strip() or "Standard",
                        str(mobile or "").strip(),
                        json.dumps(clean_services, separators=(",", ":")),
                        key_id,
                    ),
                )
                conn.commit()

    def get_api_key_entitlements(self, key_id: int) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT plan_name, mobile, services_json
                FROM api_keys
                WHERE id = ?
                """,
                (key_id,),
            ).fetchone()
            if not row:
                return {
                    "plan_name": "Standard",
                    "mobile": "",
                    "services": dict(self.DEFAULT_SERVICES),
                }
            return {
                "plan_name": row["plan_name"] or "Standard",
                "mobile": row["mobile"] or "",
                "services": self._parse_services(row["services_json"]),
            }

    def validate_or_bind_key_device(
        self,
        key_id: int,
        device_id: str,
        user_agent: str | None = None,
    ) -> bool:
        """Bind key to first-seen device and reject any different device later."""
        token = str(device_id or "").strip()
        if not token:
            return False
        with self.connect() as conn:
            key_row = conn.execute("SELECT key_type FROM api_keys WHERE id = ?", (key_id,)).fetchone()
            if key_row and key_row["key_type"] == "master":
                return True
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with self.connect() as conn:
                row = conn.execute(
                    "SELECT device_id FROM api_key_device_bindings WHERE key_id = ?",
                    (key_id,),
                ).fetchone()
                if not row:
                    conn.execute(
                        """
                        INSERT INTO api_key_device_bindings (key_id, device_id, user_agent, first_seen_at, last_seen_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (key_id, token, (user_agent or "")[:512], now, now),
                    )
                    conn.commit()
                    return True
                if str(row["device_id"]) != token:
                    return False
                conn.execute(
                    """
                    UPDATE api_key_device_bindings
                    SET user_agent = ?, last_seen_at = ?
                    WHERE key_id = ?
                    """,
                    ((user_agent or "")[:512], now, key_id),
                )
                conn.commit()
                return True

    def get_api_key_device_binding(self, key_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT device_id, user_agent, first_seen_at, last_seen_at
                FROM api_key_device_bindings
                WHERE key_id = ?
                """,
                (key_id,),
            ).fetchone()
            return dict(row) if row else None

    # ── Master Key ────────────────────────────────────────────────────────────
    # The master key is stored plaintext in platform_settings so it survives
    # any DB migration, backup/restore, or server move.
    # Key: "master_api_key_plain"   Value: raw key string
    # Key: "master_api_key_id"      Value: api_keys.id (int as str)

    _MASTER_KEY_PREFIX = "tata_master_"

    def ensure_master_key(self) -> dict:
        """Idempotently create the master API key.

        If already created (found in platform_settings), repairs the api_keys
        row if needed. On first run, creates a real api_key row (no expiry)
        and saves the plaintext in platform_settings.
        Returns: { id, key, name }
        """
        with self.connect() as conn:
            row_plain = conn.execute(
                "SELECT value FROM platform_settings WHERE key = 'master_api_key_plain'"
            ).fetchone()
            row_id = conn.execute(
                "SELECT value FROM platform_settings WHERE key = 'master_api_key_id'"
            ).fetchone()

        if row_plain:
            raw = str(row_plain["value"])
            key_hash = hash_api_key(raw, get_settings().auth.hash_salt)
            with self._lock:
                with self.connect() as conn:
                    now = datetime.now(timezone.utc).isoformat()
                    enabled_setting = conn.execute(
                        "SELECT value FROM platform_settings WHERE key = 'master_api_key_enabled'"
                    ).fetchone()
                    default_enabled = 1
                    if enabled_setting and str(enabled_setting["value"]).strip().lower() in {"0", "false", "off", "no", "inactive"}:
                        default_enabled = 0
                    key_id = int(row_id["value"]) if row_id else 0
                    existing = None
                    if key_id:
                        existing = conn.execute(
                            "SELECT id, key_hash, key_type, enabled FROM api_keys WHERE id = ?",
                            (key_id,),
                        ).fetchone()

                    if existing and existing["key_hash"] == key_hash and existing["key_type"] == "master":
                        return {
                            "id": int(existing["id"]),
                            "key": raw,
                            "name": "Master Key",
                            "enabled": bool(int(existing["enabled"])),
                        }

                    by_hash = conn.execute(
                        "SELECT id, enabled FROM api_keys WHERE key_hash = ?",
                        (key_hash,),
                    ).fetchone()
                    if by_hash:
                        key_id = int(by_hash["id"])
                        enabled = int(by_hash["enabled"] or 0)
                        conn.execute(
                            """
                            UPDATE api_keys
                            SET name = ?, key_type = 'master', enabled = ?, expires_at = NULL
                            WHERE id = ?
                            """,
                            ("Master Key", enabled, key_id),
                        )
                    elif existing:
                        key_id = int(existing["id"])
                        enabled = int(existing["enabled"] or 0)
                        conn.execute(
                            """
                            UPDATE api_keys
                            SET name = ?, key_hash = ?, key_type = 'master', enabled = ?, expires_at = NULL
                            WHERE id = ?
                            """,
                            ("Master Key", key_hash, enabled, key_id),
                        )
                    else:
                        enabled = default_enabled
                        cursor = conn.execute(
                            """
                            INSERT INTO api_keys (name, key_hash, key_type, enabled, created_at, expires_at, revoked_at)
                            VALUES (?, ?, 'master', ?, ?, NULL, NULL)
                            """,
                            ("Master Key", key_hash, enabled, now),
                        )
                        key_id = int(cursor.lastrowid)

                    conn.execute(
                        """
                        INSERT INTO platform_settings (key, value, description, updated_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                        """,
                        ("master_api_key_id", str(key_id), "Auto-managed — do not edit manually", now),
                    )
                    conn.commit()
                    return {"id": key_id, "key": raw, "name": "Master Key", "enabled": bool(enabled)}

        # Generate a new master key
        import secrets
        raw = self._MASTER_KEY_PREFIX + secrets.token_hex(24)
        key_hash = hash_api_key(raw, get_settings().auth.hash_salt)

        with self._lock:
            with self.connect() as conn:
                now = datetime.now(timezone.utc).isoformat()
                cursor = conn.execute(
                    """
                    INSERT INTO api_keys (name, key_hash, key_type, enabled, created_at, expires_at, revoked_at)
                    VALUES (?, ?, 'master', 1, ?, NULL, NULL)
                    """,
                    ("Master Key", key_hash, now),
                )
                key_id = int(cursor.lastrowid)
                # Persist plaintext + id in platform_settings (survives migrations)
                for k, v in [
                    ("master_api_key_plain", raw),
                    ("master_api_key_id",    str(key_id)),
                ]:
                    conn.execute(
                        """
                        INSERT INTO platform_settings (key, value, description, updated_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                        """,
                        (k, v, "Auto-managed — do not edit manually", now),
                    )
                conn.commit()

        return {"id": key_id, "key": raw, "name": "Master Key", "enabled": True}

    def get_master_key_info(self) -> dict | None:
        """Return master key info if it exists, else None."""
        with self.connect() as conn:
            row_plain = conn.execute(
                "SELECT value FROM platform_settings WHERE key = 'master_api_key_plain'"
            ).fetchone()
            row_id = conn.execute(
                "SELECT value FROM platform_settings WHERE key = 'master_api_key_id'"
            ).fetchone()
            key_row = None
            if row_id:
                key_row = conn.execute(
                    "SELECT enabled, revoked_at FROM api_keys WHERE id = ? AND key_type = 'master'",
                    (int(row_id["value"]),),
                ).fetchone()
        if row_plain and row_id:
            return {
                "id": int(row_id["value"]),
                "key": row_plain["value"],
                "name": "Master Key",
                "enabled": bool(int(key_row["enabled"])) if key_row else False,
                "revoked_at": key_row["revoked_at"] if key_row else None,
            }
        return None

    def set_master_key_enabled(self, enabled: bool) -> dict | None:
        """Activate/deactivate the persistent master key without rotating it."""
        info = self.ensure_master_key()
        key_id = int(info["id"])
        with self._lock:
            with self.connect() as conn:
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    """
                    UPDATE api_keys
                    SET enabled = ?, revoked_at = NULL
                    WHERE id = ? AND key_type = 'master'
                    """,
                    (1 if enabled else 0, key_id),
                )
                conn.execute(
                    """
                    INSERT INTO platform_settings (key, value, description, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                    """,
                    (
                        "master_api_key_enabled",
                        "1" if enabled else "0",
                        "Whether the persistent master API key is active",
                        now,
                    ),
                )
                conn.commit()
        return self.get_master_key_info()

    def is_master_key_hash(self, key_hash: str) -> bool:
        """Return True if the given hash belongs to a master key."""
        with self.connect() as conn:
            row = conn.execute("SELECT key_type, enabled FROM api_keys WHERE key_hash = ?", (key_hash,)).fetchone()
            if row and row["key_type"] == "master" and int(row["enabled"] or 0) == 1:
                return True
        return False
