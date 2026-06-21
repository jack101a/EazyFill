"""Database engine and session factory — supports SQLite and PostgreSQL.

This module provides the SQLAlchemy engine and session management for
the new domain models (users, subscriptions, payments, etc.).
It coexists with the existing raw-SQL Database facade for legacy tables.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker, declarative_base

from app.core.config import Settings
from app.core.sqlite import configure_sqlite_connection, sqlite_timeout_seconds

# Declarative base for all new domain models
Base = declarative_base()

# Module-level singletons
_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _build_sqlite_url(db_path: str) -> str:
    """Build SQLite URL with WAL mode for better concurrency."""
    path = Path(db_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path}"


def _build_postgresql_url(database_url: str) -> str:
    """Ensure the URL uses a sync driver for migrations/sessions."""
    if "+asyncpg" in database_url:
        return database_url.replace("+asyncpg", "+psycopg2")
    if not database_url.startswith("postgresql"):
        return f"postgresql+psycopg2://{database_url}"
    return database_url


def init_db(settings: Settings) -> Engine:
    """Initialize the database engine and session factory.

    Called once at application startup. Returns the engine.
    """
    global _engine, _SessionLocal

    db_type = settings.storage.db_type
    if db_type == "postgresql":
        if not settings.storage.database_url:
            raise RuntimeError(
                "PostgreSQL database is not configured. Set DATABASE_URL or "
                "POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, and POSTGRES_PASSWORD."
            )
        url = _build_postgresql_url(settings.storage.database_url)
    else:
        url = _build_sqlite_url(settings.storage.sqlite_path)

    connect_args = {}
    if db_type == "sqlite":
        connect_args["check_same_thread"] = False
        connect_args["timeout"] = sqlite_timeout_seconds()

    _engine = create_engine(
        url,
        echo=settings.server.debug,
        connect_args=connect_args,
        pool_pre_ping=True,
    )

    # Enable WAL mode and foreign keys for SQLite
    if db_type == "sqlite":

        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):
            configure_sqlite_connection(
                dbapi_connection,
                wal=True,
                foreign_keys=True,
                synchronous_normal=True,
            )

    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

    return _engine


def get_session() -> Session:
    """Get a new database session. Must be closed by caller."""
    if _SessionLocal is None:
        raise RuntimeError("Database not initialized — call init_db() first")
    return _SessionLocal()


def get_engine() -> Engine:
    """Get the current database engine."""
    if _engine is None:
        raise RuntimeError("Database not initialized — call init_db() first")
    return _engine


def create_all_tables() -> None:
    """Create all tables defined in SQLAlchemy models (dev convenience)."""
    if _engine is None:
        raise RuntimeError("Database not initialized")
    Base.metadata.create_all(bind=_engine)


def drop_all_tables() -> None:
    """Drop all tables (DANGER — dev only)."""
    if _engine is None:
        raise RuntimeError("Database not initialized")
    Base.metadata.drop_all(bind=_engine)
