"""track authorized crop job requesters

Revision ID: 0015_crop_job_subscriptions
Revises: 0014_job_recovery_maintenance
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0015_crop_job_subscriptions"
down_revision: str | None = "0014_job_recovery_maintenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "crop_job_subscriptions",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("paper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("region_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "requested_by_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"], ["crop_jobs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"], ["papers.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["region_id"], ["visual_regions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id",
            "paper_id",
            "region_id",
            "requested_by_id",
            name="uq_crop_job_subscriptions_scope",
        ),
    )
    op.create_index(
        "ix_crop_job_subscriptions_requester_job",
        "crop_job_subscriptions",
        ["requested_by_id", "job_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_crop_job_subscriptions_requester_job",
        table_name="crop_job_subscriptions",
    )
    op.drop_table("crop_job_subscriptions")
