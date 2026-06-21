import sqlite3
from unittest.mock import MagicMock

from app.core.database import Database


def _settings(tmp_path):
    settings = MagicMock()
    settings.storage.sqlite_path = str(tmp_path / "app.db")
    settings.storage.db_type = "sqlite"
    settings.storage.database_url = ""
    settings.auth.hash_salt = "test-salt"
    settings.auth.admin_token = "test-admin"
    settings.auth.admin_password = "test-password"
    settings.auth.key_prefix = "fp_"
    settings.auth.key_length = 32
    settings.auth.default_expiry_days = 30
    return settings


def _create_legacy_reporter_tables(db_path):
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE field_mapping_proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT NOT NULL,
                task_type TEXT NOT NULL,
                source_data_type TEXT NOT NULL,
                source_selector TEXT NOT NULL,
                target_data_type TEXT NOT NULL,
                target_selector TEXT NOT NULL,
                proposed_field_name TEXT NOT NULL,
                reported_by INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                FOREIGN KEY(reported_by) REFERENCES api_keys(id)
            );

            CREATE TABLE retrain_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT NOT NULL,
                image_path TEXT NOT NULL,
                task_type TEXT NOT NULL DEFAULT 'image',
                field_name TEXT,
                reported_by INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                label_text TEXT,
                labeled_by INTEGER,
                labeled_at TEXT,
                consumed_by_job_id INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY(reported_by) REFERENCES api_keys(id)
            );
            """
        )


def test_route_learning_tables_accept_v2_user_key_reporters(tmp_path):
    settings = _settings(tmp_path)
    _create_legacy_reporter_tables(settings.storage.sqlite_path)

    db = Database(settings)
    db.init()

    proposal = db.propose_field_mapping(
        domain="example.com",
        task_type="image",
        source_data_type="image",
        source_selector="#captcha-img",
        target_data_type="text",
        target_selector="#captcha-answer",
        proposed_field_name="login_captcha",
        reported_by=99,
        reported_by_kind="user_api_key",
        reported_by_user_id=42,
    )
    assert proposal is not None
    assert proposal["reported_by"] == 99
    assert proposal["reported_by_kind"] == "user_api_key"
    assert proposal["reported_by_user_id"] == 42

    sample_id = db.add_retrain_sample(
        domain="example.com",
        image_path="data/captcha_samples/sample.png",
        reported_by=99,
        reported_by_kind="user_api_key",
        reported_by_user_id=42,
        task_type="image",
        field_name="login_captcha",
        label_text="X7K2",
    )
    assert sample_id
