from unittest.mock import MagicMock

import pytest

from app.core.legacy_postgres import LegacyPostgresCursor, translate_sqlite_sql


def test_translate_qmark_placeholders_ignores_string_literals():
    sql, returns_id = translate_sqlite_sql(
        "SELECT * FROM platform_settings WHERE key = ? AND value != '?'"
    )

    assert sql == "SELECT * FROM platform_settings WHERE key = %s AND value != '?'"
    assert returns_id is False


def test_translate_insert_adds_returning_for_id_table():
    sql, returns_id = translate_sqlite_sql(
        "INSERT INTO api_keys (name, key_hash, created_at) VALUES (?, ?, ?)"
    )

    assert sql == "INSERT INTO api_keys (name, key_hash, created_at) VALUES (%s, %s, %s) RETURNING id"
    assert returns_id is True


def test_translate_insert_or_ignore_to_conflict_do_nothing():
    sql, returns_id = translate_sqlite_sql(
        "INSERT OR IGNORE INTO allowed_domains (domain) VALUES (?)"
    )

    assert sql == "INSERT INTO allowed_domains (domain) VALUES (%s) ON CONFLICT DO NOTHING"
    assert returns_id is False


def test_translate_insert_or_replace_model_route_to_upsert():
    sql, returns_id = translate_sqlite_sql(
        "INSERT OR REPLACE INTO model_routes (domain, ai_model_filename) VALUES (?, ?)"
    )

    assert sql == (
        "INSERT INTO model_routes (domain, ai_model_filename) VALUES (%s, %s) "
        "ON CONFLICT (domain) DO UPDATE SET ai_model_filename = EXCLUDED.ai_model_filename"
    )
    assert returns_id is False


def test_translate_blocks_sqlite_catalog_queries():
    with pytest.raises(ValueError):
        translate_sqlite_sql("SELECT name FROM sqlite_master WHERE type='table'")


def test_legacy_postgres_cursor_supports_sqlite_style_iteration():
    raw_cursor = MagicMock()
    raw_cursor.__iter__.return_value = iter([{"id": 1}, {"id": 2}])
    cursor = LegacyPostgresCursor(raw_cursor)

    assert [dict(row) for row in cursor] == [{"id": 1}, {"id": 2}]
