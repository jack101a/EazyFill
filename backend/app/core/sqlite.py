"""SQLite connection helpers shared by runtime and maintenance tasks."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

DEFAULT_SQLITE_BUSY_TIMEOUT_MS = 15_000


def sqlite_busy_timeout_ms() -> int:
    """Return a safe busy timeout so brief write locks do not fail immediately."""
    raw = os.getenv("SQLITE_BUSY_TIMEOUT_MS", str(DEFAULT_SQLITE_BUSY_TIMEOUT_MS))
    try:
        return max(1_000, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_SQLITE_BUSY_TIMEOUT_MS


def sqlite_timeout_seconds() -> float:
    return sqlite_busy_timeout_ms() / 1000.0


def configure_sqlite_connection(
    connection: sqlite3.Connection,
    *,
    wal: bool = False,
    foreign_keys: bool = False,
    synchronous_normal: bool = False,
) -> None:
    """Apply SQLite pragmas that are safe for every new connection."""
    timeout_ms = sqlite_busy_timeout_ms()
    connection.execute(f"PRAGMA busy_timeout={timeout_ms}")
    if wal:
        connection.execute("PRAGMA journal_mode=WAL")
    if synchronous_normal:
        connection.execute("PRAGMA synchronous=NORMAL")
    if foreign_keys:
        connection.execute("PRAGMA foreign_keys=ON")


def sqlite_connect(database: str | Path, **kwargs: Any) -> sqlite3.Connection:
    """Open a SQLite connection with the app's production-safe defaults."""
    kwargs.setdefault("timeout", sqlite_timeout_seconds())
    connection = sqlite3.connect(database, **kwargs)
    configure_sqlite_connection(connection, wal=True, synchronous_normal=True)
    return connection
