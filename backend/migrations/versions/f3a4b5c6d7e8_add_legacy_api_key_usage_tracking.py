"""add legacy api key usage tracking

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-06-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, Sequence[str], None] = "e2f3a4b5c6d7"
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
    if not _has_table("api_keys"):
        return
    if not _has_column("api_keys", "last_used_at"):
        op.add_column("api_keys", sa.Column("last_used_at", sa.Text(), nullable=True))
    if not _has_column("api_keys", "usage_count"):
        op.add_column(
            "api_keys",
            sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    if not _has_table("api_keys"):
        return
    if _has_column("api_keys", "usage_count"):
        op.drop_column("api_keys", "usage_count")
    if _has_column("api_keys", "last_used_at"):
        op.drop_column("api_keys", "last_used_at")
