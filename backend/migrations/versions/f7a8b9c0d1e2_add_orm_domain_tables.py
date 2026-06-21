"""add_orm_domain_tables

Revision ID: f7a8b9c0d1e2
Revises: e6a1c9b2d101
Create Date: 2026-05-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "e6a1c9b2d101"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _has_table("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("full_name", sa.String(255), nullable=False),
            sa.Column("mobile_number", sa.String(20), nullable=True),
            sa.Column("telegram_user_id", sa.String(64), nullable=True),
            sa.Column("telegram_chat_id", sa.String(64), nullable=True),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("created_by_admin_id", sa.Integer(), nullable=True),
            sa.Column("updated_by_admin_id", sa.Integer(), nullable=True),
            sa.UniqueConstraint("mobile_number"),
            sa.UniqueConstraint("telegram_user_id"),
        )

    if not _has_table("subscription_plans"):
        op.create_table(
            "subscription_plans",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("code", sa.String(64), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("monthly_limit", sa.Integer(), nullable=False),
            sa.Column("duration_days", sa.Integer(), nullable=False),
            sa.Column("price_amount", sa.Integer(), nullable=False),
            sa.Column("currency", sa.String(3), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("max_devices", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("allowed_services", sa.JSON(), nullable=True),
            sa.Column("rate_limit_rpm", sa.Integer(), nullable=False, server_default="60"),
            sa.Column("rate_limit_burst", sa.Integer(), nullable=False, server_default="10"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("code"),
        )

    if not _has_table("audit_logs"):
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("actor_type", sa.String(32), nullable=False),
            sa.Column("actor_id", sa.Integer(), nullable=True),
            sa.Column("action", sa.String(128), nullable=False),
            sa.Column("target_type", sa.String(64), nullable=True),
            sa.Column("target_id", sa.Integer(), nullable=True),
            sa.Column("before_json", sa.Text(), nullable=True),
            sa.Column("after_json", sa.Text(), nullable=True),
            sa.Column("ip_address", sa.String(45), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    if not _has_table("backup_runs"):
        op.create_table(
            "backup_runs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("backup_type", sa.String(32), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("storage_target", sa.String(512), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("file_path_or_uri", sa.String(1024), nullable=True),
            sa.Column("checksum", sa.String(128), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
        )

    if not _has_table("user_subscriptions"):
        op.create_table(
            "user_subscriptions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("plan_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("monthly_limit_snapshot", sa.Integer(), nullable=False),
            sa.Column("start_at", sa.DateTime(), nullable=True),
            sa.Column("end_at", sa.DateTime(), nullable=True),
            sa.Column("billing_anchor_day", sa.Integer(), nullable=True),
            sa.Column("current_cycle_start_at", sa.DateTime(), nullable=True),
            sa.Column("current_cycle_end_at", sa.DateTime(), nullable=True),
            sa.Column("auto_renew_enabled", sa.Boolean(), nullable=False),
            sa.Column("approved_by_admin_id", sa.Integer(), nullable=True),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["plan_id"], ["subscription_plans.id"]),
        )
        op.create_index("ix_user_subscriptions_user_id", "user_subscriptions", ["user_id"])

    if not _has_table("user_api_keys"):
        op.create_table(
            "user_api_keys",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("key_hash", sa.String(255), nullable=False),
            sa.Column("key_prefix_display", sa.String(16), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("key_version", sa.Integer(), nullable=False),
            sa.Column("issued_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("last_used_at", sa.DateTime(), nullable=True),
            sa.Column("usage_count", sa.Integer(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_reason", sa.String(255), nullable=True),
            sa.Column("rotated_from_key_id", sa.Integer(), nullable=True),
            sa.Column("created_by_admin_id", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.UniqueConstraint("key_hash"),
        )
        op.create_index("ix_user_api_keys_user_id", "user_api_keys", ["user_id"])

    if not _has_table("request_jobs"):
        op.create_table(
            "request_jobs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("api_key_id", sa.Integer(), nullable=True),
            sa.Column("request_id", sa.String(64), nullable=True),
            sa.Column("job_type", sa.String(64), nullable=False),
            sa.Column("priority", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("payload_ref", sa.String(512), nullable=True),
            sa.Column("result_ref", sa.String(512), nullable=True),
            sa.Column("attempt_count", sa.Integer(), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("queued_at", sa.DateTime(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.UniqueConstraint("request_id"),
        )
        op.create_index("ix_request_jobs_user_id", "request_jobs", ["user_id"])

    if not _has_table("payment_records"):
        op.create_table(
            "payment_records",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("subscription_id", sa.Integer(), nullable=True),
            sa.Column("plan_id", sa.Integer(), nullable=True),
            sa.Column("telegram_user_id", sa.String(64), nullable=True),
            sa.Column("payment_method", sa.String(32), nullable=False),
            sa.Column("amount", sa.Integer(), nullable=False),
            sa.Column("currency", sa.String(3), nullable=False),
            sa.Column("payment_ref", sa.String(255), nullable=True),
            sa.Column("upi_id_used", sa.String(255), nullable=True),
            sa.Column("payee_name_used", sa.String(255), nullable=True),
            sa.Column("upi_reference", sa.String(255), nullable=True),
            sa.Column("payer_name", sa.String(255), nullable=True),
            sa.Column("payment_screenshot_path", sa.String(512), nullable=True),
            sa.Column("payment_note", sa.Text(), nullable=True),
            sa.Column("ocr_matched", sa.Boolean(), nullable=True),
            sa.Column("ocr_extracted_ref", sa.String(255), nullable=True),
            sa.Column("ocr_extracted_amount", sa.String(64), nullable=True),
            sa.Column("ocr_extracted_date", sa.String(64), nullable=True),
            sa.Column("ocr_extracted_payer", sa.String(255), nullable=True),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("submitted_at", sa.DateTime(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("verified_by_admin_id", sa.Integer(), nullable=True),
            sa.Column("verified_at", sa.DateTime(), nullable=True),
            sa.Column("rejection_reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["subscription_id"], ["user_subscriptions.id"]),
            sa.ForeignKeyConstraint(["plan_id"], ["subscription_plans.id"]),
        )
        op.create_index("ix_payment_records_user_id", "payment_records", ["user_id"])

    if not _has_table("user_api_key_devices"):
        op.create_table(
            "user_api_key_devices",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("api_key_id", sa.Integer(), nullable=False),
            sa.Column("device_fingerprint", sa.String(255), nullable=False),
            sa.Column("device_name", sa.String(255), nullable=True),
            sa.Column("user_agent", sa.String(512), nullable=True),
            sa.Column("first_seen_at", sa.DateTime(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.ForeignKeyConstraint(["api_key_id"], ["user_api_keys.id"]),
            sa.UniqueConstraint("api_key_id", "device_fingerprint", name="uq_key_device"),
        )
        op.create_index("ix_user_api_key_devices_api_key_id", "user_api_key_devices", ["api_key_id"])

    if not _has_table("usage_cycles"):
        op.create_table(
            "usage_cycles",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("subscription_id", sa.Integer(), nullable=False),
            sa.Column("cycle_start_at", sa.DateTime(), nullable=False),
            sa.Column("cycle_end_at", sa.DateTime(), nullable=False),
            sa.Column("monthly_limit", sa.Integer(), nullable=False),
            sa.Column("used_count", sa.Integer(), nullable=False),
            sa.Column("blocked_at_limit", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["subscription_id"], ["user_subscriptions.id"]),
        )
        op.create_index("ix_usage_cycles_user_id", "usage_cycles", ["user_id"])


def downgrade() -> None:
    for table in [
        "usage_cycles",
        "user_api_key_devices",
        "payment_records",
        "request_jobs",
        "user_api_keys",
        "user_subscriptions",
        "backup_runs",
        "audit_logs",
        "subscription_plans",
        "users",
    ]:
        op.drop_table(table)
