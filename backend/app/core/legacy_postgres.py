"""PostgreSQL DB-API adapter for transitional legacy repositories.

This module is intentionally narrow: it supports the SQLite idioms that still
exist in the legacy raw-SQL repositories and raises for unknown dangerous
patterns instead of silently guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Iterator

import psycopg2
from psycopg2.extras import RealDictCursor


_INSERT_OR_IGNORE_RE = re.compile(r"^\s*INSERT\s+OR\s+IGNORE\s+INTO\s+", re.IGNORECASE)
_INSERT_OR_REPLACE_RE = re.compile(
    r"^\s*INSERT\s+OR\s+REPLACE\s+INTO\s+model_routes\s*"
    r"\(\s*domain\s*,\s*ai_model_filename\s*\)\s*VALUES\s*\(\s*\?\s*,\s*\?\s*\)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_INSERT_TABLE_RE = re.compile(r"^\s*INSERT\s+INTO\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", re.IGNORECASE | re.DOTALL)
_RETURNING_RE = re.compile(r"\bRETURNING\b", re.IGNORECASE)

_TABLES_WITH_ID = {
    "active_learning",
    "api_keys",
    "failed_payload_labels",
    "field_mapping_proposals",
    "field_mappings",
    "model_lifecycle_events",
    "model_registry",
    "retrain_jobs",
    "retrain_samples",
    "usage_events",
}

_BLOCKED_SQLITE_TOKENS = (
    "sqlite_master",
    "PRAGMA",
    "AUTOINCREMENT",
    "last_insert_rowid",
)


def _replace_qmark_placeholders(sql: str) -> str:
    out: list[str] = []
    in_single = False
    in_double = False
    index = 0
    while index < len(sql):
        char = sql[index]
        next_char = sql[index + 1] if index + 1 < len(sql) else ""
        if char == "'" and not in_double:
            out.append(char)
            if in_single and next_char == "'":
                out.append(next_char)
                index += 2
                continue
            in_single = not in_single
            index += 1
            continue
        if char == '"' and not in_single:
            out.append(char)
            in_double = not in_double
            index += 1
            continue
        if char == "?" and not in_single and not in_double:
            out.append("%s")
        else:
            out.append(char)
        index += 1
    return "".join(out)


def translate_sqlite_sql(sql: str) -> tuple[str, bool]:
    """Translate supported SQLite-style SQL to PostgreSQL SQL.

    Returns ``(translated_sql, returns_id)``. ``returns_id`` tells the adapter
    to capture ``cursor.lastrowid`` from ``RETURNING id``.
    """
    if any(token.lower() in sql.lower() for token in _BLOCKED_SQLITE_TOKENS):
        raise ValueError(f"SQLite-only SQL is not supported in PostgreSQL legacy mode: {sql[:80]}")

    returns_id = False
    translated = sql.strip()

    if _INSERT_OR_REPLACE_RE.match(translated):
        translated = (
            "INSERT INTO model_routes (domain, ai_model_filename) VALUES (?, ?) "
            "ON CONFLICT (domain) DO UPDATE SET ai_model_filename = EXCLUDED.ai_model_filename"
        )
    elif _INSERT_OR_IGNORE_RE.match(translated):
        translated = _INSERT_OR_IGNORE_RE.sub("INSERT INTO ", translated, count=1)
        translated = f"{translated} ON CONFLICT DO NOTHING"

    table_match = _INSERT_TABLE_RE.match(translated)
    if table_match and not _RETURNING_RE.search(translated):
        table_name = table_match.group(1).lower()
        if table_name in _TABLES_WITH_ID:
            translated = f"{translated} RETURNING id"
            returns_id = True

    return _replace_qmark_placeholders(translated), returns_id


@dataclass
class LegacyPostgresCursor:
    _cursor: Any
    _returns_id: bool = False
    lastrowid: int | None = None

    @property
    def rowcount(self) -> int:
        return int(getattr(self._cursor, "rowcount", -1))

    def _capture_lastrowid(self) -> None:
        if not self._returns_id:
            return
        row = self._cursor.fetchone()
        if row and "id" in row:
            self.lastrowid = int(row["id"])

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def __iter__(self) -> Iterator[Any]:
        return iter(self._cursor)


class LegacyPostgresConnection:
    def __init__(self, database_url: str) -> None:
        self._connection = psycopg2.connect(database_url, cursor_factory=RealDictCursor)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    def execute(self, sql: str, params: Iterable[Any] | None = None) -> LegacyPostgresCursor:
        translated, returns_id = translate_sqlite_sql(sql)
        cursor = self._connection.cursor()
        cursor.execute(translated, tuple(params or ()))
        wrapped = LegacyPostgresCursor(cursor, returns_id)
        wrapped._capture_lastrowid()
        return wrapped

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()


def legacy_postgres_connect(database_url: str) -> LegacyPostgresConnection:
    return LegacyPostgresConnection(database_url)
