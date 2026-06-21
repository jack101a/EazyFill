"""Usage event service."""

from __future__ import annotations

from app.core.database import Database


class UsageService:
    """Persist and aggregate usage."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def record(
        self,
        key_id: int,
        task_type: str,
        status: str,
        processing_ms: int,
        ip: str | None = None,
        model_used: str | None = None,
        domain: str | None = None,
    ) -> None:
        """Store single usage event."""

        self._db.insert_usage_event(
            key_id=key_id,
            task_type=task_type,
            status=status,
            processing_ms=processing_ms,
            model_used=model_used,
            domain=domain,
            ip=ip,
        )

    def summary(self, key_id: int) -> dict:
        """Return key usage summary."""

        return self._db.get_usage_summary(key_id=key_id)
