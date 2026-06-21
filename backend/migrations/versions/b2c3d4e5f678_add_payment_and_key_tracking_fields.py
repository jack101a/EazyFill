"""add_payment_and_key_tracking_fields

Revision ID: b2c3d4e5f678
Revises: 94bfa105be00
Create Date: 2026-05-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f678'
down_revision: Union[str, Sequence[str], None] = '94bfa105be00'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── payment_records new columns ─────────────────────────────────────────
    if inspector.has_table("payment_records"):
        payment_columns = {c["name"] for c in inspector.get_columns("payment_records")}
        if "plan_id" not in payment_columns:
            op.add_column('payment_records', sa.Column('plan_id', sa.Integer(), nullable=True))
        if "telegram_user_id" not in payment_columns:
            op.add_column('payment_records', sa.Column('telegram_user_id', sa.String(64), nullable=True))
        if "payment_ref" not in payment_columns:
            op.add_column('payment_records', sa.Column('payment_ref', sa.String(255), nullable=True))
        if "upi_id_used" not in payment_columns:
            op.add_column('payment_records', sa.Column('upi_id_used', sa.String(255), nullable=True))
        if "payee_name_used" not in payment_columns:
            op.add_column('payment_records', sa.Column('payee_name_used', sa.String(255), nullable=True))
        if "ocr_extracted_amount" not in payment_columns:
            op.add_column('payment_records', sa.Column('ocr_extracted_amount', sa.String(64), nullable=True))
        if "ocr_extracted_date" not in payment_columns:
            op.add_column('payment_records', sa.Column('ocr_extracted_date', sa.String(64), nullable=True))
        if "ocr_extracted_payer" not in payment_columns:
            op.add_column('payment_records', sa.Column('ocr_extracted_payer', sa.String(255), nullable=True))
        if "expires_at" not in payment_columns:
            op.add_column('payment_records', sa.Column('expires_at', sa.DateTime(), nullable=True))

    # ── user_api_keys new columns ───────────────────────────────────────────
    if inspector.has_table("user_api_keys"):
        key_columns = {c["name"] for c in inspector.get_columns("user_api_keys")}
        if "last_used_at" not in key_columns:
            op.add_column('user_api_keys', sa.Column('last_used_at', sa.DateTime(), nullable=True))
        if "usage_count" not in key_columns:
            op.add_column('user_api_keys', sa.Column('usage_count', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    # ── payment_records ─────────────────────────────────────────────────────
    op.drop_column('payment_records', 'plan_id')
    op.drop_column('payment_records', 'telegram_user_id')
    op.drop_column('payment_records', 'payment_ref')
    op.drop_column('payment_records', 'upi_id_used')
    op.drop_column('payment_records', 'payee_name_used')
    op.drop_column('payment_records', 'ocr_extracted_amount')
    op.drop_column('payment_records', 'ocr_extracted_date')
    op.drop_column('payment_records', 'ocr_extracted_payer')
    op.drop_column('payment_records', 'expires_at')

    # ── user_api_keys ───────────────────────────────────────────────────────
    op.drop_column('user_api_keys', 'last_used_at')
    op.drop_column('user_api_keys', 'usage_count')
