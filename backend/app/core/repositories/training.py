from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from .base import BaseRepository

class TrainingRepository(BaseRepository):
    def insert_retrain_sample(
        self,
        domain: str,
        image_path: str,
        reported_by: int,
        task_type: str = "image",
        field_name: str | None = None,
        reported_by_kind: str = "legacy_api_key",
        reported_by_user_id: int | None = None,
    ) -> int:
        with self._lock:
            with self.connect() as conn:
                now = datetime.now(timezone.utc).isoformat()
                cursor = conn.execute(
                    """
                    INSERT INTO retrain_samples (
                        domain, image_path, task_type, field_name, reported_by,
                        reported_by_kind, reported_by_user_id, status, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?)
                    """,
                    (
                        domain,
                        image_path,
                        task_type,
                        field_name,
                        reported_by,
                        reported_by_kind,
                        reported_by_user_id,
                        now,
                    ),
                )
                conn.commit()
                return int(cursor.lastrowid)

    def get_retrain_samples(self, status: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM retrain_samples WHERE status = ? ORDER BY id ASC LIMIT ?",
                (status, limit),
            )
            return [dict(row) for row in rows]

    def label_retrain_sample(self, sample_id: int, label_text: str, labeled_by: int | None) -> None:
        with self._lock:
            with self.connect() as conn:
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    """
                    UPDATE retrain_samples
                    SET status = 'labeled', label_text = ?, labeled_by = ?, labeled_at = ?
                    WHERE id = ?
                    """,
                    (label_text, labeled_by, now, sample_id),
                )
                conn.commit()

    def reject_retrain_sample(self, sample_id: int, labeled_by: int | None) -> None:
        with self._lock:
            with self.connect() as conn:
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    """
                    UPDATE retrain_samples
                    SET status = 'rejected', labeled_by = ?, labeled_at = ?
                    WHERE id = ?
                    """,
                    (labeled_by, now, sample_id),
                )
                conn.commit()

    def get_retrain_sample_counts(self) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS c FROM retrain_samples GROUP BY status"
            )
            counts = {"queued": 0, "labeled": 0, "rejected": 0, "consumed": 0}
            for row in rows:
                counts[row["status"]] = int(row["c"])
            return counts

    def upsert_failed_payload_label(
        self,
        filename: str,
        domain: str,
        ai_guess: str | None,
        corrected_text: str,
    ) -> None:
        with self._lock:
            with self.connect() as conn:
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    """
                    INSERT INTO failed_payload_labels (filename, domain, ai_guess, corrected_text, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(filename) DO UPDATE SET
                        domain = excluded.domain,
                        ai_guess = excluded.ai_guess,
                        corrected_text = excluded.corrected_text,
                        updated_at = excluded.updated_at
                    """,
                    (filename, domain, ai_guess, corrected_text, now),
                )
                conn.commit()

    def get_failed_payload_labels(self) -> dict[str, dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT filename, domain, ai_guess, corrected_text, updated_at FROM failed_payload_labels ORDER BY updated_at DESC"
            )
            return {
                row["filename"]: {
                    "domain": row["domain"],
                    "ai_guess": row["ai_guess"],
                    "corrected_text": row["corrected_text"],
                    "updated_at": row["updated_at"],
                }
                for row in rows
            }

    def create_retrain_job(
        self,
        requested_by: int | None,
        min_samples: int,
        notes: str | None,
        scheduled_for: str | None = None,
    ) -> int:
        with self._lock:
            with self.connect() as conn:
                now = datetime.now(timezone.utc).isoformat()
                when = scheduled_for or now
                cursor = conn.execute(
                    """
                    INSERT INTO retrain_jobs (status, scheduled_for, requested_by, min_samples, notes)
                    VALUES ('queued', ?, ?, ?, ?)
                    """,
                    (when, requested_by, min_samples, notes),
                )
                conn.commit()
                return int(cursor.lastrowid)

    def get_due_retrain_jobs(self, now_iso: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM retrain_jobs
                WHERE status = 'queued' AND scheduled_for <= ?
                ORDER BY id ASC
                """,
                (now_iso,),
            )
            return [dict(row) for row in rows]

    def mark_retrain_job_running(self, job_id: int) -> None:
        with self._lock:
            with self.connect() as conn:
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "UPDATE retrain_jobs SET status='running', started_at=? WHERE id=?",
                    (now, job_id),
                )
                conn.commit()

    def mark_retrain_job_done(self, job_id: int, produced_ai_model_id: int | None, total_samples: int) -> None:
        with self._lock:
            with self.connect() as conn:
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    """
                    UPDATE retrain_jobs
                    SET status='completed', finished_at=?, produced_ai_model_id=?, total_samples=?
                    WHERE id=?
                    """,
                    (now, produced_ai_model_id, total_samples, job_id),
                )
                conn.commit()

    def mark_retrain_job_failed(self, job_id: int, error_message: str) -> None:
        with self._lock:
            with self.connect() as conn:
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    """
                    UPDATE retrain_jobs
                    SET status='failed', finished_at=?, error_message=?
                    WHERE id=?
                    """,
                    (now, error_message[:500], job_id),
                )
                conn.commit()

    def get_retrain_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM retrain_jobs ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            return [dict(row) for row in rows]

    def claim_labeled_samples(self, job_id: int, limit: int) -> list[dict[str, Any]]:
        with self._lock:
            with self.connect() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM retrain_samples
                    WHERE status = 'labeled' AND consumed_by_job_id IS NULL
                    ORDER BY id ASC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
                sample_ids = [int(row["id"]) for row in rows]
                if sample_ids:
                    conn.executemany(
                        "UPDATE retrain_samples SET consumed_by_job_id = ?, status = 'consumed' WHERE id = ?",
                        [(job_id, sample_id) for sample_id in sample_ids],
                    )
                    conn.commit()
                return [dict(row) for row in rows]

    def release_job_claims(self, job_id: int) -> None:
        with self._lock:
            with self.connect() as conn:
                conn.execute(
                    """
                    UPDATE retrain_samples
                    SET consumed_by_job_id = NULL, status = 'labeled'
                    WHERE consumed_by_job_id = ?
                    """,
                    (job_id,),
                )
                conn.commit()

    def insert_active_learning(self, domain: str, image_path: str, reported_by: int) -> None:
        with self._lock:
            with self.connect() as conn:
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "INSERT INTO active_learning (domain, image_path, reported_by, created_at) VALUES (?, ?, ?, ?)",
                    (domain, image_path, reported_by, now)
                )
                conn.commit()

    def get_active_learning_samples(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM active_learning ORDER BY id DESC LIMIT ?", (limit,))]
