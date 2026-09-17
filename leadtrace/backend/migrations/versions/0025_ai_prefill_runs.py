"""add transactional AI extraction runs

Revision ID: 0025_ai_prefill_runs
Revises: 0024_paper_publications
Create Date: 2026-09-17
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0025_ai_prefill_runs"
down_revision: str | None = "0024_paper_publications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CREATOR_KIND_TABLES = (
    "structures",
    "structure_source_images",
    "lineages",
    "lineage_members",
    "lineage_edges",
    "evidence",
    "edge_evidence_links",
    "activities",
)


def upgrade() -> None:
    for table_name in CREATOR_KIND_TABLES:
        op.add_column(
            table_name,
            sa.Column(
                "created_by_kind",
                sa.Enum(
                    "reviewer",
                    "admin",
                    "ai",
                    "system",
                    name="science_creator_kind",
                    native_enum=False,
                    length=16,
                ),
                server_default="reviewer",
                nullable=False,
            ),
        )
        op.create_check_constraint(
            f"ck_{table_name}_creator_kind",
            table_name,
            "created_by_kind IN ('reviewer', 'admin', 'ai', 'system')",
        )
        op.alter_column(table_name, "created_by_kind", server_default=None)

    op.create_table(
        "ai_extraction_runs",
        sa.Column("paper_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("requested_by_id", sa.UUID(), nullable=False),
        sa.Column("starting_workspace_version", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "succeeded",
                "failed",
                "superseded",
                name="ai_extraction_run_status",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("engine", sa.String(length=128), nullable=False),
        sa.Column("engine_version", sa.String(length=128), nullable=False),
        sa.Column("error_summary", sa.String(length=512), nullable=True),
        sa.Column("dispatch_token", sa.UUID(), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "queued_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["paper_id"], ["papers.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "paper_id"],
            ["paper_workspaces.id", "paper_workspaces.paper_id"],
            name="fk_ai_extraction_runs_workspace_paper",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "starting_workspace_version > 0",
            name="ck_ai_extraction_runs_positive_version",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'superseded')",
            name="ck_ai_extraction_runs_status",
        ),
        sa.CheckConstraint(
            "btrim(engine) <> ''",
            name="ck_ai_extraction_runs_engine_required",
        ),
        sa.CheckConstraint(
            "btrim(engine_version) <> ''",
            name="ck_ai_extraction_runs_engine_version_required",
        ),
    )
    op.create_index(
        "ix_ai_extraction_runs_workspace_time",
        "ai_extraction_runs",
        ["workspace_id", "queued_at"],
    )
    op.create_index(
        "uq_ai_extraction_runs_active_workspace",
        "ai_extraction_runs",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.create_foreign_key(
        "fk_change_events_ai_run",
        "change_events",
        "ai_extraction_runs",
        ["ai_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_change_events_ai_run", "change_events", type_="foreignkey"
    )
    op.drop_index(
        "uq_ai_extraction_runs_active_workspace",
        table_name="ai_extraction_runs",
    )
    op.drop_index(
        "ix_ai_extraction_runs_workspace_time",
        table_name="ai_extraction_runs",
    )
    op.drop_table("ai_extraction_runs")
    for table_name in reversed(CREATOR_KIND_TABLES):
        op.drop_constraint(
            f"ck_{table_name}_creator_kind",
            table_name,
            type_="check",
        )
        op.drop_column(table_name, "created_by_kind")
