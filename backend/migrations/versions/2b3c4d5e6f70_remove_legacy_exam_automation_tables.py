"""remove legacy exam and automation tables

Revision ID: 2b3c4d5e6f70
Revises: 1a2b3c4d5e6f
Create Date: 2026-06-16 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2b3c4d5e6f70"
down_revision: Union[str, Sequence[str], None] = "1a2b3c4d5e6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LEGACY_TABLES = (
    "exam_workflow_usage",
    "automation_methods",
    "exam_learned_clusters",
    "exam_learned",
    "exam_attempts",
    "autofill_rule_proposals",
    "locators",
)


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    for table_name in LEGACY_TABLES:
        if _has_table(table_name):
            op.drop_table(table_name)


def downgrade() -> None:
    # Destructive cleanup migration. Historical migrations contain the previous
    # table definitions if a full rollback is needed.
    pass
