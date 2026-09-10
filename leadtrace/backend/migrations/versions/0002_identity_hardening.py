"""Harden existing sessions and login throttling.

Revision ID: 0002_identity_hardening
Revises: 0001_identity
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_identity_hardening"
down_revision = "0001_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "auth_sessions",
        sa.Column("reauthenticated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE auth_sessions
        SET revoked_at = now(), revocation_reason = 'identity_hardening'
        WHERE revoked_at IS NULL
        """
    )
    op.execute(
        """
        UPDATE auth_sessions
        SET reauthenticated_at = created_at
        WHERE reauthenticated_at IS NULL
        """
    )
    op.alter_column(
        "auth_sessions",
        "reauthenticated_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )

    op.add_column(
        "login_attempts",
        sa.Column("source_hash", sa.String(length=64), nullable=True),
    )
    op.execute("DELETE FROM login_attempts")
    op.alter_column(
        "login_attempts",
        "source_hash",
        existing_type=sa.String(length=64),
        nullable=False,
    )
    op.drop_index("ix_login_attempts_rate_limit", table_name="login_attempts")
    op.create_index(
        "ix_login_attempts_identity_time",
        "login_attempts",
        ["identity_hash", "attempted_at"],
    )
    op.create_index(
        "ix_login_attempts_source_time",
        "login_attempts",
        ["source_hash", "attempted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_login_attempts_source_time", table_name="login_attempts")
    op.drop_index("ix_login_attempts_identity_time", table_name="login_attempts")
    op.create_index(
        "ix_login_attempts_rate_limit",
        "login_attempts",
        ["identity_hash", "remote_address", "attempted_at"],
    )
    op.drop_column("login_attempts", "source_hash")
    op.drop_column("auth_sessions", "reauthenticated_at")
