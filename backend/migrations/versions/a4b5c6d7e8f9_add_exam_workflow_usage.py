"""add exam workflow usage table

Revision ID: a4b5c6d7e8f9
Revises: f7a8b9c0d1e2
Create Date: 2026-05-20 10:20:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a4b5c6d7e8f9"
down_revision: Union[str, Sequence[str], None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return name in inspector.get_table_names()


def upgrade() -> None:
    if _has_table("exam_workflow_usage"):
        return
    op.create_table(
        "exam_workflow_usage",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.String(length=64), nullable=False),
        sa.Column("usage_date", sa.String(length=10), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=True),
        sa.Column("question_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.UniqueConstraint("workflow_id", name="uq_exam_workflow_usage_workflow_id"),
    )
    op.create_index("ix_exam_workflow_usage_user_id", "exam_workflow_usage", ["user_id"])
    op.create_index("ix_exam_workflow_usage_usage_date", "exam_workflow_usage", ["usage_date"])


def downgrade() -> None:
    if _has_table("exam_workflow_usage"):
        op.drop_table("exam_workflow_usage")
