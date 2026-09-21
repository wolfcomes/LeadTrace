"""add Preview identity marker and application receipts

Revision ID: 0026_ai_prefill_preview_receipts
Revises: 0025_ai_prefill_runs
Create Date: 2026-09-19
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0026_ai_prefill_preview_receipts"
down_revision = "0025_ai_prefill_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "preview_markers",
        sa.Column("instance_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("baseline_sha256", sa.String(length=64), nullable=False),
        sa.Column("schema_revision", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("instance_id", name="uq_preview_markers_instance"),
        sa.CheckConstraint(
            "baseline_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_preview_markers_baseline_hash",
        ),
    )
    op.create_table(
        "preview_application_receipts",
        sa.Column("instance_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("candidate_sha256", sa.String(length=64), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("paper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_map", postgresql.JSONB(), nullable=False),
        sa.Column("initial_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column(
            "committed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["instance_id"],
            ["preview_markers.instance_id"],
            name="fk_preview_receipts_instance",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"], ["papers.id"], name="fk_preview_receipts_paper", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "paper_id"],
            ["paper_workspaces.id", "paper_workspaces.paper_id"],
            name="fk_preview_receipts_workspace_paper",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["ai_extraction_runs.id"], name="fk_preview_receipts_run", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name="fk_preview_receipts_actor", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "instance_id",
            "idempotency_key",
            name="uq_preview_receipts_instance_idempotency",
        ),
        sa.UniqueConstraint("application_id", name="uq_preview_receipts_application"),
        sa.CheckConstraint(
            "btrim(idempotency_key) <> ''",
            name="ck_preview_receipts_idempotency_required",
        ),
        sa.CheckConstraint(
            "request_digest ~ '^[0-9a-f]{64}$'",
            name="ck_preview_receipts_request_digest",
        ),
        sa.CheckConstraint(
            "candidate_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_preview_receipts_candidate_hash",
        ),
        sa.CheckConstraint(
            "payload_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_preview_receipts_payload_hash",
        ),
        sa.CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_preview_receipts_source_hash",
        ),
    )
    op.create_index(
        "ix_preview_receipts_paper_time",
        "preview_application_receipts",
        ["paper_id", "committed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_preview_receipts_paper_time",
        table_name="preview_application_receipts",
    )
    op.drop_table("preview_application_receipts")
    op.drop_table("preview_markers")
