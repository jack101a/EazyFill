"""add_account_auth_challenges_sessions

Revision ID: 5f6a7b8c9d01
Revises: 4e6f8091a2b3
Create Date: 2026-06-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5f6a7b8c9d01"
down_revision: Union[str, Sequence[str], None] = "4e6f8091a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _has_index(table_name: str, index_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return index_name in {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}


def _create_index(name: str, table_name: str, columns: list[str], *, unique: bool = False) -> None:
    if not _has_index(table_name, name):
        op.create_index(name, table_name, columns, unique=unique)


def upgrade() -> None:
    if not _has_table("user_identities"):
        op.create_table(
            "user_identities",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("identity_type", sa.String(32), nullable=False, server_default="email"),
            sa.Column("identifier", sa.String(255), nullable=False),
            sa.Column("provider", sa.String(64), nullable=False, server_default="email"),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("verified_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("identity_type", "identifier", name="uq_user_identity_identifier"),
        )
    _create_index("ix_user_identities_user_id", "user_identities", ["user_id"])
    _create_index("ix_user_identities_identifier", "user_identities", ["identifier"])

    if not _has_table("auth_challenges"):
        op.create_table(
            "auth_challenges",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("challenge_id", sa.String(128), nullable=False),
            sa.Column("identifier_type", sa.String(32), nullable=False, server_default="email"),
            sa.Column("identifier", sa.String(255), nullable=False),
            sa.Column("account_mode", sa.String(32), nullable=False, server_default="signup"),
            sa.Column("name", sa.String(255), nullable=False, server_default=""),
            sa.Column("plan_code", sa.String(64), nullable=False, server_default="free"),
            sa.Column("otp_hash", sa.String(128), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("consumed_at", sa.DateTime(), nullable=True),
            sa.Column("client_ip", sa.String(45), nullable=True),
            sa.Column("user_agent", sa.String(512), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("challenge_id", name="uq_auth_challenges_challenge_id"),
        )
    _create_index("ix_auth_challenges_challenge_id", "auth_challenges", ["challenge_id"])
    _create_index("ix_auth_challenges_identifier", "auth_challenges", ["identifier"])

    if not _has_table("user_sessions"):
        op.create_table(
            "user_sessions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("api_key_id", sa.Integer(), sa.ForeignKey("user_api_keys.id"), nullable=True),
            sa.Column("session_hash", sa.String(128), nullable=False),
            sa.Column("device_id", sa.String(255), nullable=False),
            sa.Column("device_name", sa.String(255), nullable=True),
            sa.Column("user_agent", sa.String(512), nullable=True),
            sa.Column("ip_address", sa.String(45), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="active"),
            sa.Column("issued_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("revoke_reason", sa.String(255), nullable=True),
            sa.UniqueConstraint("session_hash", name="uq_user_sessions_session_hash"),
        )
    _create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    _create_index("ix_user_sessions_api_key_id", "user_sessions", ["api_key_id"])
    _create_index("ix_user_sessions_device_id", "user_sessions", ["device_id"])


def downgrade() -> None:
    if _has_table("user_sessions"):
        op.drop_table("user_sessions")
    if _has_table("auth_challenges"):
        op.drop_table("auth_challenges")
    if _has_table("user_identities"):
        op.drop_table("user_identities")
