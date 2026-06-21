"""Shared test fixtures for the EazyFill test suite."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure test environment
os.environ.setdefault("AUTH_HASH_SALT", "test-salt-do-not-use-in-prod")
os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("APP_ENV", "test")


@pytest.fixture
def mock_settings():
    """Create a mock Settings object with test values."""
    settings = MagicMock()
    settings.auth.hash_salt = "test-salt-do-not-use-in-prod"
    settings.auth.admin_token = "test-admin-token"
    settings.auth.default_expiry_days = 30
    settings.auth.key_prefix = "SK-"
    settings.auth.key_length = 32
    settings.server.debug = True
    settings.storage.sqlite_path = ":memory:"
    return settings


@pytest.fixture
def tmp_data_dir():
    """Create a temporary data directory with minimal test data."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # Create required subdirectories
        (tmp_path / "questions").mkdir(parents=True)
        (tmp_path / "hashes").mkdir(parents=True)
        (tmp_path / "models").mkdir(parents=True)

        # Minimal questions.json
        (tmp_path / "questions" / "questions.json").write_text(
            json.dumps([
                {
                    "question_text": "What is the speed limit in a residential area?",
                    "correct_option_number": 2,
                    "option_1": "60 km/h",
                    "option_2": "25 km/h",
                    "option_3": "80 km/h",
                    "option_4": "100 km/h",
                }
            ]),
            encoding="utf-8",
        )

        # Minimal sign hashes
        (tmp_path / "hashes" / "sign_hashes.json").write_text(
            json.dumps({"abc123": "STOP"}),
            encoding="utf-8",
        )
        (tmp_path / "hashes" / "sign_label.json").write_text(
            json.dumps({"STOP": "Stop Sign"}),
            encoding="utf-8",
        )
        (tmp_path / "hashes" / "sign_hashes_perceptual.json").write_text(
            json.dumps({}),
            encoding="utf-8",
        )

        yield tmp_path


@pytest.fixture
def mock_db():
    """Create a mock Database object."""
    db = MagicMock()
    db.get_setting.return_value = ""
    db.get_api_key_by_hash.return_value = None
    return db


@pytest.fixture
def mock_key_service(mock_db, mock_settings):
    """Create a mock KeyService."""
    from app.services.key_service import KeyService
    return KeyService(db=mock_db, settings=mock_settings)
