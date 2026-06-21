from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from .base import BaseRepository

class ModelRepository(BaseRepository):
    def get_model_route(self, domain: str) -> str | None:
        with self.connect() as conn:
            for candidate in self._domain_candidates(domain):
                row = conn.execute(
                    "SELECT ai_model_filename FROM model_routes WHERE domain = ?",
                    (candidate,),
                ).fetchone()
                if row:
                    return row["ai_model_filename"]
            return None

    def set_model_route(self, domain: str, ai_model_filename: str) -> None:
        clean_domain = self._normalize_domain(domain)
        if not clean_domain:
            return
        with self._lock:
            with self.connect() as conn:
                conn.execute(
                    "INSERT INTO model_routes (domain, ai_model_filename) VALUES (?, ?) ON CONFLICT(domain) DO UPDATE SET ai_model_filename=excluded.ai_model_filename",
                    (clean_domain, ai_model_filename)
                )
                conn.commit()

    def get_all_model_routes(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM model_routes")]

    def add_model_registry_entry(
        self,
        ai_model_name: str,
        version: str,
        task_type: str,
        ai_runtime: str,
        ai_model_filename: str,
        notes: str | None,
        status: str = "active",
        lifecycle_state: str = "candidate",
    ) -> int:
        with self._lock:
            with self.connect() as conn:
                now = datetime.now(timezone.utc).isoformat()
                cursor = conn.execute(
                    """
                    INSERT INTO model_registry (ai_model_name, version, task_type, ai_runtime, ai_model_filename, status, lifecycle_state, notes, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ai_model_name,
                        version,
                        task_type,
                        ai_runtime,
                        ai_model_filename,
                        status,
                        lifecycle_state,
                        notes,
                        now,
                        now,
                    ),
                )
                conn.commit()
                return int(cursor.lastrowid)

    def get_model_registry(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM model_registry ORDER BY updated_at DESC, id DESC"
                )
            ]

    def get_model_registry_entry(self, model_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM model_registry WHERE id = ?",
                (model_id,),
            ).fetchone()
            return dict(row) if row else None

    def delete_model_registry_entry(self, model_id: int) -> None:
        with self._lock:
            with self.connect() as conn:
                conn.execute("DELETE FROM model_registry WHERE id = ?", (model_id,))
                conn.commit()

    def update_model_registry_entry(
        self,
        ai_model_id: int,
        ai_model_name: str,
        version: str,
        task_type: str,
        notes: str | None,
        lifecycle_state: str,
    ) -> None:
        with self._lock:
            with self.connect() as conn:
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    """
                    UPDATE model_registry
                    SET ai_model_name = ?, version = ?, task_type = ?, notes = ?, lifecycle_state = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (ai_model_name, version, task_type, notes, lifecycle_state, now, ai_model_id),
                )
                conn.commit()

    def set_field_mapping(
        self,
        domain: str,
        field_name: str,
        task_type: str,
        ai_model_id: int,
        source_data_type: str | None = None,
        source_selector: str | None = None,
        target_data_type: str | None = None,
        target_selector: str | None = None,
    ) -> None:
        clean_domain = self._normalize_domain(domain)
        if not clean_domain:
            return
        with self._lock:
            with self.connect() as conn:
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    """
                    INSERT INTO field_mappings (
                        domain, field_name, task_type, source_data_type, source_selector, target_data_type, target_selector, ai_model_id, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(domain, field_name, task_type) DO UPDATE SET
                        source_data_type = excluded.source_data_type,
                        source_selector = excluded.source_selector,
                        target_data_type = excluded.target_data_type,
                        target_selector = excluded.target_selector,
                        ai_model_id = excluded.ai_model_id,
                        created_at = excluded.created_at
                    """,
                    (
                        clean_domain,
                        field_name,
                        task_type,
                        source_data_type or task_type,
                        source_selector or "",
                        target_data_type or "text",
                        target_selector or "",
                        ai_model_id,
                        now,
                    ),
                )
                conn.commit()

    def remove_field_mapping(self, mapping_id: int) -> None:
        with self._lock:
            with self.connect() as conn:
                conn.execute("DELETE FROM field_mappings WHERE id = ?", (mapping_id,))
                conn.commit()

    def update_field_mapping(
        self,
        mapping_id: int,
        domain: str,
        field_name: str,
        task_type: str,
        source_data_type: str,
        source_selector: str,
        target_data_type: str,
        target_selector: str,
        ai_model_id: int,
    ) -> None:
        clean_domain = self._normalize_domain(domain)
        if not clean_domain:
            return
        with self._lock:
            with self.connect() as conn:
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    """
                    UPDATE field_mappings
                    SET domain = ?, field_name = ?, task_type = ?,
                        source_data_type = ?, source_selector = ?, target_data_type = ?, target_selector = ?,
                        ai_model_id = ?, created_at = ?
                    WHERE id = ?
                    """,
                    (
                        clean_domain,
                        field_name,
                        task_type,
                        source_data_type,
                        source_selector,
                        target_data_type,
                        target_selector,
                        ai_model_id,
                        now,
                        mapping_id,
                    ),
                )
                conn.commit()

    def rename_domain_mappings(self, old_domain: str, new_domain: str) -> int:
        clean_old = self._normalize_domain(old_domain)
        clean_new = self._normalize_domain(new_domain)
        if not clean_old or not clean_new:
            return 0
        with self._lock:
            with self.connect() as conn:
                conflict = conn.execute(
                    """
                    SELECT 1
                    FROM field_mappings src
                    JOIN field_mappings dst
                      ON dst.domain = ?
                     AND dst.field_name = src.field_name
                     AND dst.task_type = src.task_type
                    WHERE src.domain = ?
                    LIMIT 1
                    """,
                    (clean_new, clean_old),
                ).fetchone()
                if conflict:
                    raise ValueError("domain rename would create duplicate mapping keys")
                result = conn.execute(
                    "UPDATE field_mappings SET domain = ? WHERE domain = ?",
                    (clean_new, clean_old),
                )
                conn.commit()
                return int(result.rowcount or 0)

    def assign_model_to_domain(self, domain: str, ai_model_id: int) -> int:
        clean_domain = self._normalize_domain(domain)
        if not clean_domain:
            return 0
        with self._lock:
            with self.connect() as conn:
                model_row = conn.execute(
                    "SELECT task_type FROM model_registry WHERE id = ?",
                    (ai_model_id,),
                ).fetchone()
                if not model_row:
                    return 0
                model_task = str(model_row["task_type"])
                # Preferred path: only update mappings with matching task type.
                result = conn.execute(
                    """
                    UPDATE field_mappings
                    SET ai_model_id = ?
                    WHERE domain = ? AND task_type = ?
                    """,
                    (ai_model_id, clean_domain, model_task),
                )
                updated = int(result.rowcount or 0)
                if updated > 0:
                    conn.commit()
                    return updated

                # Backward-compat path for older datasets where task_type can be stale.
                # First try source_data_type match.
                result = conn.execute(
                    """
                    UPDATE field_mappings
                    SET ai_model_id = ?
                    WHERE domain = ? AND source_data_type = ?
                    """,
                    (ai_model_id, clean_domain, model_task),
                )
                updated = int(result.rowcount or 0)
                if updated > 0:
                    conn.commit()
                    return updated

                # Final fallback: if domain has mappings, apply model across that domain.
                exists = conn.execute(
                    "SELECT 1 FROM field_mappings WHERE domain = ? LIMIT 1",
                    (clean_domain,),
                ).fetchone()
                if not exists:
                    conn.commit()
                    return 0
                result = conn.execute(
                    """
                    UPDATE field_mappings
                    SET ai_model_id = ?
                    WHERE domain = ?
                    """,
                    (ai_model_id, clean_domain),
                )
                conn.commit()
                return int(result.rowcount or 0)

    def get_all_field_mappings(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT fm.id, fm.domain, fm.field_name, fm.task_type,
                       fm.source_data_type, fm.source_selector, fm.target_data_type, fm.target_selector,
                       fm.ai_model_id, fm.created_at,
                       mr.ai_model_name, mr.version, mr.ai_runtime, mr.ai_model_filename, mr.lifecycle_state
                FROM field_mappings fm
                LEFT JOIN model_registry mr ON mr.id = fm.ai_model_id
                ORDER BY fm.created_at DESC, fm.id DESC
                """
            )
            return [dict(row) for row in rows]

    def get_field_mapping_by_selectors(
        self,
        domain: str | None,
        source_selector: str,
        target_selector: str,
        task_type: str = "image",
    ) -> dict[str, Any] | None:
        domain_candidates = self._domain_candidates(domain)
        if not domain_candidates:
            return None
        with self.connect() as conn:
            for candidate in domain_candidates:
                row = conn.execute(
                    """
                    SELECT fm.id, fm.domain, fm.field_name, fm.task_type,
                           fm.source_data_type, fm.source_selector, fm.target_data_type, fm.target_selector,
                           fm.ai_model_id, fm.created_at,
                           mr.ai_model_name, mr.version, mr.ai_runtime, mr.ai_model_filename, mr.lifecycle_state
                    FROM field_mappings fm
                    JOIN model_registry mr ON mr.id = fm.ai_model_id
                    WHERE fm.domain = ? AND fm.task_type = ?
                      AND fm.source_selector = ? AND fm.target_selector = ?
                      AND mr.status = 'active'
                    LIMIT 1
                    """,
                    (candidate, task_type, source_selector or "", target_selector or ""),
                ).fetchone()
                if row:
                    return dict(row)
        return None

    def get_domain_field_mappings(self, domain: str) -> dict[str, dict[str, str]]:
        with self.connect() as conn:
            result: dict[str, dict[str, str]] = {}
            for candidate in self._domain_candidates(domain):
                rows = conn.execute(
                    """
                    SELECT fm.field_name, fm.task_type, fm.source_data_type, fm.source_selector, fm.target_data_type, fm.target_selector,
                           mr.ai_runtime, mr.ai_model_filename, mr.lifecycle_state
                    FROM field_mappings fm
                    JOIN model_registry mr ON mr.id = fm.ai_model_id
                    WHERE fm.domain = ? AND mr.status = 'active'
                    """,
                    (candidate,),
                )
                for row in rows:
                    result[row["field_name"]] = {
                        "task_type": row["task_type"],
                        "source_data_type": row["source_data_type"],
                        "source_selector": row["source_selector"],
                        "target_data_type": row["target_data_type"],
                        "target_selector": row["target_selector"],
                        "runtime": row["ai_runtime"],
                        "model_filename": row["ai_model_filename"],
                        "lifecycle_state": row["lifecycle_state"],
                    }
                if result:
                    return result
            return result

    def get_all_domain_field_mappings(self) -> dict[str, list[dict[str, Any]]]:
        """Return approved field mappings for all domains for extension sync."""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT fm.domain, fm.field_name, fm.task_type,
                       fm.source_data_type, fm.source_selector, fm.target_data_type, fm.target_selector,
                       mr.ai_model_name, mr.version, mr.ai_runtime, mr.ai_model_filename, mr.lifecycle_state
                FROM field_mappings fm
                JOIN model_registry mr ON mr.id = fm.ai_model_id
                WHERE mr.status = 'active'
                ORDER BY fm.domain ASC, fm.id ASC
                """
            )
            grouped: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                domain = row["domain"]
                grouped.setdefault(domain, []).append(
                    {
                        "field_name": row["field_name"],
                        "task_type": row["task_type"],
                        "source_data_type": row["source_data_type"],
                        "source_selector": row["source_selector"],
                        "target_data_type": row["target_data_type"],
                        "target_selector": row["target_selector"],
                        "ai_model_name": row["ai_model_name"],
                        "version": row["version"],
                        "ai_runtime": row["ai_runtime"],
                        "ai_model_filename": row["ai_model_filename"],
                        "lifecycle_state": row["lifecycle_state"],
                    }
                )
            return grouped

    def propose_field_mapping(
        self,
        domain: str,
        task_type: str,
        source_data_type: str,
        source_selector: str,
        target_data_type: str,
        target_selector: str,
        proposed_field_name: str,
        reported_by: int,
        reported_by_kind: str = "legacy_api_key",
        reported_by_user_id: int | None = None,
    ) -> dict[str, Any] | None:
        clean_domain = self._normalize_domain(domain)
        if not clean_domain:
            return None
        with self._lock:
            with self.connect() as conn:
                now = datetime.now(timezone.utc).isoformat()
                exists = conn.execute(
                    """
                    SELECT id FROM field_mapping_proposals
                    WHERE domain = ? AND task_type = ? AND source_selector = ? AND target_selector = ? AND status = 'pending'
                    """,
                    (clean_domain, task_type, source_selector, target_selector),
                ).fetchone()
                if exists:
                    return dict(conn.execute("SELECT * FROM field_mapping_proposals WHERE id = ?", (exists["id"],)).fetchone())
                approved_exists = conn.execute(
                    """
                    SELECT id FROM field_mappings
                    WHERE domain = ? AND task_type = ? AND source_selector = ? AND target_selector = ?
                    LIMIT 1
                    """,
                    (clean_domain, task_type, source_selector, target_selector),
                ).fetchone()
                if approved_exists:
                    return None
                cursor = conn.execute(
                    """
                    INSERT INTO field_mapping_proposals (
                        domain, task_type, source_data_type, source_selector, target_data_type, target_selector,
                        proposed_field_name, reported_by, reported_by_kind, reported_by_user_id, status, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                    """,
                    (
                        clean_domain,
                        task_type,
                        source_data_type,
                        source_selector,
                        target_data_type,
                        target_selector,
                        proposed_field_name,
                        reported_by,
                        reported_by_kind,
                        reported_by_user_id,
                        now,
                    ),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM field_mapping_proposals WHERE id = ?",
                    (cursor.lastrowid,),
                ).fetchone()
                return dict(row) if row else None

    def get_field_mapping_proposal_by_selectors(
        self,
        domain: str | None,
        source_selector: str,
        target_selector: str,
        task_type: str = "image",
    ) -> dict[str, Any] | None:
        clean_domain = self._normalize_domain(domain)
        if not clean_domain:
            return None
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM field_mapping_proposals
                WHERE domain = ? AND task_type = ? AND source_selector = ? AND target_selector = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (clean_domain, task_type, source_selector or "", target_selector or ""),
            ).fetchone()
            return dict(row) if row else None

    def add_retrain_sample(
        self,
        domain: str,
        image_path: str,
        reported_by: int,
        task_type: str = "image",
        field_name: str | None = None,
        label_text: str | None = None,
        reported_by_kind: str = "legacy_api_key",
        reported_by_user_id: int | None = None,
    ) -> int | None:
        clean_domain = self._normalize_domain(domain)
        if not clean_domain or not image_path or int(reported_by or 0) <= 0:
            return None
        with self._lock:
            with self.connect() as conn:
                now = datetime.now(timezone.utc).isoformat()
                cursor = conn.execute(
                    """
                    INSERT INTO retrain_samples (
                        domain, image_path, task_type, field_name, reported_by, reported_by_kind,
                        reported_by_user_id, status, label_text, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)
                    """,
                    (
                        clean_domain,
                        image_path,
                        task_type,
                        field_name,
                        int(reported_by),
                        reported_by_kind,
                        reported_by_user_id,
                        label_text,
                        now,
                    ),
                )
                conn.commit()
                return int(cursor.lastrowid)

    def get_pending_field_mapping_proposals(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM field_mapping_proposals
                WHERE status = 'pending'
                ORDER BY id DESC
                """
            )
            return [dict(row) for row in rows]

    def mark_field_mapping_proposal_status(self, proposal_id: int, status: str) -> None:
        with self._lock:
            with self.connect() as conn:
                conn.execute(
                    "UPDATE field_mapping_proposals SET status = ? WHERE id = ?",
                    (status, proposal_id),
                )
                conn.commit()

    def delete_field_mapping_proposal(self, proposal_id: int) -> bool:
        """Permanently delete a field-mapping proposal. Returns True if deleted."""
        with self._lock:
            with self.connect() as conn:
                cur = conn.execute(
                    "DELETE FROM field_mapping_proposals WHERE id = ?", (proposal_id,)
                )
                conn.commit()
                return cur.rowcount > 0

    def update_field_mapping_proposal(self, proposal_id: int, **fields) -> bool:
        """Patch editable columns on a field-mapping proposal.

        Accepted keys: domain, task_type, source_selector, target_selector,
                        proposed_field_name, source_data_type, target_data_type, status
        Returns True if a row was updated.
        """
        allowed = {
            "domain", "task_type", "source_selector", "target_selector",
            "proposed_field_name", "source_data_type", "target_data_type", "status",
        }
        parts, params = [], []
        for k, v in fields.items():
            if k in allowed and v is not None:
                parts.append(f"{k} = ?")
                params.append(v)
        if not parts:
            return False
        params.append(proposal_id)
        # SAFETY: column names in `parts` are validated against the `allowed` set above.
        # Parameters use ? placeholders.
        sql = f"UPDATE field_mapping_proposals SET {', '.join(parts)} WHERE id = ?"
        with self._lock:
            with self.connect() as conn:
                cur = conn.execute(sql, params)
                conn.commit()
                return cur.rowcount > 0


    def get_field_mapped_model(
        self,
        domain: str | None,
        field_name: str | None,
        task_type: str,
    ) -> dict[str, Any] | None:
        domain_candidates = self._domain_candidates(domain)
        if not domain_candidates:
            return None
        with self.connect() as conn:
            for candidate in domain_candidates:
                if field_name:
                    row = conn.execute(
                        """
                        SELECT mr.ai_runtime, mr.ai_model_filename, mr.status, mr.lifecycle_state
                        FROM field_mappings fm
                        JOIN model_registry mr ON mr.id = fm.ai_model_id
                        WHERE fm.domain = ? AND fm.field_name = ? AND fm.task_type = ?
                        ORDER BY CASE mr.lifecycle_state
                            WHEN 'production' THEN 0
                            WHEN 'staging' THEN 1
                            WHEN 'candidate' THEN 2
                            ELSE 3
                        END
                        LIMIT 1
                        """,
                        (candidate, field_name, task_type),
                    ).fetchone()
                    if row:
                        data = dict(row)
                        if data.get("status") == "active":
                            return data
            return None

    def set_lifecycle_state(
        self,
        ai_model_id: int,
        to_state: str,
        changed_by: int | None,
        reason: str | None = None,
    ) -> None:
        with self._lock:
            with self.connect() as conn:
                row = conn.execute(
                    "SELECT lifecycle_state FROM model_registry WHERE id = ?",
                    (ai_model_id,),
                ).fetchone()
                if not row:
                    return
                from_state = row["lifecycle_state"]
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "UPDATE model_registry SET lifecycle_state = ?, updated_at = ? WHERE id = ?",
                    (to_state, now, ai_model_id),
                )
                conn.execute(
                    """
                    INSERT INTO model_lifecycle_events (ai_model_id, from_state, to_state, reason, changed_by, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (ai_model_id, from_state, to_state, reason, changed_by, now),
                )
                conn.commit()

    def get_latest_model_by_state(self, task_type: str, lifecycle_state: str, exclude_id: int | None = None) -> dict[str, Any] | None:
        with self.connect() as conn:
            query = """
                SELECT * FROM model_registry
                WHERE task_type = ? AND lifecycle_state = ? AND status = 'active'
            """
            params: list[Any] = [task_type, lifecycle_state]
            if exclude_id is not None:
                query += " AND id != ?"
                params.append(exclude_id)
            query += " ORDER BY updated_at DESC, id DESC LIMIT 1"
            row = conn.execute(query, tuple(params)).fetchone()
            return dict(row) if row else None
