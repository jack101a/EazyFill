import base64
import hashlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
import app.core.models  # noqa: F401
from app.services.sync_service import SyncConflictError, SyncIntegrityError, SyncService


def _session_factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _blob_payload(raw: bytes = b"encrypted bytes"):
    return (
        base64.b64encode(raw).decode("ascii"),
        "sha256:" + hashlib.sha256(raw).hexdigest(),
    )


def test_sync_service_push_pull_status_and_delete():
    service = SyncService(_session_factory())
    encrypted_blob, blob_hash = _blob_payload()

    pushed = service.push_blob(
        42,
        device_id="device-1",
        sync_version=1,
        encrypted_blob_base64=encrypted_blob,
        blob_hash=blob_hash,
    )
    pulled = service.pull_blob(42)
    status = service.status(42)
    deleted = service.delete_blob(42)

    assert pushed["sync_version"] == 1
    assert pulled["found"] is True
    assert pulled["encrypted_blob"] == encrypted_blob
    assert status["blob_hash"] == blob_hash
    assert deleted["deleted"] is True
    assert service.pull_blob(42)["found"] is False


def test_sync_service_rejects_hash_mismatch():
    service = SyncService(_session_factory())
    encrypted_blob, _blob_hash = _blob_payload()

    with pytest.raises(SyncIntegrityError):
        service.push_blob(
            42,
            device_id="device-1",
            sync_version=1,
            encrypted_blob_base64=encrypted_blob,
            blob_hash="sha256:bad",
        )


def test_sync_service_rejects_stale_versions():
    service = SyncService(_session_factory())
    encrypted_blob, blob_hash = _blob_payload()
    service.push_blob(
        42,
        device_id="device-1",
        sync_version=3,
        encrypted_blob_base64=encrypted_blob,
        blob_hash=blob_hash,
    )

    with pytest.raises(SyncConflictError) as exc:
        service.push_blob(
            42,
            device_id="device-2",
            sync_version=2,
            encrypted_blob_base64=encrypted_blob,
            blob_hash=blob_hash,
        )

    assert exc.value.current_version == 3
