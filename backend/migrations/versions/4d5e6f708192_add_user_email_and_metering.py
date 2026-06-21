"""add user email and backend metering policies

Revision ID: 4d5e6f708192
Revises: 3c4d5e6f7081
Create Date: 2026-06-20 00:00:00.000000
"""

from __future__ import annotations

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "4d5e6f708192"
down_revision = "3c4d5e6f7081"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {index["name"] for index in inspector.get_indexes(table_name)}


def _create_index_if_missing(name: str, table_name: str, columns: list[str], *, unique: bool = False) -> None:
    if not _table_exists(table_name) or name in _index_names(table_name):
        return
    op.create_index(name, table_name, columns, unique=unique)


def upgrade() -> None:
    if _table_exists("users"):
        existing = _columns("users")
        with op.batch_alter_table("users") as batch_op:
            if "email" not in existing:
                batch_op.add_column(sa.Column("email", sa.String(255), nullable=True))
            if "email_verified_at" not in existing:
                batch_op.add_column(sa.Column("email_verified_at", sa.DateTime(), nullable=True))
            if "last_login_at" not in existing:
                batch_op.add_column(sa.Column("last_login_at", sa.DateTime(), nullable=True))
        _create_index_if_missing("ix_users_email", "users", ["email"], unique=True)

    if not _table_exists("metering_policies"):
        op.create_table(
            "metering_policies",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("event_type", sa.String(128), nullable=False),
            sa.Column("display_name", sa.String(255), nullable=False),
            sa.Column("unit_cost", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("event_type", name="uq_metering_policies_event_type"),
        )
        op.create_index("ix_metering_policies_event_type", "metering_policies", ["event_type"])

    if not _table_exists("credit_ledger_entries"):
        op.create_table(
            "credit_ledger_entries",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("subscription_id", sa.Integer(), nullable=True),
            sa.Column("cycle_id", sa.Integer(), nullable=True),
            sa.Column("event_type", sa.String(128), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="reserved"),
            sa.Column("credit_delta", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("unit_cost", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("amount", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("idempotency_key", sa.String(128), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["cycle_id"], ["usage_cycles.id"]),
            sa.ForeignKeyConstraint(["subscription_id"], ["user_subscriptions.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("idempotency_key", name="uq_credit_ledger_entries_idempotency_key"),
        )
        op.create_index("ix_credit_ledger_entries_cycle_id", "credit_ledger_entries", ["cycle_id"])
        op.create_index("ix_credit_ledger_entries_event_type", "credit_ledger_entries", ["event_type"])
        op.create_index("ix_credit_ledger_entries_subscription_id", "credit_ledger_entries", ["subscription_id"])
        op.create_index("ix_credit_ledger_entries_user_id", "credit_ledger_entries", ["user_id"])

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    op.get_bind().execute(
        sa.text(
            """
            INSERT INTO metering_policies
                (event_type, display_name, unit_cost, is_active, metadata_json, created_at, updated_at)
            SELECT
                :event_type, :display_name, :unit_cost, :is_active, NULL, :created_at, :updated_at
            WHERE NOT EXISTS (
                SELECT 1 FROM metering_policies WHERE event_type = :event_type
            )
            """
        ),
        {
            "event_type": "captcha.solve.image",
            "display_name": "Image CAPTCHA solve",
            "unit_cost": 1,
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        },
    )


def downgrade() -> None:
    if _table_exists("credit_ledger_entries"):
        op.drop_table("credit_ledger_entries")
    if _table_exists("metering_policies"):
        op.drop_table("metering_policies")
    if _table_exists("users"):
        existing = _columns("users")
        if "ix_users_email" in _index_names("users"):
            op.drop_index("ix_users_email", table_name="users")
        with op.batch_alter_table("users") as batch_op:
            if "last_login_at" in existing:
                batch_op.drop_column("last_login_at")
            if "email_verified_at" in existing:
                batch_op.drop_column("email_verified_at")
            if "email" in existing:
                batch_op.drop_column("email")
