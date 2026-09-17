"""freeze immutable reviewer paper submissions

Revision ID: 0023_paper_submissions
Revises: 0022_crop_job_source_provenance
Create Date: 2026-09-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0023_paper_submissions"
down_revision: Union[str, Sequence[str], None] = "0022_crop_job_source_provenance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "paper_submissions",
        sa.Column("paper_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("review_task_id", sa.UUID(), nullable=False),
        sa.Column("submission_number", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("snapshot", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("workspace_version", sa.Integer(), nullable=False),
        sa.Column("submitted_by_id", sa.UUID(), nullable=False),
        sa.Column("reviewer_note", sa.Text(), nullable=True),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["paper_id"], ["papers.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "paper_id"],
            ["paper_workspaces.id", "paper_workspaces.paper_id"],
            name="fk_paper_submissions_workspace_paper",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["review_task_id", "paper_id"],
            ["review_tasks.id", "review_tasks.paper_id"],
            name="fk_paper_submissions_task_paper",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by_id"],
            ["users.id"],
            name="fk_paper_submissions_submitter",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "submission_number",
            name="uq_paper_submissions_workspace_number",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_paper_submissions_workspace_idempotency",
        ),
        sa.CheckConstraint(
            "submission_number > 0",
            name="ck_paper_submissions_positive_number",
        ),
        sa.CheckConstraint(
            "workspace_version > 0",
            name="ck_paper_submissions_positive_workspace_version",
        ),
        sa.CheckConstraint(
            "btrim(idempotency_key) <> ''",
            name="ck_paper_submissions_idempotency_required",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_paper_submissions_content_hash",
        ),
    )
    op.create_index(
        "ix_paper_submissions_workspace_time",
        "paper_submissions",
        ["workspace_id", "submitted_at"],
    )
    op.execute(
        sa.text(
            """
            CREATE FUNCTION leadtrace_protect_paper_submission()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'paper submissions are immutable'
                    USING ERRCODE = '55000';
            END;
            $$;
            CREATE TRIGGER protect_paper_submission
            BEFORE UPDATE OR DELETE ON paper_submissions
            FOR EACH ROW EXECUTE FUNCTION leadtrace_protect_paper_submission();
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS protect_paper_submission ON paper_submissions"
        )
    )
    op.execute(
        sa.text("DROP FUNCTION IF EXISTS leadtrace_protect_paper_submission()")
    )
    op.drop_index(
        "ix_paper_submissions_workspace_time", table_name="paper_submissions"
    )
    op.drop_table("paper_submissions")
