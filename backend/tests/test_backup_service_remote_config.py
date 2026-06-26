from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.services import backup_service
from app.services.backup_service import BackupService


def _service(tmp_path, monkeypatch):
    settings = MagicMock()
    settings.storage.sqlite_path = str(tmp_path / "app.db")
    settings.storage.db_type = "sqlite"
    settings.storage.database_url = ""
    monkeypatch.setenv("RCLONE_CONFIG", str(tmp_path / "rclone.conf"))
    service = BackupService(settings)
    store = {}
    service._setting = lambda key, default="": store.get(key, default)
    service._set_setting = lambda key, value: store.__setitem__(key, value)
    return service, store, Path(tmp_path / "rclone.conf")


def _postgres_service(tmp_path, monkeypatch):
    service, store, config_path = _service(tmp_path, monkeypatch)
    service._settings.storage.db_type = "postgresql"
    service._settings.storage.database_url = ""
    monkeypatch.setenv("POSTGRES_HOST", "postgres")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_DB", "app")
    monkeypatch.setenv("POSTGRES_USER", "appuser")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
    return service, store, config_path


def test_save_remote_backup_config_writes_settings_and_rclone_conf(tmp_path, monkeypatch):
    service, store, config_path = _service(tmp_path, monkeypatch)
    monkeypatch.setattr(backup_service.shutil, "which", lambda _name: None)

    result = service.save_remote_backup_config({
        "rclone_remote": "gdrive:",
        "rclone_path": "/eazyfill-backups/",
        "rclone_config": "[gdrive]\ntype = drive\n",
        "backup_size_cap_mb": "1024",
    })

    assert store["backup.rclone_remote"] == "gdrive"
    assert store["backup.rclone_path"] == "eazyfill-backups"
    assert store["backup.size_cap_bytes"] == str(1024 * 1024 * 1024)
    assert store["backup.remote_size_cap_bytes"] == str(1024 * 1024 * 1024)
    assert result["backup_size_cap_mb"] == 1024
    assert result["backup_remote_size_cap_mb"] == 1024
    assert config_path.read_text(encoding="utf-8") == "[gdrive]\ntype = drive\n"
    assert result["rclone_config_exists"] is True
    assert result["rclone_config"] == "[gdrive]\ntype = drive\n"


def test_rclone_remote_test_uses_saved_config_and_remote_root(tmp_path, monkeypatch):
    service, store, config_path = _service(tmp_path, monkeypatch)
    store["backup.rclone_remote"] = "gdrive"
    store["backup.rclone_path"] = "eazyfill-backups"
    config_path.write_text("[gdrive]\ntype = drive\n", encoding="utf-8")
    seen = {}

    class Result:
        returncode = 0
        stdout = "          -1 2026-05-25 backup-folder\n"
        stderr = ""

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        return Result()

    monkeypatch.setattr(backup_service.shutil, "which", lambda _name: "/usr/bin/rclone")
    monkeypatch.setattr(backup_service.subprocess, "run", fake_run)

    result = service.test_rclone_remote()

    assert result["ok"] is True
    assert result["remote"] == "gdrive:eazyfill-backups"
    assert seen["cmd"] == ["rclone", "--config", str(config_path), "lsd", "gdrive:"]
    assert seen["kwargs"]["timeout"] == 30
    assert store["backup.rclone_last_error"] == ""


def test_cloudflare_r2_preset_writes_s3_rclone_config(tmp_path, monkeypatch):
    service, store, config_path = _service(tmp_path, monkeypatch)
    monkeypatch.setattr(backup_service.shutil, "which", lambda _name: None)

    result = service.save_remote_backup_config({
        "cloudflare_r2_remote": "r2",
        "cloudflare_r2_account_id": "account123",
        "cloudflare_r2_bucket": "eazyfill",
        "cloudflare_r2_prefix": "prod",
        "cloudflare_r2_access_key_id": "access123",
        "cloudflare_r2_secret_access_key": "secret123",
    })

    assert store["backup.cloudflare_r2.remote"] == "r2"
    assert store["backup.cloudflare_r2.bucket"] == "eazyfill"
    assert "backup.rclone_remote" not in store
    assert result["cloudflare_r2_access_key_set"] is True
    assert result["cloudflare_r2_secret_key_set"] is True
    text = config_path.read_text(encoding="utf-8")
    assert "[r2]" in text
    assert "provider = Cloudflare" in text
    assert "endpoint = https://account123.r2.cloudflarestorage.com" in text


def test_default_backup_retention_cap_is_two_gb(tmp_path, monkeypatch):
    service, _store, _config_path = _service(tmp_path, monkeypatch)

    assert service._backup_size_cap_bytes() == 2 * 1024 * 1024 * 1024


def test_blank_cloudflare_fields_do_not_break_plain_rclone_save(tmp_path, monkeypatch):
    service, store, config_path = _service(tmp_path, monkeypatch)
    monkeypatch.setattr(backup_service.shutil, "which", lambda _name: None)

    result = service.save_remote_backup_config({
        "rclone_remote": "gdrive",
        "rclone_path": "eazyfill-backups",
        "cloudflare_r2_remote": "cloudflare-r2",
        "cloudflare_r2_account_id": "",
        "cloudflare_r2_bucket": "",
        "cloudflare_r2_access_key_id": "",
        "cloudflare_r2_secret_access_key": "",
    })

    assert store["backup.rclone_remote"] == "gdrive"
    assert result["rclone_remote"] == "gdrive"
    assert not config_path.exists()


def test_backup_scope_tracks_current_eazyfill_data(tmp_path, monkeypatch):
    service, _store, _config_path = _service(tmp_path, monkeypatch)

    assert "encrypted_backups" in service.USER_DB_TABLES
    assert "payment_webhook_events" in service.USER_DB_TABLES
    assert "exam_workflow_usage" not in service.USER_DB_TABLES
    assert "exam_learned" not in service.SYSTEM_DB_TABLES
    assert "automation_methods" not in service.SYSTEM_DB_TABLES
    assert "data/questions" not in backup_service.SYSTEM_FILE_ROOTS
    assert "data/hashes" not in backup_service.SYSTEM_FILE_ROOTS

    warnings: list[str] = []
    webhook_rows = service._prepare_user_restore_rows(
        "payment_webhook_events",
        [{"provider": "razorpay", "event_id": "evt_1"}],
        warnings,
    )
    assert webhook_rows[0]["status"] == "received"
    assert webhook_rows[0]["payload_json"] == "{}"

    sync_rows = service._prepare_user_restore_rows(
        "encrypted_backups",
        [{"user_id": 1, "device_id": "device-1", "encrypted_blob": b"abc", "blob_hash": "sha256:test"}],
        warnings,
    )
    assert sync_rows[0]["sync_version"] == 1
    assert sync_rows[0]["blob_size_bytes"] == 3


def test_upbak_encryption_uses_authenticated_aesgcm_and_reads_legacy(tmp_path, monkeypatch):
    service, store, _config_path = _service(tmp_path, monkeypatch)
    store["backup.encryption_key"] = "test-backup-secret"
    plaintext = b"PK\x03\x04fake zip bytes"

    encrypted = backup_service._encrypt_package_bytes(plaintext, store["backup.encryption_key"])
    package = service._backup_dir / "backup_test.upbak"
    package.write_bytes(encrypted)

    assert encrypted.startswith(backup_service.AEAD_BACKUP_MAGIC)
    assert service._read_package_bytes(package) == plaintext

    tampered = bytearray(encrypted)
    tampered[-1] ^= 1
    package.write_bytes(bytes(tampered))
    with pytest.raises(Exception):
        service._read_package_bytes(package)

    legacy = backup_service._xor_stream(plaintext, store["backup.encryption_key"])
    package.write_bytes(legacy)
    assert service._read_package_bytes(package) == plaintext


def test_rclone_pull_latest_downloads_expected_category_file(tmp_path, monkeypatch):
    service, store, config_path = _service(tmp_path, monkeypatch)
    store["backup.rclone_remote"] = "r2"
    store["backup.rclone_path"] = "eazyfill/prod"
    config_path.write_text("[r2]\ntype = s3\n", encoding="utf-8")
    seen = {}

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        destination = Path(cmd[5])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("backup", encoding="utf-8")
        return Result()

    monkeypatch.setattr(backup_service.shutil, "which", lambda _name: "/usr/bin/rclone")
    monkeypatch.setattr(backup_service.subprocess, "run", fake_run)

    result = service.rclone_pull_latest("users")

    assert result["success"] is True
    assert seen["cmd"] == [
        "rclone",
        "--config",
        str(config_path),
        "copyto",
        "r2:eazyfill/prod/latest_users.json.gz",
        result["path"],
        "--log-level",
        "ERROR",
    ]


def test_rclone_sync_latest_category_uploads_history_latest_and_prunes_by_size_cap(tmp_path, monkeypatch):
    service, store, config_path = _service(tmp_path, monkeypatch)
    store["backup.rclone_remote"] = "r2"
    store["backup.rclone_path"] = "eazyfill/prod"
    store["backup.size_cap_bytes"] = "20"
    config_path.write_text("[r2]\ntype = s3\n", encoding="utf-8")
    backup_dir = service._backup_dir / "system"
    backup_dir.mkdir(parents=True, exist_ok=True)
    newest = backup_dir / "system_20260610_120000.tar.gz"
    newest.write_bytes(b"newest")

    commands = []

    class Result:
        def __init__(self, stdout="", returncode=0):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        if "lsjson" in cmd:
            return Result(
                stdout=(
                    '[{"Path":"system_20260610_120000.tar.gz","Size":6,"ModTime":"2026-06-10T12:00:00Z"},'
                    '{"Path":"system_20260609_120000.tar.gz","Size":6,"ModTime":"2026-06-09T12:00:00Z"},'
                    '{"Path":"system_20260608_120000.tar.gz","Size":6,"ModTime":"2026-06-08T12:00:00Z"},'
                    '{"Path":"latest_system.tar.gz","Size":6,"ModTime":"2026-06-10T12:00:01Z"}]'
                )
            )
        return Result()

    monkeypatch.setattr(backup_service.shutil, "which", lambda _name: "/usr/bin/rclone")
    monkeypatch.setattr(backup_service.subprocess, "run", fake_run)

    result = service.rclone_sync_latest_category("system")

    assert result["success"] is True
    copy_commands = [cmd for cmd in commands if "copyto" in cmd]
    assert copy_commands[0][4:] == [
        str(newest),
        "r2:eazyfill/prod/system_20260610_120000.tar.gz",
        "--log-level",
        "ERROR",
    ]
    assert copy_commands[1][4:] == [
        str(newest),
        "r2:eazyfill/prod/latest_system.tar.gz",
        "--log-level",
        "ERROR",
    ]
    delete_commands = [cmd for cmd in commands if "deletefile" in cmd]
    assert delete_commands == [
        ["rclone", "--config", str(config_path), "deletefile", "r2:eazyfill/prod/system_20260608_120000.tar.gz"]
    ]


def test_full_backup_list_reads_root_packages_and_rclone_uploads_latest_alias(tmp_path, monkeypatch):
    service, store, config_path = _service(tmp_path, monkeypatch)
    store["backup.rclone_remote"] = "gdrive"
    store["backup.rclone_path"] = "eazyfill/prod"
    config_path.write_text("[gdrive]\ntype = drive\n", encoding="utf-8")
    full = service._backup_dir / "backup_20260610_120000.upbak"
    full.write_bytes(b"full")
    commands = []

    class Result:
        def __init__(self, stdout="", returncode=0):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        if "lsjson" in cmd:
            return Result(stdout='[{"Path":"backup_20260610_120000.upbak","Size":4,"ModTime":"2026-06-10T12:00:00Z"}]')
        return Result()

    monkeypatch.setattr(backup_service.shutil, "which", lambda _name: "/usr/bin/rclone")
    monkeypatch.setattr(backup_service.subprocess, "run", fake_run)

    listed = service.list_all_backups()
    result = service.rclone_sync_latest_category("full")

    assert listed["full"][0]["name"] == full.name
    assert result["success"] is True
    copy_commands = [cmd for cmd in commands if "copyto" in cmd]
    assert copy_commands[0][4:] == [str(full), "gdrive:eazyfill/prod/backup_20260610_120000.upbak", "--log-level", "ERROR"]
    assert copy_commands[1][4:] == [str(full), "gdrive:eazyfill/prod/latest_full.upbak", "--log-level", "ERROR"]


def test_telegram_restore_is_dump_only(tmp_path, monkeypatch):
    service, _store, _config_path = _service(tmp_path, monkeypatch)

    pull = service.telegram_pull_latest("system")
    restore = service.telegram_restore_latest("system")

    assert pull["success"] is False
    assert pull["target"] == "telegram"
    assert "dump-only" in pull["error"]
    assert restore["success"] is False
    assert "disabled" in restore["error"]


def test_create_postgres_backup_uses_pg_dump_and_verifies_dump(tmp_path, monkeypatch):
    service, _store, _config_path = _postgres_service(tmp_path, monkeypatch)
    commands = []

    class Result:
        def __init__(self, stdout="", returncode=0):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    def fake_run(cmd, **kwargs):
        commands.append((cmd, kwargs))
        if cmd[0] == "pg_dump":
            Path(cmd[cmd.index("--file") + 1]).write_bytes(b"postgres-dump")
            assert kwargs["env"]["PGPASSWORD"] == "secret"
            assert "secret" not in " ".join(cmd)
            return Result()
        if cmd[:2] == ["pg_restore", "--list"]:
            return Result(stdout="1; table public users\n2; table public api_keys\n")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(backup_service.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(backup_service.subprocess, "run", fake_run)

    result = service.create_postgres_backup()

    assert result["success"] is True
    assert result["type"] == "postgres"
    assert result["objects"] == 2
    assert Path(result["path"]).exists()
    assert (service._backup_dir / "postgres" / "latest_postgres.dump").exists()
    assert commands[0][0][0] == "pg_dump"


def test_restore_postgres_backup_requires_confirmation(tmp_path, monkeypatch):
    service, _store, _config_path = _postgres_service(tmp_path, monkeypatch)
    pg_dir = service._backup_dir / "postgres"
    pg_dir.mkdir(parents=True, exist_ok=True)
    backup_path = pg_dir / "postgres_20260610_120000.dump"
    backup_path.write_bytes(b"dump")

    result = service.restore_postgres_backup(backup_path.name)

    assert result == {"success": False, "error": "confirmation phrase required"}
