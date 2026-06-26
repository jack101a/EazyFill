"""Backup and restore service - portable system/user backup packages."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import logging
import os
import gzip
import shutil
import sqlite3
import subprocess
import tarfile
import time
import zipfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlencode, urlparse

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import JSON as SAJSON
from sqlalchemy import Boolean, Date, DateTime, MetaData, Table, Time, delete, insert, inspect, select, text

from app.core.config import Settings
from app.core.db import Base, get_engine, get_session
from app.core.paths import get_project_root
from app.core.sqlite import sqlite_connect

logger = logging.getLogger(__name__)

BACKUP_VERSION = 1
DEFAULT_BACKUP_SIZE_CAP_BYTES = 2 * 1024 * 1024 * 1024
REMOTE_BACKUP_SIZE_PRUNE_RATIO = 0.9
TELEGRAM_PUBLIC_SEND_LIMIT_BYTES = 50 * 1024 * 1024
TELEGRAM_PUBLIC_DOWNLOAD_LIMIT_BYTES = 20 * 1024 * 1024
AEAD_BACKUP_MAGIC = b"EAZYFILL-UPBAK-AESGCM-V1\n"
SYSTEM_FILE_ROOTS = [
    "data/models",
    "data/userscripts",
]
USER_TABLES = [
    "users",
    "subscription_plans",
    "user_subscriptions",
    "payment_records",
    "payment_webhook_events",
    "user_api_keys",
    "user_api_key_devices",
    "usage_cycles",
    "encrypted_backups",
    "audit_logs",
    "api_keys",
    "api_key_allowed_domains",
    "api_key_rate_limits",
    "api_key_device_bindings",
    "usage_events",
]

ADMIN_BACKUP_CATEGORIES = ("full", "system", "users")
SPLIT_BACKUP_CATEGORIES = {"full", "system", "users", "postgres"}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str).encode("utf-8")


def _xor_stream(data: bytes, key: str) -> bytes:
    """Legacy reversible stream used by older .upbak packages."""
    if not key:
        return data
    secret = key.encode("utf-8")
    out = bytearray()
    counter = 0
    while len(out) < len(data):
        out.extend(hmac.new(secret, counter.to_bytes(8, "big"), hashlib.sha256).digest())
        counter += 1
    return bytes(a ^ b for a, b in zip(data, out, strict=False))


def _backup_aead_key(key: str) -> bytes:
    return hashlib.sha256(key.encode("utf-8")).digest()


def _encrypt_package_bytes(data: bytes, key: str) -> bytes:
    if not key:
        return data
    nonce = os.urandom(12)
    ciphertext = AESGCM(_backup_aead_key(key)).encrypt(nonce, data, AEAD_BACKUP_MAGIC)
    return AEAD_BACKUP_MAGIC + nonce + ciphertext


def _decrypt_package_bytes(data: bytes, key: str) -> bytes:
    if not key:
        return data
    if data.startswith(AEAD_BACKUP_MAGIC):
        offset = len(AEAD_BACKUP_MAGIC)
        nonce = data[offset:offset + 12]
        ciphertext = data[offset + 12:]
        if len(nonce) != 12 or not ciphertext:
            raise ValueError("encrypted backup package is truncated")
        return AESGCM(_backup_aead_key(key)).decrypt(nonce, ciphertext, AEAD_BACKUP_MAGIC)
    return _xor_stream(data, key)


class BackupService:
    """Manages local packages, restore validation, and cloud backup sync."""

    # System backup: platform configuration and data files
    SYSTEM_FILE_PATHS = [
        "data/models/",
        "data/userscripts/",
        "backend/config/config.yaml",
    ]

    SYSTEM_DB_TABLES = [
        "access_control",
        "allowed_domains",
        "model_routes",
        "model_registry",
        "field_mappings",
        "field_mapping_proposals",
        "retrain_samples",
        "retrain_jobs",
        "model_lifecycle_events",
        "active_learning",
        "failed_payload_labels",
        "platform_settings",
    ]

    USER_DB_TABLES = USER_TABLES.copy()

    def __init__(self, settings: Settings):
        self._settings = settings
        self._root = get_project_root()
        self._db_path = Path(settings.storage.sqlite_path)
        self._backup_dir = self._root / "backend" / "backups"
        self._backup_dir.mkdir(parents=True, exist_ok=True)

    def full_backup(self) -> dict:
        started = datetime.now(UTC)
        backup_id = f"backup_{started.strftime('%Y%m%d_%H%M%S')}"
        result = {
            "backup_id": backup_id,
            "type": "full-package",
            "started_at": started.isoformat(),
            "status": "running",
        }
        try:
            package = self.create_package(backup_id=backup_id)
            latest_name = self._latest_backup_filename("full", Path(package["path"]))
            latest_path = self._backup_dir / latest_name
            latest_path.unlink(missing_ok=True)
            shutil.copy2(str(package["path"]), str(latest_path))
            result.update({
                "status": "completed",
                "finished_at": datetime.now(UTC).isoformat(),
                "file_path_or_uri": str(package["path"]),
                "checksum": package["checksum"],
                "size_bytes": package["size_bytes"],
                "encrypted": package["encrypted"],
                "latest_file": latest_name,
            })
            self._prune_local_backups_by_size()
            self._log_backup_run(result)
            if self._truthy_setting("backup.gdrive.enabled"):
                self.upload_to_gdrive(Path(package["path"]))
            return result
        except Exception as exc:
            result["status"] = "failed"
            result["error"] = str(exc)
            self._log_backup_run(result)
            logger.exception("backup_failed", extra={"context": result})
            return result

    def create_package(self, backup_id: str | None = None) -> dict:
        created = datetime.now(UTC)
        backup_id = backup_id or f"backup_{created.strftime('%Y%m%d_%H%M%S')}"
        payload = self._build_payload(backup_id, created)
        clear_bytes = self._zip_payload(payload)
        encryption_key = self._backup_encryption_key()
        stored_bytes = _encrypt_package_bytes(clear_bytes, encryption_key)
        suffix = ".upbak" if encryption_key else ".zip"
        package_path = self._backup_dir / f"{backup_id}{suffix}"
        package_path.write_bytes(stored_bytes)
        return {
            "backup_id": backup_id,
            "path": package_path,
            "checksum": _sha256(stored_bytes),
            "size_bytes": package_path.stat().st_size,
            "encrypted": bool(encryption_key),
        }

    def validate_package(self, package_path: str | Path) -> dict:
        package = Path(package_path)
        clear_bytes = self._read_package_bytes(package)
        with zipfile.ZipFile(io.BytesIO(clear_bytes)) as zf:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            for name, expected in manifest.get("checksums", {}).items():
                actual = _sha256(zf.read(name))
                if actual != expected:
                    return {"ok": False, "error": f"checksum mismatch: {name}"}
        return {"ok": True, "manifest": manifest}

    def restore_from_backup(self, backup_id: str) -> dict:
        candidates = [self._backup_dir / backup_id]
        if not Path(backup_id).suffix:
            candidates += [self._backup_dir / f"{backup_id}.upbak", self._backup_dir / f"{backup_id}.zip"]
        package = next((item for item in candidates if item.exists()), None)
        if not package:
            return {"status": "failed", "error": f"Backup {backup_id} not found"}
        return self.restore_package(package)

    def restore_package(self, package_path: str | Path) -> dict:
        package = Path(package_path)
        try:
            validation = self.validate_package(package)
            if not validation.get("ok"):
                return {"status": "failed", "error": validation.get("error")}
            clear_bytes = self._read_package_bytes(package)
            with zipfile.ZipFile(io.BytesIO(clear_bytes)) as zf:
                system_data = json.loads(zf.read("system-data.json").decode("utf-8"))
                user_data = json.loads(zf.read("user-data.json").decode("utf-8"))
                self._restore_system_data(system_data)
                self._restore_user_data(user_data)
                self._restore_files(zf)
            return {"status": "completed", "backup": str(package), "manifest": validation["manifest"]}
        except Exception as exc:
            logger.exception("restore_failed", extra={"context": {"error": str(exc)}})
            return {"status": "failed", "error": str(exc)}

    def import_system_bundle(self, package_path: str | Path) -> dict:
        package = Path(package_path)
        try:
            validation = self.validate_package(package)
            if not validation.get("ok"):
                return {"status": "failed", "error": validation.get("error")}
            clear_bytes = self._read_package_bytes(package)
            with zipfile.ZipFile(io.BytesIO(clear_bytes)) as zf:
                names = set(zf.namelist())
                if "system-data.json" in names:
                    system_data = json.loads(zf.read("system-data.json").decode("utf-8"))
                    if system_data:
                        self._restore_system_data(system_data)
                self._restore_files(zf)
            manifest = validation["manifest"]
            return {
                "status": "completed",
                "bundle": str(package),
                "file_count": int(manifest.get("file_count") or 0),
                "manifest": manifest,
            }
        except Exception as exc:
            logger.exception("system_bundle_import_failed", extra={"context": {"error": str(exc)}})
            return {"status": "failed", "error": str(exc)}

    def list_backups(self) -> list[dict]:
        backups = []
        for item in sorted(self._backup_dir.glob("backup_*.*"), key=lambda p: p.stat().st_mtime, reverse=True):
            if item.suffix not in {".upbak", ".zip"}:
                continue
            backups.append({
                "id": item.stem,
                "name": item.name,
                "created": datetime.fromtimestamp(item.stat().st_mtime, tz=UTC).isoformat(),
                "size_bytes": item.stat().st_size,
                "path": str(item),
                "encrypted": item.suffix == ".upbak",
            })
        return backups

    def get_backup_health(self) -> dict:
        backups = self.list_backups()
        gdrive_token = self._gdrive_token_data()
        return {
            "total_backups": len(backups),
            "last_backup": backups[0] if backups else None,
            "backup_dir": str(self._backup_dir),
            "db_type": self._settings.storage.db_type,
            "gdrive_enabled": self._truthy_setting("backup.gdrive.enabled"),
            "gdrive_client_configured": bool(self._gdrive_client_id() and self._gdrive_client_secret()),
            "gdrive_connected": bool(gdrive_token.get("refresh_token") or gdrive_token.get("access_token")),
            "gdrive_folder_id_set": bool(self._setting("backup.gdrive.folder_id")),
            "gdrive_last_error": self._setting("backup.gdrive.last_error"),
            "gdrive_last_file_id": self._setting("backup.gdrive.last_file_id"),
        }

    def gdrive_auth_url(self, redirect_uri: str) -> dict:
        client_id = self._gdrive_client_id()
        if not client_id:
            return {"ok": False, "error": "Google Drive OAuth client is not configured (set GOOGLE_DRIVE_CLIENT_ID or backup.gdrive.client_id)"}
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "https://www.googleapis.com/auth/drive.file",
            "access_type": "offline",
            "prompt": "consent",
        }
        return {"ok": True, "url": "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)}

    async def gdrive_exchange_code(self, code: str, redirect_uri: str) -> dict:
        client_id = self._gdrive_client_id()
        client_secret = self._gdrive_client_secret()
        if not client_id or not client_secret:
            return {"ok": False, "error": "Google Drive OAuth client is not configured (set GOOGLE_DRIVE_CLIENT_ID/GOOGLE_DRIVE_CLIENT_SECRET)"}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post("https://oauth2.googleapis.com/token", data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            })
        if resp.status_code >= 400:
            self._set_setting("backup.gdrive.last_error", resp.text)
            return {"ok": False, "error": resp.text}
        data = resp.json()
        existing = self._gdrive_token_data()
        if "refresh_token" not in data and existing.get("refresh_token"):
            data["refresh_token"] = existing["refresh_token"]
        if data.get("expires_in"):
            data["expires_at"] = int(time.time()) + int(data["expires_in"])
        self._save_gdrive_token_data(data)
        self._set_setting("backup.gdrive.enabled", "true")
        return {"ok": True, "expires_in": data.get("expires_in")}

    def upload_to_gdrive(self, package_path: Path) -> dict:
        token = self._gdrive_access_token()
        if not token:
            return {"ok": False, "error": "Google Drive is not connected"}
        metadata = {"name": package_path.name}
        folder_id = self._setting("backup.gdrive.folder_id")
        if folder_id:
            metadata["parents"] = [folder_id]
        try:
            init_resp = httpx.post(
                "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=UTF-8",
                    "X-Upload-Content-Type": "application/octet-stream",
                    "X-Upload-Content-Length": str(package_path.stat().st_size),
                },
                content=json.dumps(metadata).encode("utf-8"),
                timeout=30,
            )
            if init_resp.status_code >= 400:
                self._set_setting("backup.gdrive.last_error", init_resp.text)
                return {"ok": False, "error": init_resp.text}
            upload_url = init_resp.headers.get("Location")
            if not upload_url:
                error = "Google Drive did not return a resumable upload URL"
                self._set_setting("backup.gdrive.last_error", error)
                return {"ok": False, "error": error}
            with package_path.open("rb") as fh:
                upload_resp = httpx.put(
                    upload_url,
                    headers={
                        "Content-Type": "application/octet-stream",
                        "Content-Length": str(package_path.stat().st_size),
                    },
                    content=fh,
                    timeout=300,
                )
            if upload_resp.status_code >= 400:
                self._set_setting("backup.gdrive.last_error", upload_resp.text)
                return {"ok": False, "error": upload_resp.text}
            data = upload_resp.json()
            self._set_setting("backup.gdrive.last_file_id", data.get("id", ""))
            self._set_setting("backup.gdrive.last_error", "")
            return {"ok": True, "file_id": data.get("id")}
        except Exception as exc:
            self._set_setting("backup.gdrive.last_error", str(exc))
            return {"ok": False, "error": str(exc)}

    def _build_payload(self, backup_id: str, created: datetime) -> dict:
        system_data = self._export_system_data()
        user_data = self._export_user_data()
        files = self._collect_files()
        manifest = {
            "backup_version": BACKUP_VERSION,
            "backup_id": backup_id,
            "created_at": created.isoformat(),
            "db_type": self._settings.storage.db_type,
            "app": "eazyfill",
            "sections": ["system-data", "user-data"],
            "file_count": len(files),
            "checksums": {},
        }
        return {"manifest": manifest, "system": system_data, "user": user_data, "files": files}

    def _zip_payload(self, payload: dict) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            entries = {
                "system-data.json": _json_bytes(payload["system"]),
                "user-data.json": _json_bytes(payload["user"]),
            }
            for arcname, data in entries.items():
                payload["manifest"]["checksums"][arcname] = _sha256(data)
            for rel, abs_path in payload["files"].items():
                data = abs_path.read_bytes()
                arcname = f"files/{rel}"
                entries[arcname] = data
                payload["manifest"]["checksums"][arcname] = _sha256(data)
            manifest_bytes = _json_bytes(payload["manifest"])
            zf.writestr("manifest.json", manifest_bytes)
            for arcname, data in entries.items():
                zf.writestr(arcname, data)
        return buf.getvalue()

    def _export_system_data(self) -> dict:
        from app.core.database import Database

        db = Database(self._settings)
        db.init()
        return db.export_master_setup()

    def _export_user_data(self) -> dict:
        data: dict[str, list[dict]] = {}
        engine = get_engine()
        with engine.connect() as conn:
            for table in Base.metadata.sorted_tables:
                if table.name in USER_TABLES:
                    rows = conn.execute(select(table)).mappings().all()
                    data[table.name] = [dict(row) for row in rows]
        if self._settings.storage.db_type == "sqlite" and self._db_path.exists():
            data["sqlite_snapshot_sha256"] = self._sqlite_snapshot_hash()
        return data

    def _restore_user_data(self, data: dict) -> None:
        session = get_session()
        try:
            tables = [t for t in reversed(Base.metadata.sorted_tables) if t.name in USER_TABLES]
            for table in tables:
                session.execute(delete(table))
            for table in [t for t in Base.metadata.sorted_tables if t.name in USER_TABLES]:
                rows = data.get(table.name) or []
                if rows:
                    session.execute(insert(table), rows)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _restore_system_data(self, data: dict) -> None:
        from app.core.database import Database

        db = Database(self._settings)
        previous = os.getenv("EAZYFILL_SKIP_MASTER_KEY_ENSURE")
        os.environ["EAZYFILL_SKIP_MASTER_KEY_ENSURE"] = "1"
        try:
            db.init()
            db.import_master_setup(data)
        finally:
            if previous is None:
                os.environ.pop("EAZYFILL_SKIP_MASTER_KEY_ENSURE", None)
            else:
                os.environ["EAZYFILL_SKIP_MASTER_KEY_ENSURE"] = previous

    def _collect_files(self) -> dict[str, Path]:
        files: dict[str, Path] = {}
        for rel_root in SYSTEM_FILE_ROOTS:
            root = (self._root / rel_root).resolve()
            if not root.exists():
                continue
            for item in root.rglob("*"):
                if item.is_file():
                    files[str(item.relative_to(self._root)).replace("\\", "/")] = item
        return files

    def _restore_files(self, zf: zipfile.ZipFile) -> None:
        for name in zf.namelist():
            if not name.startswith("files/") or name.endswith("/"):
                continue
            rel = name.removeprefix("files/")
            target = (self._root / rel).resolve()
            if self._root.resolve() not in target.parents:
                raise ValueError(f"unsafe backup path: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(name))

    def _read_package_bytes(self, package: Path) -> bytes:
        data = package.read_bytes()
        return _decrypt_package_bytes(data, self._backup_encryption_key()) if package.suffix == ".upbak" else data

    def _sqlite_snapshot_hash(self) -> str:
        tmp = self._backup_dir / ".sqlite_snapshot.tmp"
        if tmp.exists():
            tmp.unlink()
        src = sqlite_connect(str(self._db_path))
        dst = sqlite_connect(str(tmp))
        src.backup(dst)
        dst.close()
        src.close()
        digest = _sha256(tmp.read_bytes())
        tmp.unlink(missing_ok=True)
        return digest

    def _prune_local_backups_by_size(self) -> None:
        cap_bytes = self._backup_size_cap_bytes()
        if cap_bytes <= 0:
            return
        threshold = int(cap_bytes * REMOTE_BACKUP_SIZE_PRUNE_RATIO)
        try:
            timestamped: list[tuple[str, Path]] = []
            timestamped.extend(("full", path) for path in self._backup_dir.glob("backup_*.*") if path.is_file() and path.suffix in {".upbak", ".zip"})
            timestamped.extend(("postgres", path) for path in (self._backup_dir / "postgres").glob("postgres_*") if path.is_file())
            timestamped.extend(("system", path) for path in (self._backup_dir / "system").glob("system_*") if path.is_file())
            timestamped.extend(("users", path) for path in (self._backup_dir / "users").glob("users_*") if path.is_file())
            latest = [
                path for path in [
                    self._backup_dir / "latest_full.upbak",
                    self._backup_dir / "latest_full.zip",
                    self._backup_dir / "postgres" / "latest_postgres.dump",
                    self._backup_dir / "system" / "latest_system.tar.gz",
                    self._backup_dir / "users" / "latest_users.json.gz",
                ]
                if path.is_file()
            ]
            total_size = sum(path.stat().st_size for _, path in timestamped) + sum(path.stat().st_size for path in latest)
            newest_by_kind: dict[str, Path] = {}
            for kind, path in sorted(timestamped, key=lambda item: item[1].stat().st_mtime, reverse=True):
                newest_by_kind.setdefault(kind, path)
            candidates = sorted(timestamped, key=lambda item: item[1].stat().st_mtime)
            for kind, path in candidates:
                if total_size <= threshold:
                    break
                if newest_by_kind.get(kind) == path:
                    continue
                size = path.stat().st_size
                path.unlink(missing_ok=True)
                total_size -= size
        except Exception as exc:
            logger.warning("local_backup_size_prune_failed", extra={"context": {"error": str(exc)}})

    def _log_backup_run(self, result: dict) -> None:
        try:
            from app.core.models import BackupRun

            session = get_session()
            run = BackupRun(
                backup_type=result["type"],
                status=result["status"],
                storage_target=str(self._backup_dir),
                started_at=datetime.fromisoformat(result["started_at"]),
                finished_at=datetime.fromisoformat(result.get("finished_at", result["started_at"])),
                file_path_or_uri=result.get("file_path_or_uri") or result.get("backup_id", ""),
                checksum=result.get("checksum"),
                error_message=result.get("error", ""),
            )
            session.add(run)
            session.commit()
            session.close()
        except Exception as exc:
            logger.warning("backup_log_failed", extra={"context": {"error": str(exc)}})

    def _setting(self, key: str, default: str = "") -> str:
        try:
            from app.core.database import Database

            db = Database(self._settings)
            db.init()
            return db.get_setting(key, default) or default
        except Exception:
            return os.getenv(key.upper().replace(".", "_"), default)

    def _set_setting(self, key: str, value: str) -> None:
        try:
            from app.core.database import Database

            db = Database(self._settings)
            db.init()
            db.set_setting(key, value)
        except Exception:
            logger.warning("backup_setting_write_failed", extra={"context": {"key": key}})

    def _truthy_setting(self, key: str) -> bool:
        return self._setting(key).strip().lower() in {"1", "true", "yes", "on"}

    def _backup_size_cap_bytes(self) -> int:
        try:
            configured = int(
                self._setting(
                    "backup.size_cap_bytes",
                    self._setting("backup.remote_size_cap_bytes", str(DEFAULT_BACKUP_SIZE_CAP_BYTES)),
                )
            )
            return max(0, configured)
        except ValueError:
            return DEFAULT_BACKUP_SIZE_CAP_BYTES

    @staticmethod
    def _positive_int(value: Any, default: int, *, minimum: int = 1, maximum: int | None = None) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        parsed = max(minimum, parsed)
        if maximum is not None:
            parsed = min(maximum, parsed)
        return parsed

    def _backup_encryption_key(self) -> str:
        return self._setting("backup.encryption_key") or os.getenv("BACKUP_ENCRYPTION_KEY", "")

    def _package_checksum(self, package: Path) -> str:
        try:
            return _sha256(package.read_bytes()) if package.exists() else ""
        except Exception:
            return ""

    def _rclone_config_path(self) -> Path:
        configured = os.getenv("RCLONE_CONFIG", "").strip()
        if configured:
            return Path(configured).expanduser()
        return Path.home() / ".config" / "rclone" / "rclone.conf"

    def _rclone_command(self, *args: str) -> list[str]:
        cmd = ["rclone"]
        config_path = self._rclone_config_path()
        if config_path.exists():
            cmd.extend(["--config", str(config_path)])
        cmd.extend(args)
        return cmd

    def _write_rclone_remote_section(self, config_path: Path, remote: str, body: str) -> None:
        header = f"[{remote}]"
        existing = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
        lines = existing.splitlines()
        next_lines: list[str] = []
        index = 0
        replaced = False
        while index < len(lines):
            line = lines[index]
            if line.strip() == header:
                replaced = True
                next_lines.append(header)
                next_lines.extend(body.rstrip("\n").splitlines())
                index += 1
                while index < len(lines) and not lines[index].lstrip().startswith("["):
                    index += 1
                continue
            next_lines.append(line)
            index += 1
        if not replaced:
            if next_lines and next_lines[-1].strip():
                next_lines.append("")
            next_lines.append(header)
            next_lines.extend(body.rstrip("\n").splitlines())
        config_path.write_text("\n".join(next_lines).rstrip() + "\n", encoding="utf-8")

    def _postgres_env(self) -> tuple[dict[str, str], str]:
        if self._settings.storage.db_type != "postgresql":
            raise RuntimeError("PostgreSQL backup requires DB_TYPE=postgresql")

        host = os.getenv("POSTGRES_HOST", "").strip()
        port = os.getenv("POSTGRES_PORT", "").strip()
        database = os.getenv("POSTGRES_DB", "").strip()
        username = os.getenv("POSTGRES_USER", "").strip()
        password = os.getenv("POSTGRES_PASSWORD", "")

        if not (host and port and database and username):
            parsed = urlparse((self._settings.storage.database_url or "").replace("postgresql+psycopg2://", "postgresql://"))
            host = host or (parsed.hostname or "")
            port = port or str(parsed.port or 5432)
            database = database or unquote((parsed.path or "").lstrip("/"))
            username = username or unquote(parsed.username or "")
            password = password or unquote(parsed.password or "")

        if not (host and port and database and username):
            raise RuntimeError("PostgreSQL connection is not configured")

        env = os.environ.copy()
        env.update({
            "PGHOST": host,
            "PGPORT": port,
            "PGDATABASE": database,
            "PGUSER": username,
        })
        if password:
            env["PGPASSWORD"] = password
        return env, database

    def _postgres_backup_dir(self) -> Path:
        directory = self._backup_dir / "postgres"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _gdrive_client_id(self) -> str:
        return os.getenv("GOOGLE_DRIVE_CLIENT_ID", "").strip() or self._setting("backup.gdrive.client_id").strip()

    def _gdrive_client_secret(self) -> str:
        return os.getenv("GOOGLE_DRIVE_CLIENT_SECRET", "").strip() or self._setting("backup.gdrive.client_secret").strip()

    def get_remote_backup_config(self) -> dict:
        config_path = self._rclone_config_path()
        config_text = ""
        config_error = ""
        if config_path.exists():
            try:
                config_text = config_path.read_text(encoding="utf-8")
            except Exception as exc:
                config_error = str(exc)

        remotes: list[str] = []
        remotes_error = ""
        if shutil.which("rclone"):
            try:
                result = subprocess.run(
                    self._rclone_command("listremotes"),
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if result.returncode == 0:
                    remotes = [line.rstrip(":") for line in result.stdout.splitlines() if line.strip()]
                elif result.stderr:
                    remotes_error = result.stderr[:500]
            except Exception as exc:
                remotes_error = str(exc)
        else:
            remotes_error = "rclone binary not found"

        return {
            "rclone_remote": self._setting("backup.rclone_remote", ""),
            "rclone_path": self._setting("backup.rclone_path", "eazyfill-backups"),
            "backup_size_cap_mb": int(self._backup_size_cap_bytes() / (1024 * 1024)),
            "backup_remote_size_cap_mb": int(self._backup_size_cap_bytes() / (1024 * 1024)),
            "cloudflare_r2_remote": self._setting("backup.cloudflare_r2.remote", "cloudflare-r2"),
            "cloudflare_r2_account_id": self._setting("backup.cloudflare_r2.account_id", ""),
            "cloudflare_r2_bucket": self._setting("backup.cloudflare_r2.bucket", ""),
            "cloudflare_r2_prefix": self._setting("backup.cloudflare_r2.prefix", "eazyfill-backups"),
            "cloudflare_r2_access_key_set": bool(self._setting("backup.cloudflare_r2.access_key_id", "")),
            "cloudflare_r2_secret_key_set": bool(self._setting("backup.cloudflare_r2.secret_access_key", "")),
            "cloudflare_r2_last_error": self._setting("backup.cloudflare_r2.last_error", ""),
            "telegram_chat_id": self._setting("backup.telegram.chat_id", ""),
            "telegram_bot_token_set": bool(self._setting("backup.telegram.bot_token", "") or os.getenv("BACKUP_TELEGRAM_BOT_TOKEN", "")),
            "telegram_last_error": self._setting("backup.telegram.last_error", ""),
            "telegram_latest": {
                category: {
                    "file_name": self._setting(f"backup.telegram.latest.{category}.file_name", ""),
                    "file_id_set": bool(self._setting(f"backup.telegram.latest.{category}.file_id", "")),
                }
                for category in ADMIN_BACKUP_CATEGORIES
            },
            "rclone_binary": shutil.which("rclone") or "",
            "rclone_config_path": str(config_path),
            "rclone_config_exists": config_path.exists(),
            "rclone_config": config_text,
            "rclone_config_error": config_error,
            "rclone_remotes": remotes,
            "rclone_remotes_error": remotes_error,
            "rclone_last_error": self._setting("backup.rclone_last_error", ""),
        }

    def save_remote_backup_config(self, data: dict[str, Any]) -> dict:
        if "rclone_remote" in data:
            self._set_setting("backup.rclone_remote", str(data.get("rclone_remote") or "").strip().rstrip(":"))
        if "rclone_path" in data:
            self._set_setting("backup.rclone_path", str(data.get("rclone_path") or "").strip().strip("/"))
        if "telegram_chat_id" in data:
            self._set_setting("backup.telegram.chat_id", str(data.get("telegram_chat_id") or "").strip())
        if str(data.get("telegram_bot_token") or "").strip():
            self._set_setting("backup.telegram.bot_token", str(data.get("telegram_bot_token") or "").strip())
        cap_value = data.get("backup_size_cap_mb", data.get("backup_remote_size_cap_mb"))
        if cap_value is not None:
            cap_mb = self._positive_int(cap_value, int(DEFAULT_BACKUP_SIZE_CAP_BYTES / (1024 * 1024)), minimum=0)
            self._set_setting("backup.size_cap_bytes", str(cap_mb * 1024 * 1024))
            self._set_setting("backup.remote_size_cap_bytes", str(cap_mb * 1024 * 1024))
        if "rclone_config" in data:
            config_path = self._rclone_config_path()
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(str(data.get("rclone_config") or ""), encoding="utf-8")
            try:
                config_path.chmod(0o600)
            except Exception:
                pass
        cloudflare_payload_present = any(str(key).startswith("cloudflare_r2_") for key in data)
        cloudflare_configured_or_submitted = any(
            str(data.get(key) or self._setting(f"backup.{key.replace('cloudflare_r2_', 'cloudflare_r2.')}") or "").strip()
            for key in (
                "cloudflare_r2_account_id",
                "cloudflare_r2_bucket",
                "cloudflare_r2_access_key_id",
                "cloudflare_r2_secret_access_key",
            )
        )
        if cloudflare_payload_present and cloudflare_configured_or_submitted:
            self.configure_cloudflare_r2_remote(data)
        return self.get_remote_backup_config()

    def configure_cloudflare_r2_remote(self, data: dict[str, Any]) -> dict:
        remote = str(data.get("cloudflare_r2_remote") or self._setting("backup.cloudflare_r2.remote", "cloudflare-r2")).strip().rstrip(":")
        account_id = str(data.get("cloudflare_r2_account_id") or self._setting("backup.cloudflare_r2.account_id", "")).strip()
        bucket = str(data.get("cloudflare_r2_bucket") or self._setting("backup.cloudflare_r2.bucket", "")).strip().strip("/")
        prefix = str(data.get("cloudflare_r2_prefix") or self._setting("backup.cloudflare_r2.prefix", "eazyfill-backups")).strip().strip("/")
        access_key_id = str(data.get("cloudflare_r2_access_key_id") or self._setting("backup.cloudflare_r2.access_key_id", "")).strip()
        secret_access_key = str(data.get("cloudflare_r2_secret_access_key") or self._setting("backup.cloudflare_r2.secret_access_key", "")).strip()
        if not remote:
            raise ValueError("Cloudflare R2 remote name is required")
        if not account_id:
            raise ValueError("Cloudflare R2 account ID is required")
        if not bucket:
            raise ValueError("Cloudflare R2 bucket is required")
        if not access_key_id:
            raise ValueError("Cloudflare R2 access key ID is required")
        if not secret_access_key:
            raise ValueError("Cloudflare R2 secret access key is required")

        self._set_setting("backup.cloudflare_r2.remote", remote)
        self._set_setting("backup.cloudflare_r2.account_id", account_id)
        self._set_setting("backup.cloudflare_r2.bucket", bucket)
        self._set_setting("backup.cloudflare_r2.prefix", prefix)
        self._set_setting("backup.cloudflare_r2.access_key_id", access_key_id)
        self._set_setting("backup.cloudflare_r2.secret_access_key", secret_access_key)

        config_path = self._rclone_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_rclone_remote_section(
            config_path,
            remote,
            "\n".join([
                "type = s3",
                "provider = Cloudflare",
                f"access_key_id = {access_key_id}",
                f"secret_access_key = {secret_access_key}",
                f"endpoint = https://{account_id}.r2.cloudflarestorage.com",
                "acl = private",
                "",
            ]),
        )
        try:
            config_path.chmod(0o600)
        except Exception:
            pass
        return self.get_remote_backup_config()

    def test_rclone_remote(self, remote: str | None = None, remote_path: str | None = None) -> dict:
        target_remote = (remote or self._setting("backup.rclone_remote", "")).strip().rstrip(":")
        target_path = (remote_path if remote_path is not None else self._setting("backup.rclone_path", "eazyfill-backups")).strip().strip("/")
        if not target_remote:
            return {"ok": False, "error": "backup.rclone_remote is not configured"}
        if not shutil.which("rclone"):
            return {"ok": False, "remote": target_remote, "error": "rclone binary not found"}

        root_target = f"{target_remote}:"
        configured_target = f"{target_remote}:{target_path}" if target_path else root_target
        try:
            result = subprocess.run(
                self._rclone_command("lsd", root_target),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                error = (result.stderr or result.stdout or "rclone remote test failed")[:1000]
                self._set_setting("backup.rclone_last_error", error)
                return {"ok": False, "remote": configured_target, "error": error}
            self._set_setting("backup.rclone_last_error", "")
            lines = [line for line in result.stdout.splitlines() if line.strip()]
            return {"ok": True, "remote": configured_target, "entries": lines[:20], "entry_count": len(lines)}
        except subprocess.TimeoutExpired:
            error = "rclone remote test timed out (30s)"
            self._set_setting("backup.rclone_last_error", error)
            return {"ok": False, "remote": configured_target, "error": error}
        except Exception as exc:
            error = str(exc)
            self._set_setting("backup.rclone_last_error", error)
            return {"ok": False, "remote": configured_target, "error": error}

    def _gdrive_token_data(self) -> dict:
        raw = self._setting("backup.gdrive.token_json")
        if not raw:
            return {}
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_gdrive_token_data(self, data: dict) -> None:
        self._set_setting("backup.gdrive.token_json", json.dumps(data))

    def _gdrive_access_token(self) -> str:
        data = self._gdrive_token_data()
        if not data:
            return ""
        expires_at = int(data.get("expires_at") or 0)
        if data.get("access_token") and (not expires_at or expires_at > int(time.time()) + 60):
            return data.get("access_token", "")
        refreshed = self._refresh_gdrive_token(data)
        return refreshed.get("access_token", "")

    def _refresh_gdrive_token(self, token_data: dict) -> dict:
        refresh_token = token_data.get("refresh_token")
        client_id = self._gdrive_client_id()
        client_secret = self._gdrive_client_secret()
        if not refresh_token or not client_id or not client_secret:
            return token_data
        try:
            resp = httpx.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=30,
            )
            if resp.status_code >= 400:
                self._set_setting("backup.gdrive.last_error", resp.text)
                return token_data
            updated = token_data | resp.json()
            updated["refresh_token"] = refresh_token
            if updated.get("expires_in"):
                updated["expires_at"] = int(time.time()) + int(updated["expires_in"])
            self._save_gdrive_token_data(updated)
            self._set_setting("backup.gdrive.last_error", "")
            return updated
        except Exception as exc:
            self._set_setting("backup.gdrive.last_error", str(exc))
            return token_data

    def create_system_backup(self) -> dict:
        """
        Create a compressed tarball of system files + DB table exports.

        Saves to: {backup_dir}/system/system_{timestamp}.tar.gz
        Returns: {"path": str, "size": int, "tables": list, "files": list}
        """
        project_root = self._root
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        sys_dir = self._backup_dir / "system"
        sys_dir.mkdir(parents=True, exist_ok=True)

        tarball_path = sys_dir / f"system_{timestamp}.tar.gz"
        included_files = []
        included_tables = []
        system_data = self._export_system_data()

        with tarfile.open(str(tarball_path), "w:gz") as tar:
            data = json.dumps(system_data, indent=2, default=str).encode("utf-8")
            info = tarfile.TarInfo(name="system-data.json")
            info.size = len(data)
            tar.addfile(info, BytesIO(data))

            # Add file-based assets
            for rel_path in self.SYSTEM_FILE_PATHS:
                full_path = (project_root / rel_path).resolve()
                if full_path.is_file():
                    tar.add(str(full_path), arcname=rel_path)
                    included_files.append(rel_path)
                elif full_path.is_dir():
                    for child in full_path.rglob("*"):
                        if child.is_file():
                            arc = str(child.relative_to(project_root))
                            tar.add(str(child), arcname=arc)
                            included_files.append(arc)

            # Add DB table exports as JSON
            for table_name in self.SYSTEM_DB_TABLES:
                try:
                    rows = self._export_table_rows(table_name)
                    data = json.dumps(rows, indent=2, default=str).encode("utf-8")
                    info = tarfile.TarInfo(name=f"db_tables/{table_name}.json")
                    info.size = len(data)
                    tar.addfile(info, BytesIO(data))
                    included_tables.append(table_name)
                except Exception as e:
                    logger.warning(f"system_backup_table_skip: {table_name}: {e}")

        # Update latest symlink (copy)
        latest = sys_dir / "latest_system.tar.gz"
        try:
            if latest.exists():
                latest.unlink()
            import shutil
            shutil.copy2(str(tarball_path), str(latest))
        except Exception:
            pass

        self._prune_local_backups_by_size()

        logger.info("system_backup_created", extra={"context": {
            "path": str(tarball_path),
            "files": len(included_files),
            "tables": len(included_tables),
        }})

        return {
            "path": str(tarball_path),
            "size": tarball_path.stat().st_size,
            "files": included_files,
            "tables": included_tables,
        }

    def create_user_backup(self) -> dict:
        """
        Export user-related DB tables to compressed JSON.

        Saves to: {backup_dir}/users/users_{timestamp}.json.gz
        Returns: {"path": str, "size": int, "tables": dict}
        """
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        user_dir = self._backup_dir / "users"
        user_dir.mkdir(parents=True, exist_ok=True)

        export = {
            "_backup_meta": {
                "type": "user_backup",
                "timestamp": datetime.now(UTC).isoformat(),
                "version": 1,
            }
        }

        self._ensure_user_tables()

        # Export raw rows so restore gets every persisted column, including key hashes.
        for table_name in self.USER_DB_TABLES:
            try:
                if self._table_exists(table_name):
                    export[table_name] = self._export_table_rows(table_name)
            except Exception as e:
                logger.warning(f"user_backup_table_skip: {table_name}: {e}")

        # Write compressed
        out_path = user_dir / f"users_{timestamp}.json.gz"
        with gzip.open(str(out_path), "wt", encoding="utf-8") as f:
            json.dump(export, f, indent=2, default=str)

        # Latest copy
        latest = user_dir / "latest_users.json.gz"
        try:
            if latest.exists():
                latest.unlink()
            import shutil
            shutil.copy2(str(out_path), str(latest))
        except Exception:
            pass

        self._prune_local_backups_by_size()

        table_summary = {k: len(v) for k, v in export.items() if isinstance(v, list)}
        logger.info("user_backup_created", extra={"context": {
            "path": str(out_path),
            "tables": table_summary,
        }})

        return {
            "path": str(out_path),
            "size": out_path.stat().st_size,
            "tables": table_summary,
        }

    def create_postgres_backup(self) -> dict:
        """Create a PostgreSQL-native custom-format dump with pg_dump -Fc."""
        if not shutil.which("pg_dump"):
            return {"success": False, "error": "pg_dump binary not found"}
        if not shutil.which("pg_restore"):
            return {"success": False, "error": "pg_restore binary not found"}

        env, database = self._postgres_env()
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        pg_dir = self._postgres_backup_dir()
        dump_path = pg_dir / f"postgres_{timestamp}.dump"
        cmd = [
            "pg_dump",
            "-Fc",
            "--no-owner",
            "--no-privileges",
            "--file",
            str(dump_path),
        ]
        started = datetime.now(UTC)
        result = {
            "backup_id": dump_path.stem,
            "type": "postgres",
            "started_at": started.isoformat(),
            "status": "running",
        }
        try:
            completed = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=900)
            if completed.returncode != 0:
                error = (completed.stderr or completed.stdout or "pg_dump failed")[:1000]
                dump_path.unlink(missing_ok=True)
                result.update({"status": "failed", "finished_at": datetime.now(UTC).isoformat(), "error": error})
                self._log_backup_run(result)
                return {"success": False, "error": error}

            verified = self.inspect_postgres_backup(dump_path.name)
            if not verified.get("success"):
                error = verified.get("error", "pg_restore verification failed")
                dump_path.unlink(missing_ok=True)
                result.update({"status": "failed", "finished_at": datetime.now(UTC).isoformat(), "error": error})
                self._log_backup_run(result)
                return {"success": False, "error": error}

            latest = pg_dir / "latest_postgres.dump"
            latest.unlink(missing_ok=True)
            shutil.copy2(str(dump_path), str(latest))
            checksum = self._package_checksum(dump_path)
            result.update({
                "status": "completed",
                "finished_at": datetime.now(UTC).isoformat(),
                "file_path_or_uri": str(dump_path),
                "checksum": checksum,
                "size_bytes": dump_path.stat().st_size,
            })
            self._prune_local_backups_by_size()
            self._log_backup_run(result)
            return {
                "success": True,
                "type": "postgres",
                "database": database,
                "path": str(dump_path),
                "size": dump_path.stat().st_size,
                "checksum": checksum,
                "objects": verified.get("objects", 0),
            }
        except subprocess.TimeoutExpired:
            dump_path.unlink(missing_ok=True)
            error = "pg_dump timed out (900s)"
            result.update({"status": "failed", "finished_at": datetime.now(UTC).isoformat(), "error": error})
            self._log_backup_run(result)
            return {"success": False, "error": error}
        except Exception as exc:
            dump_path.unlink(missing_ok=True)
            error = str(exc)
            result.update({"status": "failed", "finished_at": datetime.now(UTC).isoformat(), "error": error})
            self._log_backup_run(result)
            return {"success": False, "error": error}

    def inspect_postgres_backup(self, backup_path: str | Path) -> dict:
        """Inspect a PostgreSQL custom-format dump using pg_restore --list."""
        if not shutil.which("pg_restore"):
            return {"success": False, "error": "pg_restore binary not found"}
        backup_path = self._resolve_split_backup_path("postgres", backup_path)
        try:
            result = subprocess.run(
                ["pg_restore", "--list", str(backup_path)],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                return {"success": False, "error": (result.stderr or result.stdout or "pg_restore --list failed")[:1000]}
            entries = [
                line for line in result.stdout.splitlines()
                if line.strip() and not line.lstrip().startswith(";")
            ]
            return {
                "success": True,
                "type": "postgres",
                "path": str(backup_path),
                "size": backup_path.stat().st_size,
                "checksum": self._package_checksum(backup_path),
                "objects": len(entries),
                "sample": entries[:20],
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "pg_restore --list timed out (120s)"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def restore_postgres_backup(self, backup_path: str | Path, *, confirm: str = "") -> dict:
        """Restore a PostgreSQL custom-format dump into the configured database."""
        if confirm != "RESTORE POSTGRES":
            return {"success": False, "error": "confirmation phrase required"}
        if not shutil.which("pg_restore"):
            return {"success": False, "error": "pg_restore binary not found"}
        env, database = self._postgres_env()
        backup_path = self._resolve_split_backup_path("postgres", backup_path)
        verified = self.inspect_postgres_backup(backup_path)
        if not verified.get("success"):
            return verified
        cmd = [
            "pg_restore",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
            "--exit-on-error",
            "--dbname",
            database,
            str(backup_path),
        ]
        try:
            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=900)
            if result.returncode != 0:
                return {"success": False, "error": (result.stderr or result.stdout or "pg_restore failed")[:1000]}
            return {
                "success": True,
                "type": "postgres",
                "database": database,
                "path": str(backup_path),
                "objects": verified.get("objects", 0),
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "pg_restore timed out (900s)"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def restore_system_backup(self, backup_path: str | Path) -> dict:
        """Restore a system split backup tarball created by create_system_backup()."""
        backup_path = self._resolve_split_backup_path("system", backup_path)
        restored_files: list[str] = []
        restored_tables: dict[str, int] = {}
        system_data: dict[str, Any] | None = None
        table_payload: dict[str, list[dict[str, Any]]] = {}

        with tarfile.open(str(backup_path), "r:gz") as tar:
            members = tar.getmembers()
            for member in members:
                if member.isdir():
                    continue
                if member.name == "system-data.json":
                    extracted = tar.extractfile(member)
                    if extracted:
                        system_data = json.loads(extracted.read().decode("utf-8"))
                    continue
                if member.name.startswith("db_tables/") and member.name.endswith(".json"):
                    table_name = Path(member.name).stem
                    if table_name not in self.SYSTEM_DB_TABLES:
                        continue
                    extracted = tar.extractfile(member)
                    if not extracted:
                        continue
                    rows = json.loads(extracted.read().decode("utf-8"))
                    if isinstance(rows, list):
                        table_payload[table_name] = rows
                    continue
                self._restore_tar_member(tar, member)
                restored_files.append(member.name)

        if system_data:
            self._restore_system_data(system_data)
            restored_tables["system-data"] = 1
        if table_payload:
            # When raw table exports exist in the split backup, treat them as
            # the restore source of truth for DB row fidelity.
            restored_tables.update(self._restore_table_group(self.SYSTEM_DB_TABLES, table_payload))

        key_counts = {
            "model_routes": int(restored_tables.get("model_routes", 0)),
            "model_registry": int(restored_tables.get("model_registry", 0)),
            "field_mappings": int(restored_tables.get("field_mappings", 0)),
            "field_mapping_proposals": int(restored_tables.get("field_mapping_proposals", 0)),
            "retrain_samples": int(restored_tables.get("retrain_samples", 0)),
            "retrain_jobs": int(restored_tables.get("retrain_jobs", 0)),
        }

        return {
            "success": True,
            "type": "system",
            "path": str(backup_path),
            "files": restored_files,
            "tables": restored_tables,
            "restore_strategy": "table_rows_authoritative" if table_payload else "system_data_only",
            "key_counts": key_counts,
        }

    def restore_user_backup(self, backup_path: str | Path) -> dict:
        """Restore lossless legacy user tables from create_user_backup()."""
        backup_path = self._resolve_split_backup_path("users", backup_path)
        with gzip.open(str(backup_path), "rt", encoding="utf-8") as f:
            payload = json.load(f)

        self._ensure_user_tables()

        skipped_tables: list[str] = []
        compatibility_warnings: list[str] = []
        restorable_payload: dict[str, list[dict[str, Any]]] = {}
        for table_name, rows in payload.items():
            if table_name.startswith("_"):
                continue
            if table_name not in self.USER_DB_TABLES:
                skipped_tables.append(table_name)
                continue
            if not isinstance(rows, list):
                compatibility_warnings.append(f"{table_name}: skipped non-list payload")
                continue
            restorable_payload[table_name] = self._prepare_user_restore_rows(
                table_name,
                rows,
                compatibility_warnings,
            )
        self._add_missing_legacy_api_key_parents(restorable_payload, compatibility_warnings)
        restored_tables = self._restore_table_group(self.USER_DB_TABLES, restorable_payload)

        return {
            "success": True,
            "type": "users",
            "path": str(backup_path),
            "tables": restored_tables,
            "skipped_tables": skipped_tables,
            "warnings": compatibility_warnings,
            "key_counts": {
                "users": int(restored_tables.get("users", 0)),
                "subscription_plans": int(restored_tables.get("subscription_plans", 0)),
                "user_subscriptions": int(restored_tables.get("user_subscriptions", 0)),
                "payment_records": int(restored_tables.get("payment_records", 0)),
                "payment_webhook_events": int(restored_tables.get("payment_webhook_events", 0)),
                "user_api_keys": int(restored_tables.get("user_api_keys", 0)),
                "encrypted_backups": int(restored_tables.get("encrypted_backups", 0)),
                "api_keys": int(restored_tables.get("api_keys", 0)),
                "api_key_allowed_domains": int(restored_tables.get("api_key_allowed_domains", 0)),
                "api_key_rate_limits": int(restored_tables.get("api_key_rate_limits", 0)),
                "api_key_device_bindings": int(restored_tables.get("api_key_device_bindings", 0)),
                "usage_events": int(restored_tables.get("usage_events", 0)),
                "audit_logs": int(restored_tables.get("audit_logs", 0)),
            },
        }

    def inspect_system_backup(self, backup_path: str | Path) -> dict:
        """Inspect system split backup contents without restoring anything."""
        backup_path = self._resolve_split_backup_path("system", backup_path)
        table_counts: dict[str, int] = {}
        system_counts = {
            "model_routes": 0,
            "field_mappings": 0,
            "model_registry": 0,
        }
        asset_counts = {
            "model_files": 0,
            "userscript_files": 0,
        }

        with tarfile.open(str(backup_path), "r:gz") as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                name = member.name
                if name.startswith("data/models/") and name.endswith(".onnx"):
                    asset_counts["model_files"] += 1
                elif name.startswith("data/userscripts/"):
                    asset_counts["userscript_files"] += 1

                if name == "system-data.json":
                    extracted = tar.extractfile(member)
                    if extracted:
                        payload = json.loads(extracted.read().decode("utf-8"))
                        system_counts["model_routes"] = self._item_count(payload.get("model_routes"))
                        system_counts["model_registry"] = self._item_count(payload.get("model_registry"))
                        system_counts["field_mappings"] = self._item_count(payload.get("field_mappings"))
                    continue

                if name.startswith("db_tables/") and name.endswith(".json"):
                    table_name = Path(name).stem
                    extracted = tar.extractfile(member)
                    if not extracted:
                        continue
                    rows = json.loads(extracted.read().decode("utf-8"))
                    table_counts[table_name] = self._item_count(rows)

        return {
            "success": True,
            "type": "system",
            "path": str(backup_path),
            "system_data_counts": system_counts,
            "table_counts": table_counts,
            "asset_counts": asset_counts,
        }

    def inspect_user_backup(self, backup_path: str | Path) -> dict:
        """Inspect user split backup contents without restoring anything."""
        backup_path = self._resolve_split_backup_path("users", backup_path)
        with gzip.open(str(backup_path), "rt", encoding="utf-8") as f:
            payload = json.load(f)

        table_counts: dict[str, int] = {}
        for table_name in self.USER_DB_TABLES:
            rows = payload.get(table_name, [])
            table_counts[table_name] = self._item_count(rows)
        payload_tables = {
            table_name: self._item_count(rows)
            for table_name, rows in payload.items()
            if not table_name.startswith("_") and isinstance(rows, list)
        }

        return {
            "success": True,
            "type": "users",
            "path": str(backup_path),
            "table_counts": table_counts,
            "payload_tables": payload_tables,
            "unknown_tables": [
                table_name for table_name in payload_tables
                if table_name not in self.USER_DB_TABLES
            ],
        }

    def inspect_full_backup(self, backup_path: str | Path) -> dict:
        """Inspect a full portable snapshot package without restoring it."""
        backup_path = self._resolve_full_backup_path(backup_path)
        validation = self.validate_package(backup_path)
        if not validation.get("ok"):
            return {"success": False, "error": validation.get("error", "full snapshot validation failed")}
        manifest = validation.get("manifest") or {}
        return {
            "success": True,
            "type": "full",
            "path": str(backup_path),
            "size": backup_path.stat().st_size,
            "checksum": self._package_checksum(backup_path),
            "encrypted": backup_path.suffix == ".upbak",
            "manifest": manifest,
            "sections": manifest.get("sections", []),
            "file_count": int(manifest.get("file_count") or 0),
        }

    def restore_full_backup(self, backup_path: str | Path, *, confirm: str = "") -> dict:
        """Restore a full portable snapshot package."""
        if confirm != "RESTORE FULL SNAPSHOT":
            return {"success": False, "error": "confirmation phrase required"}
        backup_path = self._resolve_full_backup_path(backup_path)
        restored = self.restore_package(backup_path)
        return {
            "success": restored.get("status") == "completed",
            "type": "full",
            "path": str(backup_path),
            "restored": restored,
            "error": restored.get("error", ""),
        }

    def list_all_backups(self) -> dict:
        """List all backup files for admin dashboard."""
        result = {"full": [], "system": [], "users": [], "postgres": []}
        result["full"] = [
            {
                "name": item["name"],
                "size": item["size_bytes"],
                "created": item["created"],
                "encrypted": item["encrypted"],
            }
            for item in self.list_backups()
        ]
        for category in ("system", "users", "postgres"):
            cat_dir = self._backup_dir / category
            if not cat_dir.exists():
                continue
            for f in sorted(cat_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                if f.is_file() and not f.name.startswith("latest"):
                    result[category].append({
                        "name": f.name,
                        "size": f.stat().st_size,
                        "created": datetime.fromtimestamp(
                            f.stat().st_mtime, tz=UTC
                        ).isoformat(),
                    })
        return result

    def rclone_sync(self, backup_path: str | Path) -> dict:
        """
        Upload a backup file to configured rclone remote.

        Configuration (from platform_settings):
        - backup.rclone_remote: remote name (e.g., "gdrive")
        - backup.rclone_path: remote folder (e.g., "eazyfill-backups")

        Returns: {"success": bool, "remote": str, "error": str}
        """
        backup_path = Path(backup_path)
        remote = self._setting("backup.rclone_remote", "")
        if not remote:
            return {"success": False, "remote": "", "error": "No rclone remote configured"}

        remote_path = self._setting("backup.rclone_path", "eazyfill-backups")

        try:
            cmd = self._rclone_command(
                "copy",
                str(backup_path),
                f"{remote}:{remote_path}/",
                "--log-level",
                "ERROR",
            )
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300,
            )
            if result.returncode != 0:
                error_msg = result.stderr[:500] if result.stderr else "Unknown error"
                self._set_setting("backup.rclone_last_error", error_msg)
                logger.error("rclone_failed", extra={"context": {"stderr": error_msg}})
                return {"success": False, "remote": remote, "error": error_msg}

            self._set_setting("backup.rclone_last_error", "")
            logger.info("rclone_synced", extra={"context": {
                "file": backup_path.name, "remote": remote,
            }})
            return {"success": True, "remote": f"{remote}:{remote_path}", "error": ""}
        except FileNotFoundError:
            msg = "rclone binary not found - install rclone in container"
            self._set_setting("backup.rclone_last_error", msg)
            logger.error(msg)
            return {"success": False, "remote": remote, "error": msg}
        except subprocess.TimeoutExpired:
            msg = "rclone upload timed out (300s)"
            self._set_setting("backup.rclone_last_error", msg)
            logger.error(msg)
            return {"success": False, "remote": remote, "error": msg}
        except Exception as e:
            error = str(e)
            self._set_setting("backup.rclone_last_error", error)
            return {"success": False, "remote": remote, "error": error}

    def rclone_sync_latest_category(self, category: str, *, target: str = "rclone") -> dict:
        """Upload the newest backup plus latest alias, then prune remote history."""
        category = str(category or "").strip().lower()
        if category not in SPLIT_BACKUP_CATEGORIES:
            return {"success": False, "error": "category must be full, system, users, or postgres"}
        newest = self._newest_backup_for_category(category)
        if not newest.exists():
            return {"success": False, "category": category, "error": f"no local {category} backup found"}

        latest_name = self._latest_backup_filename(category, newest)
        timestamped = self.rclone_sync_to_name(newest, newest.name, target=target)
        if not timestamped.get("success"):
            return {**timestamped, "category": category}
        latest = self.rclone_sync_to_name(newest, latest_name, target=target)
        if not latest.get("success"):
            return {**latest, "category": category}
        retention = self.apply_rclone_retention(category, target=target)
        return {
            "success": True,
            "category": category,
            "target": target,
            "uploaded": [timestamped, latest],
            "retention": retention,
            "remote": timestamped.get("remote_base", timestamped.get("remote", "")),
        }

    def rclone_sync_to_name(self, backup_path: str | Path, remote_filename: str, *, target: str = "rclone") -> dict:
        backup_path = Path(backup_path)
        target_config = self._rclone_target_config(target)
        remote = target_config["remote"]
        if not remote:
            return {"success": False, "remote": "", "target": target_config["target"], "error": target_config["missing_error"]}
        if not backup_path.exists():
            return {"success": False, "remote": remote, "target": target_config["target"], "error": f"backup file not found: {backup_path}"}
        if not shutil.which("rclone"):
            msg = "rclone binary not found - install rclone in container"
            self._set_rclone_target_error(target_config, msg)
            return {"success": False, "remote": remote, "target": target_config["target"], "error": msg}

        remote_path = target_config["path"]
        target = self._rclone_child_target(f"{remote}:{remote_path}" if remote_path else f"{remote}:", remote_filename)
        try:
            result = subprocess.run(
                self._rclone_command("copyto", str(backup_path), target, "--log-level", "ERROR"),
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode != 0:
                error_msg = (result.stderr or result.stdout or "rclone upload failed")[:1000]
                self._set_rclone_target_error(target_config, error_msg)
                return {"success": False, "remote": target, "target": target_config["target"], "error": error_msg}
            self._set_rclone_target_error(target_config, "")
            return {
                "success": True,
                "remote": target,
                "remote_base": f"{remote}:{remote_path}" if remote_path else f"{remote}:",
                "target": target_config["target"],
                "filename": remote_filename,
                "size": backup_path.stat().st_size,
            }
        except subprocess.TimeoutExpired:
            msg = "rclone upload timed out (300s)"
            self._set_rclone_target_error(target_config, msg)
            return {"success": False, "remote": target, "target": target_config["target"], "error": msg}
        except Exception as exc:
            error = str(exc)
            self._set_rclone_target_error(target_config, error)
            return {"success": False, "remote": target, "target": target_config["target"], "error": error}

    def apply_rclone_retention(self, category: str, *, target: str = "rclone") -> dict:
        category = str(category or "").strip().lower()
        if category not in SPLIT_BACKUP_CATEGORIES:
            return {"success": False, "error": "category must be full, system, users, or postgres"}
        target_config = self._rclone_target_config(target)
        remote = target_config["remote"]
        if not remote:
            return {"success": False, "remote": "", "target": target_config["target"], "error": target_config["missing_error"]}
        if not shutil.which("rclone"):
            msg = "rclone binary not found - install rclone in container"
            self._set_rclone_target_error(target_config, msg)
            return {"success": False, "remote": remote, "target": target_config["target"], "error": msg}

        remote_path = target_config["path"]
        target_dir = f"{remote}:{remote_path}" if remote_path else f"{remote}:"
        cap_bytes = self._backup_size_cap_bytes()
        threshold = int(cap_bytes * REMOTE_BACKUP_SIZE_PRUNE_RATIO) if cap_bytes else 0

        files = self._rclone_list_files(target_dir, error_key=target_config["last_error_key"])
        if files is None:
            return {"success": False, "remote": target_dir, "target": target_config["target"], "error": self._setting(target_config["last_error_key"], "rclone list failed")}

        managed = [
            item for item in files
            if str(item.get("Path", "")).startswith(("backup_", "postgres_", "system_", "users_"))
        ]
        managed.sort(key=lambda item: str(item.get("ModTime") or ""), reverse=True)
        newest_by_prefix: dict[str, str] = {}
        for item in managed:
            path = str(item.get("Path", ""))
            prefix = self._managed_backup_prefix_for_path(path)
            newest_by_prefix.setdefault(prefix, path)
        counted_files = [
            item for item in files
            if str(item.get("Path", "")).startswith(("backup_", "postgres_", "system_", "users_", "latest_"))
        ]
        total_size = sum(int(item.get("Size") or 0) for item in counted_files)
        deleted: list[str] = []

        # Delete oldest timestamped copies only when the managed backup set is
        # near the configured cap. Keep latest_* restore pointers and the newest
        # timestamped copy for each backup family.
        size_prune_candidates = list(reversed(managed))
        while threshold and total_size > threshold and size_prune_candidates:
            item = size_prune_candidates.pop(0)
            item_path = str(item.get("Path", ""))
            item_prefix = self._managed_backup_prefix_for_path(item_path)
            if newest_by_prefix.get(item_prefix) == item_path:
                continue
            if self._rclone_delete_file(target_dir, item_path, error_key=target_config["last_error_key"]):
                deleted.append(str(item.get("Path", "")))
                total_size -= int(item.get("Size") or 0)

        return {
            "success": True,
            "remote": target_dir,
            "category": category,
            "target": target_config["target"],
            "retention_strategy": "size_cap",
            "size_cap_bytes": cap_bytes,
            "size_prune_threshold_bytes": threshold,
            "deleted": deleted,
            "remaining_size_bytes_estimate": max(0, total_size),
        }

    def _rclone_list_files(self, target_dir: str, *, error_key: str = "backup.rclone_last_error") -> list[dict[str, Any]] | None:
        try:
            result = subprocess.run(
                self._rclone_command("lsjson", target_dir, "--files-only"),
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                error_msg = (result.stderr or result.stdout or "rclone lsjson failed")[:1000]
                self._set_setting(error_key, error_msg)
                return None
            payload = json.loads(result.stdout or "[]")
            self._set_setting(error_key, "")
            return payload if isinstance(payload, list) else []
        except Exception as exc:
            self._set_setting(error_key, str(exc))
            return None

    def _rclone_delete_file(self, target_dir: str, filename: str, *, error_key: str = "backup.rclone_last_error") -> bool:
        if not filename or "/" in filename:
            return False
        target = self._rclone_child_target(target_dir, filename)
        try:
            result = subprocess.run(
                self._rclone_command("deletefile", target),
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                self._set_setting(error_key, (result.stderr or result.stdout or "rclone delete failed")[:1000])
                return False
            return True
        except Exception as exc:
            self._set_setting(error_key, str(exc))
            return False

    @staticmethod
    def _rclone_child_target(target_dir: str, filename: str) -> str:
        base = target_dir.rstrip("/")
        if base.endswith(":"):
            return f"{base}{filename}"
        return f"{base}/{filename}"

    @staticmethod
    def _backup_prefix(category: str) -> str:
        return {
            "full": "backup_",
            "postgres": "postgres_",
            "system": "system_",
            "users": "users_",
        }[category]

    @staticmethod
    def _latest_backup_filename(category: str, source_path: str | Path | None = None) -> str:
        suffix = Path(source_path).suffix if source_path is not None else ".upbak"
        return {
            "full": "latest_full.zip" if suffix == ".zip" else "latest_full.upbak",
            "postgres": "latest_postgres.dump",
            "system": "latest_system.tar.gz",
            "users": "latest_users.json.gz",
        }[category]

    @staticmethod
    def _latest_backup_filenames(category: str) -> list[str]:
        if category == "full":
            return ["latest_full.upbak", "latest_full.zip"]
        return [BackupService._latest_backup_filename(category)]

    @staticmethod
    def _managed_backup_prefix_for_path(path: str) -> str:
        if path.startswith("backup_"):
            return "backup_"
        if path.startswith("postgres_"):
            return "postgres_"
        if path.startswith("system_"):
            return "system_"
        return "users_"

    def rclone_pull_latest(self, category: str, *, target: str = "rclone") -> dict:
        """Download the latest backup for a category from the rclone remote."""
        category = str(category or "").strip().lower()
        if category not in SPLIT_BACKUP_CATEGORIES:
            return {"success": False, "error": "category must be full, system, users, or postgres"}
        target_config = self._rclone_target_config(target)
        remote = target_config["remote"]
        if not remote:
            return {"success": False, "remote": "", "target": target_config["target"], "error": target_config["missing_error"]}
        if not shutil.which("rclone"):
            msg = "rclone binary not found - install rclone in container"
            self._set_rclone_target_error(target_config, msg)
            return {"success": False, "remote": remote, "target": target_config["target"], "error": msg}

        remote_path = target_config["path"]
        local_dir = self._backup_category_dir(category)
        local_dir.mkdir(parents=True, exist_ok=True)
        errors: list[str] = []
        for filename in self._latest_backup_filenames(category):
            destination = local_dir / filename
            source = f"{remote}:{remote_path}/{filename}" if remote_path else f"{remote}:{filename}"
            try:
                result = subprocess.run(
                    self._rclone_command("copyto", source, str(destination), "--log-level", "ERROR"),
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                if result.returncode != 0:
                    error_msg = (result.stderr or result.stdout or "rclone download failed")[:1000]
                    errors.append(f"{filename}: {error_msg}")
                    destination.unlink(missing_ok=True)
                    continue
                self._set_rclone_target_error(target_config, "")
                return {
                    "success": True,
                    "category": category,
                    "target": target_config["target"],
                    "remote": source,
                    "path": str(destination),
                    "size": destination.stat().st_size if destination.exists() else 0,
                }
            except subprocess.TimeoutExpired:
                errors.append(f"{filename}: rclone download timed out (300s)")
                destination.unlink(missing_ok=True)
            except Exception as exc:
                errors.append(f"{filename}: {exc}")
                destination.unlink(missing_ok=True)
        error = "; ".join(errors) or "rclone download failed"
        self._set_rclone_target_error(target_config, error)
        return {"success": False, "remote": f"{remote}:{remote_path}", "target": target_config["target"], "error": error}

    def rclone_restore_latest(self, category: str, *, target: str = "rclone", confirm: str = "") -> dict:
        pulled = self.rclone_pull_latest(category, target=target)
        if not pulled.get("success"):
            return pulled
        restored = self._restore_category_backup(category, pulled["path"], confirm=confirm)
        return {"success": bool(restored.get("success")), "pulled": pulled, "restored": restored}

    def telegram_sync_latest_category(self, category: str) -> dict:
        category = str(category or "").strip().lower()
        if category not in ADMIN_BACKUP_CATEGORIES:
            return {"success": False, "error": "category must be full, system, or users"}
        config = self._telegram_config()
        if not config["bot_token"] or not config["chat_id"]:
            return {"success": False, "target": "telegram", "error": "Telegram bot token and chat ID are required"}
        newest = self._newest_backup_for_category(category)
        if not newest.exists():
            return {"success": False, "target": "telegram", "category": category, "error": f"no local {category} backup found"}
        if self._telegram_uses_public_api() and newest.stat().st_size > TELEGRAM_PUBLIC_SEND_LIMIT_BYTES:
            return {
                "success": False,
                "target": "telegram",
                "category": category,
                "error": "Telegram public Bot API upload limit is 50 MB; use rclone/R2 for this backup or configure a local Bot API server",
            }
        caption = f"EazyFill {category} backup: {newest.name}"
        url = f"{self._telegram_api_base()}/bot{config['bot_token']}/sendDocument"
        try:
            with newest.open("rb") as fh:
                response = httpx.post(
                    url,
                    data={"chat_id": config["chat_id"], "caption": caption},
                    files={"document": (newest.name, fh, "application/octet-stream")},
                    timeout=300,
                )
            payload = response.json() if response.content else {}
            if response.status_code >= 400 or not payload.get("ok"):
                error = str(payload.get("description") or response.text or "Telegram upload failed")[:1000]
                self._set_setting("backup.telegram.last_error", error)
                return {"success": False, "target": "telegram", "category": category, "error": error}
            document = payload.get("result", {}).get("document", {})
            file_id = document.get("file_id", "")
            if not file_id:
                error = "Telegram upload succeeded but no file_id was returned"
                self._set_setting("backup.telegram.last_error", error)
                return {"success": False, "target": "telegram", "category": category, "error": error}
            self._set_setting(f"backup.telegram.latest.{category}.file_id", file_id)
            self._set_setting(f"backup.telegram.latest.{category}.file_name", newest.name)
            self._set_setting("backup.telegram.last_error", "")
            return {
                "success": True,
                "target": "telegram",
                "category": category,
                "filename": newest.name,
                "file_id": file_id,
                "size": newest.stat().st_size,
            }
        except Exception as exc:
            error = str(exc)
            self._set_setting("backup.telegram.last_error", error)
            return {"success": False, "target": "telegram", "category": category, "error": error}

    def telegram_pull_latest(self, category: str) -> dict:
        category = str(category or "").strip().lower()
        if category not in ADMIN_BACKUP_CATEGORIES:
            return {"success": False, "error": "category must be full, system, or users"}
        config = self._telegram_config()
        if not config["bot_token"]:
            return {"success": False, "target": "telegram", "error": "Telegram bot token is required"}
        file_id = self._setting(f"backup.telegram.latest.{category}.file_id", "").strip()
        filename = self._setting(f"backup.telegram.latest.{category}.file_name", self._latest_backup_filename(category)).strip()
        if not file_id:
            return {"success": False, "target": "telegram", "category": category, "error": "No Telegram file_id is stored for this backup category"}
        try:
            file_response = httpx.get(
                f"{self._telegram_api_base()}/bot{config['bot_token']}/getFile",
                params={"file_id": file_id},
                timeout=30,
            )
            file_payload = file_response.json() if file_response.content else {}
            if file_response.status_code >= 400 or not file_payload.get("ok"):
                error = str(file_payload.get("description") or file_response.text or "Telegram getFile failed")[:1000]
                self._set_setting("backup.telegram.last_error", error)
                return {"success": False, "target": "telegram", "category": category, "error": error}
            file_path = file_payload.get("result", {}).get("file_path", "")
            if not file_path:
                return {"success": False, "target": "telegram", "category": category, "error": "Telegram did not return a file path"}
            file_size = int(file_payload.get("result", {}).get("file_size") or 0)
            if self._telegram_uses_public_api() and file_size > TELEGRAM_PUBLIC_DOWNLOAD_LIMIT_BYTES:
                return {
                    "success": False,
                    "target": "telegram",
                    "category": category,
                    "error": "Telegram public Bot API download limit is 20 MB; use rclone/R2 for restore or configure a local Bot API server",
                }
            download = httpx.get(
                f"{self._telegram_file_base()}/bot{config['bot_token']}/{file_path}",
                timeout=300,
            )
            if download.status_code >= 400:
                error = (download.text or "Telegram download failed")[:1000]
                self._set_setting("backup.telegram.last_error", error)
                return {"success": False, "target": "telegram", "category": category, "error": error}
            local_dir = self._backup_category_dir(category)
            local_dir.mkdir(parents=True, exist_ok=True)
            destination = local_dir / Path(filename).name
            destination.write_bytes(download.content)
            self._set_setting("backup.telegram.last_error", "")
            return {
                "success": True,
                "target": "telegram",
                "category": category,
                "path": str(destination),
                "filename": destination.name,
                "size": destination.stat().st_size,
            }
        except Exception as exc:
            error = str(exc)
            self._set_setting("backup.telegram.last_error", error)
            return {"success": False, "target": "telegram", "category": category, "error": error}

    def telegram_restore_latest(self, category: str, *, confirm: str = "") -> dict:
        pulled = self.telegram_pull_latest(category)
        if not pulled.get("success"):
            return pulled
        restored = self._restore_category_backup(category, pulled["path"], confirm=confirm)
        return {"success": bool(restored.get("success")), "pulled": pulled, "restored": restored}

    def _restore_category_backup(self, category: str, backup_path: str | Path, *, confirm: str = "") -> dict:
        category = str(category or "").strip().lower()
        if category == "full":
            return self.restore_full_backup(backup_path, confirm=confirm)
        if category == "system":
            return self.restore_system_backup(backup_path)
        if category == "postgres":
            return self.restore_postgres_backup(backup_path, confirm=confirm or "RESTORE POSTGRES")
        return self.restore_user_backup(backup_path)

    def _backup_category_dir(self, category: str) -> Path:
        if category == "full":
            return self._backup_dir
        return self._backup_dir / category

    def _newest_backup_for_category(self, category: str) -> Path:
        category = str(category or "").strip().lower()
        category_dir = self._backup_category_dir(category)
        prefix = self._backup_prefix(category)
        suffixes = {".upbak", ".zip"} if category == "full" else None
        candidates = []
        if category_dir.exists():
            for path in category_dir.glob(f"{prefix}*"):
                if not path.is_file() or path.name.startswith("latest"):
                    continue
                if suffixes and path.suffix not in suffixes:
                    continue
                candidates.append(path)
        if candidates:
            return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)[0]
        for latest_name in self._latest_backup_filenames(category):
            latest = category_dir / latest_name
            if latest.exists():
                return latest
        return category_dir / self._latest_backup_filename(category)

    def _rclone_target_config(self, target: str = "rclone") -> dict[str, str]:
        normalized = str(target or "rclone").strip().lower().replace("-", "_")
        normalized = "r2" if normalized in {"r2", "cloudflare", "cloudflare_r2"} else "rclone"
        if normalized == "r2":
            remote = self._setting("backup.cloudflare_r2.remote", "cloudflare-r2").strip().rstrip(":")
            bucket = self._setting("backup.cloudflare_r2.bucket", "").strip().strip("/")
            prefix = self._setting("backup.cloudflare_r2.prefix", "eazyfill-backups").strip().strip("/")
            return {
                "target": "r2",
                "remote": remote,
                "path": "/".join(part for part in [bucket, prefix] if part),
                "last_error_key": "backup.cloudflare_r2.last_error",
                "missing_error": "Cloudflare R2 remote and bucket are not configured",
            }
        return {
            "target": "rclone",
            "remote": self._setting("backup.rclone_remote", "").strip().rstrip(":"),
            "path": self._setting("backup.rclone_path", "eazyfill-backups").strip().strip("/"),
            "last_error_key": "backup.rclone_last_error",
            "missing_error": "No rclone remote configured",
        }

    def _set_rclone_target_error(self, target_config: dict[str, str], error: str) -> None:
        self._set_setting(target_config.get("last_error_key", "backup.rclone_last_error"), error)

    def _telegram_config(self) -> dict[str, str]:
        return {
            "bot_token": os.getenv("BACKUP_TELEGRAM_BOT_TOKEN", "").strip() or self._setting("backup.telegram.bot_token", "").strip(),
            "chat_id": os.getenv("BACKUP_TELEGRAM_CHAT_ID", "").strip() or self._setting("backup.telegram.chat_id", "").strip(),
        }

    def _telegram_api_base(self) -> str:
        return os.getenv("BACKUP_TELEGRAM_API_BASE", "https://api.telegram.org").strip().rstrip("/")

    def _telegram_file_base(self) -> str:
        return os.getenv("BACKUP_TELEGRAM_FILE_BASE", f"{self._telegram_api_base()}/file").strip().rstrip("/")

    def _telegram_uses_public_api(self) -> bool:
        return self._telegram_api_base() == "https://api.telegram.org"

    def _export_table_rows(self, table_name: str) -> list[dict[str, Any]]:
        engine = get_engine()
        table = self._reflect_table(table_name)
        with engine.connect() as conn:
            rows = conn.execute(select(table)).mappings().all()
            return [dict(row) for row in rows]

    def _ensure_user_tables(self) -> None:
        """Create user-domain tables before backup/restore when migrations are absent."""
        try:
            from app.core.database import Database

            db = Database(self._settings)
            db.init()
        except Exception as exc:
            logger.warning(f"user_backup_legacy_schema_init_failed: {exc}")

        try:
            import app.core.models  # noqa: F401

            engine = get_engine()
            tables = [
                table for table in Base.metadata.sorted_tables
                if table.name in self.USER_DB_TABLES
            ]
            Base.metadata.create_all(bind=engine, tables=tables)
        except Exception as exc:
            logger.warning(f"user_backup_orm_schema_init_failed: {exc}")

    def _table_exists(self, table_name: str) -> bool:
        return bool(inspect(get_engine()).has_table(table_name))

    def _prepare_user_restore_rows(
        self,
        table_name: str,
        rows: list[dict[str, Any]],
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        if table_name not in {
            "subscription_plans",
            "user_subscriptions",
            "payment_records",
            "payment_webhook_events",
            "user_api_keys",
            "usage_cycles",
            "encrypted_backups",
        }:
            return rows

        now = datetime.now(UTC).isoformat()
        prepared: list[dict[str, Any]] = []
        generated_key_hashes = 0

        for row in rows:
            if not isinstance(row, dict):
                continue
            item = dict(row)
            if table_name == "subscription_plans":
                item.setdefault("created_at", now)
                item.setdefault("updated_at", now)
            elif table_name == "user_subscriptions":
                item.setdefault("updated_at", now)
            elif table_name == "payment_records":
                item.setdefault("updated_at", now)
            elif table_name == "payment_webhook_events":
                item.setdefault("status", "received")
                item.setdefault("payload_json", "{}")
                item.setdefault("error_message", "")
                item.setdefault("received_at", now)
            elif table_name == "user_api_keys":
                item.setdefault("revoked_reason", "")
                if not item.get("key_hash"):
                    seed = f"{table_name}:{item.get('id')}:{item.get('user_id')}:{item.get('key_prefix_display')}"
                    item["key_hash"] = "restored_missing_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()
                    generated_key_hashes += 1
            elif table_name == "usage_cycles":
                item.setdefault("updated_at", now)
            elif table_name == "encrypted_backups":
                item.setdefault("sync_version", 1)
                item.setdefault("blob_size_bytes", len(item.get("encrypted_blob") or b""))
                item.setdefault("created_at", now)
                item.setdefault("updated_at", now)
            prepared.append(item)

        if generated_key_hashes:
            warnings.append(
                f"user_api_keys: generated {generated_key_hashes} placeholder key_hash values "
                "because the backup did not contain real key hashes"
            )
        return prepared

    def _add_missing_legacy_api_key_parents(
        self,
        payload: dict[str, list[dict[str, Any]]],
        warnings: list[str],
    ) -> None:
        api_key_rows = payload.get("api_keys")
        if not isinstance(api_key_rows, list):
            return

        present_ids = {
            int(row["id"])
            for row in api_key_rows
            if isinstance(row, dict) and row.get("id") is not None
        }
        referenced_ids: set[int] = set()
        for table_name, column_name in {
            "api_key_allowed_domains": "key_id",
            "api_key_rate_limits": "key_id",
            "api_key_device_bindings": "key_id",
            "usage_events": "key_id",
        }.items():
            rows = payload.get(table_name) or []
            for row in rows:
                if not isinstance(row, dict) or row.get(column_name) is None:
                    continue
                try:
                    referenced_ids.add(int(row[column_name]))
                except (TypeError, ValueError):
                    continue

        missing_ids = sorted(referenced_ids - present_ids)
        if not missing_ids:
            return

        now = datetime.now(UTC).isoformat()
        for key_id in missing_ids:
            seed = f"restored_missing_legacy_api_key:{key_id}"
            api_key_rows.append({
                "id": key_id,
                "name": f"Restored missing legacy API key #{key_id}",
                "key_hash": "restored_missing_" + hashlib.sha256(seed.encode("utf-8")).hexdigest(),
                "enabled": 0,
                "all_domains": 0,
                "created_at": now,
                "expires_at": None,
                "revoked_at": now,
                "key_type": "restored_missing",
                "plan_name": "Restored Missing Parent",
                "mobile": "",
                "services_json": "{}",
            })
        warnings.append(
            "api_keys: added disabled placeholder parent rows for missing referenced "
            f"legacy key ids: {', '.join(str(item) for item in missing_ids)}"
        )

    def _resolve_full_backup_path(self, backup_path: str | Path) -> Path:
        path = Path(backup_path)
        if not path.is_absolute():
            path = self._backup_dir / path
        resolved = path.resolve()
        backup_dir = self._backup_dir.resolve()
        if resolved != backup_dir and backup_dir not in resolved.parents:
            raise ValueError("backup path outside full backup directory")
        if not resolved.exists() or not resolved.is_file():
            raise FileNotFoundError(f"backup not found: {path}")
        if resolved.suffix not in {".upbak", ".zip"}:
            raise ValueError("full snapshot must be a .upbak or .zip package")
        return resolved

    def _resolve_split_backup_path(self, category: str, backup_path: str | Path) -> Path:
        path = Path(backup_path)
        if not path.is_absolute():
            path = self._backup_dir / category / path
        resolved = path.resolve()
        category_dir = (self._backup_dir / category).resolve()
        if resolved != category_dir and category_dir not in resolved.parents:
            raise ValueError(f"backup path outside {category} backup directory")
        if not resolved.exists() or not resolved.is_file():
            raise FileNotFoundError(f"backup not found: {path}")
        return resolved

    def _restore_tar_member(self, tar: tarfile.TarFile, member: tarfile.TarInfo) -> None:
        if member.islnk() or member.issym():
            raise ValueError(f"unsafe backup link: {member.name}")
        target = (self._root / member.name).resolve()
        root = self._root.resolve()
        if target != root and root not in target.parents:
            raise ValueError(f"unsafe backup path: {member.name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        source = tar.extractfile(member)
        if not source:
            return
        with source, target.open("wb") as out:
            out.write(source.read())

    def _restore_table_rows(self, table_name: str, rows: list[dict[str, Any]]) -> int:
        allowed_tables = set(self.SYSTEM_DB_TABLES) | set(self.USER_DB_TABLES)
        if table_name not in allowed_tables:
            raise ValueError(f"restore not allowed for table: {table_name}")
        if not isinstance(rows, list):
            raise ValueError(f"table payload must be a list: {table_name}")

        engine = get_engine()
        table = self._reflect_table(table_name)
        with engine.begin() as conn:
            conn.execute(delete(table))
            if rows:
                usable_columns = [col.name for col in table.columns if any(col.name in row for row in rows)]
                if not usable_columns:
                    raise ValueError(f"no restorable columns for table: {table_name}")
                values = [
                    self._prepare_reflected_row(table, row, usable_columns)
                    for row in rows
                ]
                conn.execute(insert(table), values)
            self._reset_postgres_identity_sequence(conn, table)
        return len(rows)

    def _restore_table_group(self, table_names: list[str], payload: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
        restored: dict[str, int] = {}
        engine = get_engine()
        tables: dict[str, Table] = {}
        with engine.begin() as conn:
            for table_name in table_names:
                if table_name not in payload:
                    continue
                tables[table_name] = self._reflect_table(table_name)

            for table_name in reversed([name for name in table_names if name in payload]):
                conn.execute(delete(tables[table_name]))

            for table_name in [name for name in table_names if name in payload]:
                rows = payload[table_name]
                if not isinstance(rows, list):
                    raise ValueError(f"table payload must be a list: {table_name}")
                table = tables[table_name]
                if rows:
                    usable_columns = [col.name for col in table.columns if any(col.name in row for row in rows)]
                    if not usable_columns:
                        raise ValueError(f"no restorable columns for table: {table_name}")
                    values = [
                        self._prepare_reflected_row(table, row, usable_columns)
                        for row in rows
                    ]
                    conn.execute(insert(table), values)
                    self._reset_postgres_identity_sequence(conn, table)
                restored[table_name] = len(rows)
        return restored

    def _reflect_table(self, table_name: str) -> Table:
        metadata = MetaData()
        try:
            return Table(table_name, metadata, autoload_with=get_engine())
        except Exception as exc:
            raise ValueError(f"table does not exist: {table_name}") from exc

    def _prepare_reflected_row(self, table: Table, row: dict[str, Any], usable_columns: list[str]) -> dict[str, Any]:
        return {
            column_name: self._coerce_db_value(table.columns[column_name].type, row.get(column_name))
            for column_name in usable_columns
        }

    def _reset_postgres_identity_sequence(self, conn, table: Table) -> None:
        if conn.dialect.name != "postgresql":
            return
        for column in table.primary_key.columns:
            if not getattr(column.type, "python_type", None):
                continue
            try:
                if column.type.python_type is not int:
                    continue
            except NotImplementedError:
                continue
            quoted_column = column.name.replace('"', '""')
            quoted_table = table.name.replace('"', '""')
            sequence_name = conn.execute(
                text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
                {"table_name": table.name, "column_name": column.name},
            ).scalar()
            if not sequence_name:
                continue
            max_value = conn.execute(
                text(
                    f"SELECT MAX(\"{quoted_column}\") FROM \"{quoted_table}\""
                ),
            ).scalar()
            conn.execute(
                text("SELECT setval(:sequence_name, :value, :is_called)"),
                {
                    "sequence_name": sequence_name,
                    "value": max_value if max_value is not None else 1,
                    "is_called": max_value is not None,
                },
            )

    @staticmethod
    def _coerce_db_value(column_type: Any, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(column_type, SAJSON):
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return value
            return value
        if isinstance(column_type, DateTime) and isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        if isinstance(column_type, Date) and isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        if isinstance(column_type, Time) and isinstance(value, str):
            return datetime.fromisoformat(f"1970-01-01T{value}").time()
        if isinstance(column_type, Boolean) and isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return value

    @staticmethod
    def _sqlite_value(value: Any) -> Any:
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, default=str)
        return value

    @staticmethod
    def _item_count(value: Any) -> int:
        if isinstance(value, list):
            return len(value)
        if isinstance(value, dict):
            return len(value)
        return 0
