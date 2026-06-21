"""User management service — CRUD operations for the users domain."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.models import User


class UserService:
    """Manages user lifecycle: create, update, status changes, queries."""

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def _session(self) -> Session:
        return self._session_factory()

    def create_user(
        self,
        full_name: str = "",
        email: str | None = None,
        mobile_number: str | None = None,
        notes: str = "",
        created_by_admin_id: int | None = None,
    ) -> User:
        session = self._session()
        try:
            user = User(
                full_name=full_name,
                email=email,
                mobile_number=mobile_number,
                status="pending_payment",
                notes=notes,
                created_by_admin_id=created_by_admin_id,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            return user
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_user(self, user_id: int) -> User | None:
        session = self._session()
        try:
            return session.query(User).filter(User.id == user_id).first()
        finally:
            session.close()

    def get_user_by_mobile(self, mobile: str) -> User | None:
        session = self._session()
        try:
            return session.query(User).filter(User.mobile_number == mobile).first()
        finally:
            session.close()

    def get_user_by_email(self, email: str) -> User | None:
        session = self._session()
        try:
            return session.query(User).filter(User.email == str(email or "").strip().lower()).first()
        finally:
            session.close()

    def list_users(
        self,
        status: str | None = None,
        plan_id: int | None = None,
        search: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[User], int]:
        session = self._session()
        try:
            q = session.query(User)
            if status:
                q = q.filter(User.status == status)
            if search:
                q = q.filter(
                    (User.full_name.ilike(f"%{search}%"))
                    | (User.email.ilike(f"%{search}%"))
                    | (User.mobile_number.ilike(f"%{search}%"))
                )
            total = q.count()
            users = q.order_by(User.created_at.desc()).offset(offset).limit(limit).all()
            return users, total
        finally:
            session.close()

    def update_user(
        self,
        user_id: int,
        full_name: str | None = None,
        email: str | None = None,
        mobile_number: str | None = None,
        notes: str | None = None,
        updated_by_admin_id: int | None = None,
    ) -> User | None:
        session = self._session()
        try:
            user = session.query(User).filter(User.id == user_id).first()
            if not user:
                return None
            if full_name is not None:
                user.full_name = full_name
            if email is not None:
                user.email = email
            if mobile_number is not None:
                user.mobile_number = mobile_number
            if notes is not None:
                user.notes = notes
            if updated_by_admin_id is not None:
                user.updated_by_admin_id = updated_by_admin_id
            user.updated_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(user)
            return user
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def set_user_status(
        self,
        user_id: int,
        status: str,
        updated_by_admin_id: int | None = None,
    ) -> User | None:
        """Set user status: active, blocked, inactive, expired, deleted."""
        session = self._session()
        try:
            user = session.query(User).filter(User.id == user_id).first()
            if not user:
                return None
            user.status = status
            user.updated_at = datetime.now(timezone.utc)
            if updated_by_admin_id is not None:
                user.updated_by_admin_id = updated_by_admin_id
            session.commit()
            session.refresh(user)
            return user
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def delete_user(self, user_id: int) -> bool:
        """Soft-delete: set status to 'deleted'."""
        return self.set_user_status(user_id, "deleted") is not None
