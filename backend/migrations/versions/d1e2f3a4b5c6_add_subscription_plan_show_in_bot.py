"""add subscription plan show_in_bot flag

Revision ID: d1e2f3a4b5c6
Revises: 9d0e1f2a3b4c
Create Date: 2026-06-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "9d0e1f2a3b4c"
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
    if _has_table("subscription_plans") and not _has_column("subscription_plans", "show_in_bot"):
        op.add_column(
            "subscription_plans",
            sa.Column("show_in_bot", sa.Boolean(), nullable=False, server_default=sa.true()),
        )


def downgrade() -> None:
    if _has_table("subscription_plans") and _has_column("subscription_plans", "show_in_bot"):
        op.drop_column("subscription_plans", "show_in_bot")
