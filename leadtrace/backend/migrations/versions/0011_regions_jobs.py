"""persist deterministic visual crop jobs

Revision ID: 0011_regions_jobs
Revises: 0010_audit
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0011_regions_jobs"
down_revision: str | None = "0010_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "crop_jobs",
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("source_pdf_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("x0", sa.Float(), nullable=False),
        sa.Column("y0", sa.Float(), nullable=False),
        sa.Column("x1", sa.Float(), nullable=False),
        sa.Column("y1", sa.Float(), nullable=False),
        sa.Column("rotation", sa.Integer(), nullable=False),
        sa.Column("padding", sa.Integer(), nullable=False),
        sa.Column("dpi", sa.Integer(), nullable=False),
        sa.Column("renderer_version", sa.String(length=120), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "running", "completed", "failed", name="crop_job_status", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("char_length(input_hash) = 64", name="ck_crop_jobs_input_hash_length"),
        sa.CheckConstraint("char_length(source_pdf_sha256) = 64", name="ck_crop_jobs_source_hash_length"),
        sa.CheckConstraint("page_number > 0", name="ck_crop_jobs_positive_page"),
        sa.CheckConstraint("x0 >= 0 AND y0 >= 0 AND x1 <= 1 AND y1 <= 1 AND x0 < x1 AND y0 < y1", name="ck_crop_jobs_normalized_bounds"),
        sa.CheckConstraint("rotation IN (0, 90, 180, 270)", name="ck_crop_jobs_rotation"),
        sa.CheckConstraint("padding >= 0", name="ck_crop_jobs_nonnegative_padding"),
        sa.CheckConstraint("dpi > 0", name="ck_crop_jobs_positive_dpi"),
        sa.ForeignKeyConstraint(["source_asset_id"], ["assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("input_hash", name="uq_crop_jobs_input_hash"),
    )
    op.create_index("ix_crop_jobs_status_created", "crop_jobs", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_crop_jobs_status_created", table_name="crop_jobs")
    op.drop_table("crop_jobs")
