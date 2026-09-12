"""persist job recovery and maintenance state

Revision ID: 0014_job_recovery_maintenance
Revises: 0013_approvals
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0014_job_recovery_maintenance"
down_revision: str | None = "0013_approvals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "crop_jobs",
        sa.Column("dispatch_token", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "crop_jobs",
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "crop_jobs",
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "crop_jobs",
        sa.Column(
            "max_attempts",
            sa.Integer(),
            server_default=sa.text("3"),
            nullable=False,
        ),
    )
    op.add_column(
        "crop_jobs",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "crop_jobs",
        sa.Column(
            "superseded_by_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_crop_jobs_superseded_by",
        "crop_jobs",
        "crop_jobs",
        ["superseded_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_crop_jobs_nonnegative_attempts",
        "crop_jobs",
        "attempt_count >= 0",
    )
    op.create_check_constraint(
        "ck_crop_jobs_positive_max_attempts",
        "crop_jobs",
        "max_attempts > 0",
    )
    op.create_index(
        "ix_crop_jobs_status_dispatch",
        "crop_jobs",
        ["status", "dispatched_at"],
    )
    op.create_index(
        "ix_crop_jobs_status_heartbeat",
        "crop_jobs",
        ["status", "heartbeat_at"],
    )

    op.create_table(
        "crop_job_attempts",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column(
            "delivery_token", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "status",
            sa.Enum(
                "running",
                "completed",
                "failed",
                "stale",
                name="crop_job_attempt_status",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "attempt_number > 0",
            name="ck_crop_job_attempts_positive_number",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["crop_jobs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "delivery_token", name="uq_crop_job_attempts_delivery_token"
        ),
        sa.UniqueConstraint(
            "job_id",
            "attempt_number",
            name="uq_crop_job_attempts_number",
        ),
    )
    op.create_index(
        "ix_crop_job_attempts_job_status",
        "crop_job_attempts",
        ["job_id", "status"],
    )

    op.create_table(
        "crop_job_retry_operations",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("attempt_count_before", sa.Integer(), nullable=False),
        sa.Column("max_attempts_after", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "attempt_count_before >= 0",
            name="ck_crop_job_retry_operations_attempt_count",
        ),
        sa.CheckConstraint(
            "max_attempts_after > attempt_count_before",
            name="ck_crop_job_retry_operations_budget",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["crop_jobs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id",
            "actor_id",
            "idempotency_key",
            name="uq_crop_job_retry_operations_key",
        ),
    )
    op.create_index(
        "ix_crop_job_retry_operations_job",
        "crop_job_retry_operations",
        ["job_id", "created_at"],
    )

    op.create_table(
        "maintenance_windows",
        sa.Column("active_slot", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expected_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "started_by_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ended_reason", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "active_slot IS NULL OR active_slot = 1",
            name="ck_maintenance_windows_active_slot",
        ),
        sa.CheckConstraint(
            "expected_end_at > started_at",
            name="ck_maintenance_windows_expected_end",
        ),
        sa.CheckConstraint(
            "(ended_at IS NULL AND ended_by_id IS NULL AND ended_reason IS NULL "
            "AND active_slot = 1) OR "
            "(ended_at IS NOT NULL AND ended_by_id IS NOT NULL "
            "AND ended_reason IS NOT NULL AND active_slot IS NULL)",
            name="ck_maintenance_windows_lifecycle",
        ),
        sa.ForeignKeyConstraint(
            ["ended_by_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["started_by_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "active_slot", name="uq_maintenance_windows_active_slot"
        ),
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE crop_jobs
            SET status = 'failed',
                error_message = CASE
                    WHEN error_message IS NULL OR btrim(error_message) = ''
                        THEN 'Superseded work mapped to failed during Task 23 rollback'
                    ELSE error_message || '; mapped to failed during Task 23 rollback'
                END
            WHERE status = 'superseded'
            """
        )
    )
    op.drop_table("maintenance_windows")
    op.drop_index(
        "ix_crop_job_retry_operations_job",
        table_name="crop_job_retry_operations",
    )
    op.drop_table("crop_job_retry_operations")
    op.drop_index(
        "ix_crop_job_attempts_job_status", table_name="crop_job_attempts"
    )
    op.drop_table("crop_job_attempts")
    op.drop_index("ix_crop_jobs_status_heartbeat", table_name="crop_jobs")
    op.drop_index("ix_crop_jobs_status_dispatch", table_name="crop_jobs")
    op.drop_constraint(
        "ck_crop_jobs_positive_max_attempts", "crop_jobs", type_="check"
    )
    op.drop_constraint(
        "ck_crop_jobs_nonnegative_attempts", "crop_jobs", type_="check"
    )
    op.drop_constraint(
        "fk_crop_jobs_superseded_by", "crop_jobs", type_="foreignkey"
    )
    op.drop_column("crop_jobs", "superseded_by_id")
    op.drop_column("crop_jobs", "heartbeat_at")
    op.drop_column("crop_jobs", "max_attempts")
    op.drop_column("crop_jobs", "attempt_count")
    op.drop_column("crop_jobs", "dispatched_at")
    op.drop_column("crop_jobs", "dispatch_token")
