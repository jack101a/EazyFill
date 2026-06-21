"""add_user_sync_secret

Revision ID: 1a2b3c4d5e6f
Revises: 0f1e2d3c4b5a
Create Date: 2026-06-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "1a2b3c4d5e6f"
down_revision: Union[str, Sequence[str], None] = "0f1e2d3c4b5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _has_column(table_name: str, column_name: str) -> bool:
    if not _has_table(table_name):
        return False
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}
    return column_name in columns


def upgrade() -> None:
    if _has_table("users") and not _has_column("users", "sync_secret"):
        op.add_column("users", sa.Column("sync_secret", sa.String(length=128), nullable=True))


def downgrade() -> None:
    if _has_table("users") and _has_column("users", "sync_secret"):
        op.drop_column("users", "sync_secret")
