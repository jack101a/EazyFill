"""add_flowpilot_encrypted_backups

Revision ID: 0f1e2d3c4b5a
Revises: f3a4b5c6d7e8
Create Date: 2026-06-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0f1e2d3c4b5a"
down_revision: Union[str, Sequence[str], None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _has_index(table_name: str, index_name: str) -> bool:
    if not _has_table(table_name):
        return False
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}
    return index_name in indexes


def upgrade() -> None:
    if not _has_table("encrypted_backups"):
        op.create_table(
            "encrypted_backups",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("device_id", sa.String(length=255), nullable=False),
            sa.Column("sync_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("encrypted_blob", sa.LargeBinary(), nullable=False),
            sa.Column("blob_hash", sa.String(length=128), nullable=False),
            sa.Column("blob_size_bytes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("user_id", name="uq_encrypted_backups_user"),
        )
    if not _has_index("encrypted_backups", "ix_encrypted_backups_user_id"):
        op.create_index("ix_encrypted_backups_user_id", "encrypted_backups", ["user_id"])


def downgrade() -> None:
    if _has_index("encrypted_backups", "ix_encrypted_backups_user_id"):
        op.drop_index("ix_encrypted_backups_user_id", table_name="encrypted_backups")
    if _has_table("encrypted_backups"):
        op.drop_table("encrypted_backups")
