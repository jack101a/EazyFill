"""remove legacy CallMeBot settings

Revision ID: b5d6e7f8a901
Revises: a4b5c6d7e8f9
Create Date: 2026-05-31 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b5d6e7f8a901"
down_revision: Union[str, Sequence[str], None] = "a4b5c6d7e8f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return name in inspector.get_table_names()


def upgrade() -> None:
    if not _has_table("platform_settings"):
        return
    op.execute(
        sa.text(
            """
            DELETE FROM platform_settings
            WHERE key IN (
                'alerts.whatsapp_enabled',
                'alerts.callmebot_phone',
                'alerts.callmebot_apikey'
            )
            """
        )
    )


def downgrade() -> None:
    # Removed integration settings are intentionally not restored.
    return
