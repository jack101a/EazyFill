"""allow v2 user-key route learning reporters

Revision ID: 4e6f8091a2b3
Revises: 4d5e6f708192
Create Date: 2026-06-21 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "4e6f8091a2b3"
down_revision = "4d5e6f708192"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _table_exists(table_name: str) -> bool:
    return table_name in _inspector().get_table_names()


def _columns(table_name: str) -> set[str]:
    if not _table_exists(table_name):
        return set()
    return {column["name"] for column in _inspector().get_columns(table_name)}


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _drop_reported_by_foreign_keys(table_name: str) -> None:
    if not _table_exists(table_name):
        return
    for fk in _inspector().get_foreign_keys(table_name):
        constrained = set(fk.get("constrained_columns") or [])
        referred = fk.get("referred_table")
        name = fk.get("name")
        if name and constrained == {"reported_by"} and referred == "api_keys":
            op.drop_constraint(name, table_name, type_="foreignkey")


def _ensure_reporter_columns(table_name: str) -> None:
    if not _table_exists(table_name):
        return
    cols = _columns(table_name)
    if "reported_by_kind" not in cols:
        op.add_column(
            table_name,
            sa.Column(
                "reported_by_kind",
                sa.Text(),
                nullable=False,
                server_default="legacy_api_key",
            ),
        )
    if "reported_by_user_id" not in cols:
        op.add_column(table_name, sa.Column("reported_by_user_id", sa.Integer(), nullable=True))
    if "reported_by" in cols:
        if _is_sqlite():
            with op.batch_alter_table(table_name) as batch_op:
                batch_op.alter_column("reported_by", existing_type=sa.Integer(), nullable=True)
        else:
            op.alter_column(table_name, "reported_by", existing_type=sa.Integer(), nullable=True)


def upgrade() -> None:
    for table_name in ("field_mapping_proposals", "retrain_samples"):
        _drop_reported_by_foreign_keys(table_name)
        _ensure_reporter_columns(table_name)


def downgrade() -> None:
    for table_name in ("field_mapping_proposals", "retrain_samples"):
        if not _table_exists(table_name):
            continue
        cols = _columns(table_name)
        if "reported_by_user_id" in cols:
            op.drop_column(table_name, "reported_by_user_id")
        if "reported_by_kind" in cols:
            op.drop_column(table_name, "reported_by_kind")
