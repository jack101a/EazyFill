"""Alembic environment configuration — reads DB URL from project Settings."""

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

# Ensure the backend package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.config import get_settings, _resolve_path
from app.core.sqlite import sqlite_timeout_seconds

# Alembic Config object
config = context.config

# Set up logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Database URL from project settings ────────────────────────────────────────
settings = get_settings()

# Determine dialect from settings (supports SQLite and PostgreSQL)
db_type = os.getenv("DB_TYPE", "sqlite").lower()
if db_type == "postgresql":
    db_url = settings.storage.database_url
    if not db_url:
        raise RuntimeError(
            "PostgreSQL database is not configured. Set DATABASE_URL or "
            "POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, and POSTGRES_PASSWORD."
        )
    # Alembic uses sync driver for migrations
    db_url = db_url.replace("+asyncpg", "+psycopg2")
else:
    db_url = f"sqlite:///{settings.storage.sqlite_path}"

config.set_main_option("sqlalchemy.url", db_url)

# ── Target metadata (populated as domain models are added) ────────────────────
# Import all model bases here for autogenerate support
from app.core.db import Base
from app.core import models  # noqa: F401 — registers all tables with Base.metadata

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generate SQL without connecting)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# Only include tables from our SQLAlchemy metadata (ignore legacy raw-SQL tables)
def _include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table":
        return name in target_metadata.tables
    return True


def run_migrations_online() -> None:
    """Run migrations against the live database."""
    connect_args = {}
    if db_type == "sqlite":
        connect_args["timeout"] = sqlite_timeout_seconds()

    connectable = create_engine(
        config.get_main_option("sqlalchemy.url"),
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )

    # Only include tables from our SQLAlchemy metadata (ignore legacy raw-SQL tables)
    def include_object(obj, name, type_, reflected, compare_to):
        if type_ == "table":
            return name in target_metadata.tables
        return True

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=_include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
