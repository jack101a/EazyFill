"""full_schema_baseline

Revision ID: e6a1c9b2d101
Revises: c3f4a9d8e2b1
Create Date: 2026-05-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e6a1c9b2d101"
down_revision: Union[str, Sequence[str], None] = "c3f4a9d8e2b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _has_index(table_name: str, index_name: str) -> bool:
    if not _has_table(table_name):
        return False
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}
    return index_name in indexes


def _create_table(name: str, *columns, **kwargs) -> None:
    if not _has_table(name):
        op.create_table(name, *columns, **kwargs)


def _create_index(name: str, table_name: str, columns: list[str]) -> None:
    if not _has_index(table_name, name):
        op.create_index(name, table_name, columns)


def _ensure_global_access() -> None:
    bind = op.get_bind()
    row = bind.execute(
        sa.text("SELECT 1 FROM access_control WHERE key = :key"),
        {"key": "global_access"},
    ).fetchone()
    if not row:
        bind.execute(
            sa.text("INSERT INTO access_control (key, value) VALUES (:key, :value)"),
            {"key": "global_access", "value": "true"},
        )


def upgrade() -> None:
    _create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("enabled", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("all_domains", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=True),
        sa.Column("revoked_at", sa.Text(), nullable=True),
        sa.Column("last_used_at", sa.Text(), nullable=True),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("key_type", sa.Text(), nullable=False, server_default="user"),
        sa.Column("plan_name", sa.Text(), nullable=False, server_default="Standard"),
        sa.Column("mobile", sa.Text(), nullable=False, server_default=""),
        sa.Column("telegram_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("services_json", sa.Text(), nullable=False, server_default="{}"),
    )
    _create_table(
        "api_key_allowed_domains",
        sa.Column("key_id", sa.Integer(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("key_id", "domain"),
        sa.ForeignKeyConstraint(["key_id"], ["api_keys.id"]),
    )
    _create_table(
        "api_key_rate_limits",
        sa.Column("key_id", sa.Integer(), primary_key=True),
        sa.Column("requests_per_minute", sa.Integer(), nullable=False),
        sa.Column("burst", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["key_id"], ["api_keys.id"]),
    )
    _create_table(
        "api_key_device_bindings",
        sa.Column("key_id", sa.Integer(), primary_key=True),
        sa.Column("device_id", sa.Text(), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.Text(), nullable=False),
        sa.Column("last_seen_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["key_id"], ["api_keys.id"]),
    )
    _create_table(
        "usage_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key_id", sa.Integer(), nullable=False),
        sa.Column("task_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("processing_ms", sa.Integer(), nullable=False),
        sa.Column("model_used", sa.Text(), nullable=True),
        sa.Column("domain", sa.Text(), nullable=True),
        sa.Column("ip", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["key_id"], ["api_keys.id"]),
    )
    _create_table(
        "model_routes",
        sa.Column("domain", sa.Text(), primary_key=True),
        sa.Column("ai_model_filename", sa.Text(), nullable=False),
    )
    _create_table(
        "model_registry",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ai_model_name", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("task_type", sa.Text(), nullable=False),
        sa.Column("ai_runtime", sa.Text(), nullable=False, server_default="onnx"),
        sa.Column("ai_model_filename", sa.Text(), nullable=False, unique=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("lifecycle_state", sa.Text(), nullable=False, server_default="production"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    _create_table(
        "field_mappings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("field_name", sa.Text(), nullable=False),
        sa.Column("task_type", sa.Text(), nullable=False),
        sa.Column("source_data_type", sa.Text(), nullable=False, server_default="image"),
        sa.Column("source_selector", sa.Text(), nullable=False, server_default=""),
        sa.Column("target_data_type", sa.Text(), nullable=False, server_default="text"),
        sa.Column("target_selector", sa.Text(), nullable=False, server_default=""),
        sa.Column("ai_model_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("domain", "field_name", "task_type"),
        sa.ForeignKeyConstraint(["ai_model_id"], ["model_registry.id"]),
    )
    _create_table(
        "field_mapping_proposals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("task_type", sa.Text(), nullable=False),
        sa.Column("source_data_type", sa.Text(), nullable=False),
        sa.Column("source_selector", sa.Text(), nullable=False),
        sa.Column("target_data_type", sa.Text(), nullable=False),
        sa.Column("target_selector", sa.Text(), nullable=False),
        sa.Column("proposed_field_name", sa.Text(), nullable=False),
        sa.Column("reported_by", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["reported_by"], ["api_keys.id"]),
    )
    _create_table(
        "retrain_samples",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("image_path", sa.Text(), nullable=False),
        sa.Column("task_type", sa.Text(), nullable=False, server_default="image"),
        sa.Column("field_name", sa.Text(), nullable=True),
        sa.Column("reported_by", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("label_text", sa.Text(), nullable=True),
        sa.Column("labeled_by", sa.Integer(), nullable=True),
        sa.Column("labeled_at", sa.Text(), nullable=True),
        sa.Column("consumed_by_job_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["reported_by"], ["api_keys.id"]),
    )
    _create_table(
        "retrain_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("scheduled_for", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.Integer(), nullable=True),
        sa.Column("min_samples", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("produced_ai_model_id", sa.Integer(), nullable=True),
        sa.Column("total_samples", sa.Integer(), nullable=False, server_default="0"),
    )
    _create_table(
        "model_lifecycle_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ai_model_id", sa.Integer(), nullable=False),
        sa.Column("from_state", sa.Text(), nullable=True),
        sa.Column("to_state", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["ai_model_id"], ["model_registry.id"]),
    )
    _create_table(
        "active_learning",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("image_path", sa.Text(), nullable=False),
        sa.Column("reported_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["reported_by"], ["api_keys.id"]),
    )
    _create_table(
        "access_control",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
    )
    _create_table(
        "allowed_domains",
        sa.Column("domain", sa.Text(), primary_key=True),
    )
    _create_table(
        "locators",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("image_selector", sa.Text(), nullable=False),
        sa.Column("input_selector", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    _create_table(
        "failed_payload_labels",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("filename", sa.Text(), nullable=False, unique=True),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("ai_guess", sa.Text(), nullable=True),
        sa.Column("corrected_text", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    _create_table(
        "platform_settings",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    _create_table(
        "autofill_rule_proposals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True, unique=True),
        sa.Column("device_id", sa.Text(), nullable=True),
        sa.Column("api_key_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("reviewed_by", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.Text(), nullable=True),
        sa.Column("rule_json", sa.Text(), nullable=False),
        sa.Column("approved_rule_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    _create_table(
        "exam_attempts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("question_hash", sa.Text(), nullable=False),
        sa.Column("selected_option", sa.Integer(), nullable=False),
        sa.Column("was_correct", sa.Integer(), nullable=False),
        sa.Column("method", sa.Text(), nullable=True),
        sa.Column("processing_ms", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("domain", sa.Text(), nullable=True),
        sa.Column("question_num", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    _create_table(
        "exam_learned",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("cluster_id", sa.Integer(), nullable=True),
        sa.Column("question_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("question_phash", sa.Text(), nullable=False, server_default=""),
        sa.Column("question_text", sa.Text(), nullable=True, server_default=""),
        sa.Column("option_1", sa.Text(), nullable=True, server_default=""),
        sa.Column("option_2", sa.Text(), nullable=True, server_default=""),
        sa.Column("option_3", sa.Text(), nullable=True, server_default=""),
        sa.Column("option_4", sa.Text(), nullable=True, server_default=""),
        sa.Column("correct_option", sa.Integer(), nullable=False),
        sa.Column("correct_option_hash", sa.Text(), nullable=False, server_default=""),
        sa.Column("correct_option_phash", sa.Text(), nullable=False, server_default=""),
        sa.Column("correct_option_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.8"),
        sa.Column("seen_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_seen", sa.Text(), nullable=False),
        sa.Column("last_seen", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False, server_default="exam_feedback"),
        sa.Column("learning_mode", sa.Text(), nullable=False, server_default="hash_based"),
        sa.Column("ocr_quality", sa.Text(), nullable=False, server_default="unverified"),
        sa.Column("ocr_preview_unreliable", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("verified_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("wrong_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_verified_at", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="training"),
    )
    _create_table(
        "exam_learned_clusters",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("canonical_question_hash", sa.Text(), nullable=False, server_default=""),
        sa.Column("canonical_question_phash", sa.Text(), nullable=False, server_default=""),
        sa.Column("question_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("question_text_norm", sa.Text(), nullable=False, server_default=""),
        sa.Column("option_signature", sa.Text(), nullable=False, server_default=""),
        sa.Column("correct_option_hash", sa.Text(), nullable=False, server_default=""),
        sa.Column("correct_option_phash", sa.Text(), nullable=False, server_default=""),
        sa.Column("correct_option_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("correct_option_text_norm", sa.Text(), nullable=False, server_default=""),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.8"),
        sa.Column("seen_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("verified_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("wrong_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("variant_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("conflict_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.Text(), nullable=False, server_default="training"),
        sa.Column("first_seen", sa.Text(), nullable=False),
        sa.Column("last_seen", sa.Text(), nullable=False),
        sa.Column("last_verified_at", sa.Text(), nullable=True),
    )
    _create_table(
        "automation_methods",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("method_type", sa.Text(), nullable=False, server_default="stall-flow"),
        sa.Column("enabled", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("active", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )

    _create_index("idx_usage_task_status", "usage_events", ["task_type", "status"])
    _create_index("idx_usage_key_id", "usage_events", ["key_id"])
    _create_index("idx_usage_task_created", "usage_events", ["task_type", "created_at"])
    _create_index("idx_field_proposals_status", "field_mapping_proposals", ["status"])
    _create_index("idx_autofill_proposals_status", "autofill_rule_proposals", ["status", "created_at"])
    _create_index("idx_exam_learned_phash", "exam_learned", ["question_phash"])
    _create_index("idx_exam_learned_cluster_id", "exam_learned", ["cluster_id"])
    _create_index("idx_exam_learned_clusters_phash", "exam_learned_clusters", ["canonical_question_phash"])
    _create_index("idx_exam_learned_clusters_status", "exam_learned_clusters", ["status"])

    _ensure_global_access()


def downgrade() -> None:
    for table in [
        "automation_methods",
        "exam_learned_clusters",
        "exam_learned",
        "exam_attempts",
        "autofill_rule_proposals",
        "platform_settings",
        "failed_payload_labels",
        "locators",
        "allowed_domains",
        "access_control",
        "active_learning",
        "model_lifecycle_events",
        "retrain_jobs",
        "retrain_samples",
        "field_mapping_proposals",
        "field_mappings",
        "model_registry",
        "model_routes",
        "usage_events",
        "api_key_device_bindings",
        "api_key_rate_limits",
        "api_key_allowed_domains",
        "api_keys",
    ]:
        if _has_table(table):
            op.drop_table(table)
