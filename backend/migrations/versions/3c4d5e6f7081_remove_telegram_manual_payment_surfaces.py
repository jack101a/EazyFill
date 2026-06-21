"""remove telegram and manual payment surfaces

Revision ID: 3c4d5e6f7081
Revises: 2b3c4d5e6f70
Create Date: 2026-06-16 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "3c4d5e6f7081"
down_revision = "2b3c4d5e6f70"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _drop_existing_columns(table_name: str, column_names: list[str]) -> None:
    if not _table_exists(table_name):
        return
    existing = _columns(table_name)
    drop_names = [name for name in column_names if name in existing]
    if not drop_names:
        return
    with op.batch_alter_table(table_name) as batch_op:
        for name in drop_names:
            batch_op.drop_column(name)


def upgrade() -> None:
    _drop_existing_columns("users", ["telegram_user_id", "telegram_chat_id"])
    _drop_existing_columns("api_keys", ["telegram_id"])

    if _table_exists("subscription_plans"):
        existing = _columns("subscription_plans")
        with op.batch_alter_table("subscription_plans") as batch_op:
            if "show_in_bot" in existing and "show_in_checkout" not in existing:
                batch_op.alter_column(
                    "show_in_bot",
                    new_column_name="show_in_checkout",
                    existing_type=sa.Boolean(),
                    existing_nullable=False,
                )
            elif "show_in_checkout" not in existing:
                batch_op.add_column(
                    sa.Column("show_in_checkout", sa.Boolean(), nullable=False, server_default=sa.true())
                )

    _drop_existing_columns(
        "payment_records",
        [
            "telegram_user_id",
            "upi_id_used",
            "payee_name_used",
            "upi_reference",
            "payer_name",
            "payment_screenshot_path",
            "ocr_matched",
            "ocr_extracted_ref",
            "ocr_extracted_amount",
            "ocr_extracted_date",
            "ocr_extracted_payer",
        ],
    )

    if _table_exists("platform_settings"):
        op.execute(
            """
            DELETE FROM platform_settings
            WHERE key LIKE 'telegram.%'
               OR key LIKE 'backup.telegram_%'
               OR key = 'payment.upi_id'
               OR key = 'payment.qr_image_url'
               OR key LIKE 'payment.qr_image_url_plan_%'
            """
        )


def downgrade() -> None:
    if _table_exists("subscription_plans"):
        existing = _columns("subscription_plans")
        with op.batch_alter_table("subscription_plans") as batch_op:
            if "show_in_checkout" in existing and "show_in_bot" not in existing:
                batch_op.alter_column(
                    "show_in_checkout",
                    new_column_name="show_in_bot",
                    existing_type=sa.Boolean(),
                    existing_nullable=False,
                )

    if _table_exists("users"):
        existing = _columns("users")
        with op.batch_alter_table("users") as batch_op:
            if "telegram_user_id" not in existing:
                batch_op.add_column(sa.Column("telegram_user_id", sa.String(64), nullable=True))
            if "telegram_chat_id" not in existing:
                batch_op.add_column(sa.Column("telegram_chat_id", sa.String(64), nullable=True))

    if _table_exists("api_keys") and "telegram_id" not in _columns("api_keys"):
        with op.batch_alter_table("api_keys") as batch_op:
            batch_op.add_column(sa.Column("telegram_id", sa.Text(), nullable=False, server_default=""))

    if _table_exists("payment_records"):
        existing = _columns("payment_records")
        with op.batch_alter_table("payment_records") as batch_op:
            for name, column_type in [
                ("telegram_user_id", sa.String(64)),
                ("upi_id_used", sa.String(255)),
                ("payee_name_used", sa.String(255)),
                ("upi_reference", sa.String(255)),
                ("payer_name", sa.String(255)),
                ("payment_screenshot_path", sa.String(512)),
                ("ocr_matched", sa.Boolean()),
                ("ocr_extracted_ref", sa.String(255)),
                ("ocr_extracted_amount", sa.String(64)),
                ("ocr_extracted_date", sa.String(64)),
                ("ocr_extracted_payer", sa.String(255)),
            ]:
                if name not in existing:
                    batch_op.add_column(sa.Column(name, column_type, nullable=True))
