"""Audit logging service — records all critical admin actions."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.models import AuditLog


class AuditService:
    """Writes audit logs for admin and system actions."""

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def _session(self) -> Session:
        return self._session_factory()

    def log(
        self,
        actor_type: str,      # admin, system, integration, user
        action: str,
        actor_id: int | None = None,
        target_type: str | None = None,
        target_id: int | None = None,
        before_json: str | None = None,
        after_json: str | None = None,
        ip_address: str | None = None,
    ) -> AuditLog:
        session = self._session()
        try:
            entry = AuditLog(
                actor_type=actor_type,
                actor_id=actor_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                before_json=before_json,
                after_json=after_json,
                ip_address=ip_address,
            )
            session.add(entry)
            session.commit()
            session.refresh(entry)
            return entry
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def list_logs(
        self,
        actor_type: str | None = None,
        action: str | None = None,
        target_type: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[AuditLog], int]:
        session = self._session()
        try:
            q = session.query(AuditLog)
            if actor_type:
                q = q.filter(AuditLog.actor_type == actor_type)
            if action:
                q = q.filter(AuditLog.action == action)
            if target_type:
                q = q.filter(AuditLog.target_type == target_type)
            total = q.count()
            logs = q.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()
            return logs, total
        finally:
            session.close()
