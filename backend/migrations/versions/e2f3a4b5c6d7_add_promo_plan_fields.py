"""add promo plan fields

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-06-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, Sequence[str], None] = "d1e2f3a4b5c6"
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
    if not _has_table("subscription_plans"):
        return
    if not _has_column("subscription_plans", "is_promo"):
        op.add_column(
            "subscription_plans",
            sa.Column("is_promo", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if not _has_column("subscription_plans", "promo_audience"):
        op.add_column(
            "subscription_plans",
            sa.Column("promo_audience", sa.String(length=32), nullable=False, server_default="both"),
        )


def downgrade() -> None:
    if not _has_table("subscription_plans"):
        return
    if _has_column("subscription_plans", "promo_audience"):
        op.drop_column("subscription_plans", "promo_audience")
    if _has_column("subscription_plans", "is_promo"):
        op.drop_column("subscription_plans", "is_promo")
