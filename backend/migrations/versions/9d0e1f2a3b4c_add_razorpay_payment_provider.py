"""add razorpay payment provider

Revision ID: 9d0e1f2a3b4c
Revises: f7a8b9c0d1e2
Create Date: 2026-06-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9d0e1f2a3b4c"
down_revision: Union[str, Sequence[str], None] = "b5d6e7f8a901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _has_column(table_name: str, column_name: str) -> bool:
    if not _has_table(table_name):
        return False
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}
    return column_name in columns


def _has_index(table_name: str, index_name: str) -> bool:
    if not _has_table(table_name):
        return False
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}
    return index_name in indexes


def upgrade() -> None:
    if _has_table("payment_records"):
        with op.batch_alter_table("payment_records") as batch_op:
            if not _has_column("payment_records", "payment_provider"):
                batch_op.add_column(sa.Column("payment_provider", sa.String(32), nullable=False, server_default="manual_upi"))
            if not _has_column("payment_records", "provider_order_id"):
                batch_op.add_column(sa.Column("provider_order_id", sa.String(255), nullable=True))
            if not _has_column("payment_records", "provider_payment_id"):
                batch_op.add_column(sa.Column("provider_payment_id", sa.String(255), nullable=True))
            if not _has_column("payment_records", "provider_signature"):
                batch_op.add_column(sa.Column("provider_signature", sa.String(255), nullable=True))
            if not _has_column("payment_records", "provider_status"):
                batch_op.add_column(sa.Column("provider_status", sa.String(64), nullable=True))
            if not _has_column("payment_records", "provider_payload_json"):
                batch_op.add_column(sa.Column("provider_payload_json", sa.Text(), nullable=True))

        if not _has_index("payment_records", "uq_payment_records_provider_order_id"):
            op.create_index(
                "uq_payment_records_provider_order_id",
                "payment_records",
                ["provider_order_id"],
                unique=True,
            )
        if not _has_index("payment_records", "uq_payment_records_provider_payment_id"):
            op.create_index(
                "uq_payment_records_provider_payment_id",
                "payment_records",
                ["provider_payment_id"],
                unique=True,
            )

    if not _has_table("payment_webhook_events"):
        op.create_table(
            "payment_webhook_events",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("provider", sa.String(32), nullable=False),
            sa.Column("event_id", sa.String(255), nullable=False),
            sa.Column("event_type", sa.String(128), nullable=False, server_default=""),
            sa.Column("payment_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="received"),
            sa.Column("payload_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("received_at", sa.DateTime(), nullable=False),
            sa.Column("processed_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["payment_id"], ["payment_records.id"]),
            sa.UniqueConstraint("event_id"),
        )
        op.create_index("ix_payment_webhook_events_payment_id", "payment_webhook_events", ["payment_id"])


def downgrade() -> None:
    if _has_table("payment_webhook_events"):
        op.drop_table("payment_webhook_events")

    if _has_table("payment_records"):
        if _has_index("payment_records", "uq_payment_records_provider_payment_id"):
            op.drop_index("uq_payment_records_provider_payment_id", table_name="payment_records")
        if _has_index("payment_records", "uq_payment_records_provider_order_id"):
            op.drop_index("uq_payment_records_provider_order_id", table_name="payment_records")
        with op.batch_alter_table("payment_records") as batch_op:
            for column_name in [
                "provider_payload_json",
                "provider_status",
                "provider_signature",
                "provider_payment_id",
                "provider_order_id",
                "payment_provider",
            ]:
                if _has_column("payment_records", column_name):
                    batch_op.drop_column(column_name)
