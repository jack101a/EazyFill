"""Encrypted EazyFill sync blob storage."""

from __future__ import annotations

import base64
import binascii
import hashlib
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.models import EncryptedBackup


DEFAULT_MAX_BLOB_BYTES = 10 * 1024 * 1024


class SyncServiceError(Exception):
    """Base class for sync service errors."""


class SyncBlobTooLargeError(SyncServiceError):
    """Raised when an encrypted sync blob exceeds the caller's quota."""


class SyncIntegrityError(SyncServiceError):
    """Raised when the encrypted blob fails transport integrity checks."""


class SyncConflictError(SyncServiceError):
    """Raised when a client tries to overwrite a newer backup."""

    def __init__(self, current_version: int) -> None:
        super().__init__("sync version conflict")
        self.current_version = int(current_version)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SyncService:
    """Stores encrypted backup blobs without decrypting user data."""

    def __init__(self, session_factory, *, default_max_blob_bytes: int = DEFAULT_MAX_BLOB_BYTES) -> None:
        self._session_factory = session_factory
        self._default_max_blob_bytes = max(1, int(default_max_blob_bytes))

    def _session(self) -> Session:
        return self._session_factory()

    def push_blob(
        self,
        user_id: int,
        *,
        device_id: str,
        sync_version: int,
        encrypted_blob_base64: str,
        blob_hash: str,
        max_blob_bytes: int | None = None,
    ) -> dict[str, Any]:
        blob = self._decode_blob(encrypted_blob_base64)
        max_size = max(1, int(max_blob_bytes or self._default_max_blob_bytes))
        if len(blob) > max_size:
            raise SyncBlobTooLargeError(f"sync blob exceeds {max_size} bytes")
        self._verify_hash(blob, blob_hash)

        version = max(1, int(sync_version or 1))
        now = _utcnow()
        session = self._session()
        try:
            backup = session.query(EncryptedBackup).filter(EncryptedBackup.user_id == int(user_id)).first()
            if backup and int(backup.sync_version or 0) > version:
                raise SyncConflictError(int(backup.sync_version or 0))
            if backup is None:
                backup = EncryptedBackup(
                    user_id=int(user_id),
                    device_id=str(device_id or "")[:255],
                    sync_version=version,
                    encrypted_blob=blob,
                    blob_hash=blob_hash,
                    blob_size_bytes=len(blob),
                    created_at=now,
                    updated_at=now,
                )
                session.add(backup)
            else:
                backup.device_id = str(device_id or "")[:255]
                backup.sync_version = version
                backup.encrypted_blob = blob
                backup.blob_hash = blob_hash
                backup.blob_size_bytes = len(blob)
                backup.updated_at = now
            session.commit()
            return self._metadata(backup)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def pull_blob(self, user_id: int) -> dict[str, Any]:
        session = self._session()
        try:
            backup = session.query(EncryptedBackup).filter(EncryptedBackup.user_id == int(user_id)).first()
            if backup is None:
                return {"found": False}
            return {
                "found": True,
                **self._metadata(backup),
                "encrypted_blob": base64.b64encode(bytes(backup.encrypted_blob)).decode("ascii"),
            }
        finally:
            session.close()

    def status(self, user_id: int) -> dict[str, Any]:
        session = self._session()
        try:
            backup = session.query(EncryptedBackup).filter(EncryptedBackup.user_id == int(user_id)).first()
            if backup is None:
                return {"found": False, "sync_version": 0, "blob_size_bytes": 0, "updated_at": None}
            return {"found": True, **self._metadata(backup)}
        finally:
            session.close()

    def delete_blob(self, user_id: int) -> dict[str, Any]:
        session = self._session()
        try:
            backup = session.query(EncryptedBackup).filter(EncryptedBackup.user_id == int(user_id)).first()
            if backup is None:
                return {"deleted": False}
            session.delete(backup)
            session.commit()
            return {"deleted": True}
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def _decode_blob(encrypted_blob_base64: str) -> bytes:
        try:
            return base64.b64decode(str(encrypted_blob_base64 or ""), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise SyncIntegrityError("encrypted_blob must be valid base64") from exc

    @staticmethod
    def _verify_hash(blob: bytes, blob_hash: str) -> None:
        expected = str(blob_hash or "").strip().lower()
        actual = "sha256:" + hashlib.sha256(blob).hexdigest()
        if not expected.startswith("sha256:") or expected != actual:
            raise SyncIntegrityError("blob_hash does not match encrypted_blob")

    @staticmethod
    def _metadata(backup: EncryptedBackup) -> dict[str, Any]:
        return {
            "device_id": backup.device_id,
            "sync_version": int(backup.sync_version or 0),
            "blob_hash": backup.blob_hash,
            "blob_size_bytes": int(backup.blob_size_bytes or 0),
            "created_at": backup.created_at.isoformat() if backup.created_at else None,
            "updated_at": backup.updated_at.isoformat() if backup.updated_at else None,
        }
