"""add initial baseline approval and publication support

Revision ID: 0016_initial_baseline_release
Revises: 0015_crop_job_subscriptions
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0016_initial_baseline_release"
down_revision: str | None = "0015_crop_job_subscriptions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "import_candidate_decisions",
        sa.Column(
            "candidate_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "manifest",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("manifest_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "decision IN ('approve', 'reject')",
            name="ck_import_candidate_decisions_decision",
        ),
        sa.CheckConstraint(
            "char_length(manifest_hash) = 64",
            name="ck_import_candidate_decisions_manifest_hash",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["import_release_candidates.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "candidate_id",
            name="uq_import_candidate_decisions_candidate",
        ),
    )
    op.create_index(
        "ix_import_candidate_decisions_candidate_time",
        "import_candidate_decisions",
        ["candidate_id", "created_at"],
    )
    op.execute(
        """
        CREATE FUNCTION leadtrace_reject_import_candidate_decision_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'import candidate decisions are append-only'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_import_candidate_decisions_append_only
        BEFORE UPDATE OR DELETE ON import_candidate_decisions
        FOR EACH ROW
        EXECUTE FUNCTION leadtrace_reject_import_candidate_decision_mutation()
        """
    )

    op.alter_column(
        "audit_events",
        "paper_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.alter_column(
        "release_operations",
        "replaced_release_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.drop_constraint(
        "ck_release_operations_type",
        "release_operations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_release_operations_type",
        "release_operations",
        "operation_type IN ('baseline_publish', 'publish', 'rollback')",
    )


def downgrade() -> None:
    # Once append-only approval/publication data exists, operators may roll back
    # application code but must keep the schema at 0016 or later.
    usage = op.get_bind().execute(
        sa.text(
            """
            SELECT
                EXISTS (
                    SELECT 1 FROM import_candidate_decisions LIMIT 1
                ) AS candidate_decisions,
                EXISTS (
                    SELECT 1
                    FROM release_operations
                    WHERE operation_type = 'baseline_publish'
                    LIMIT 1
                ) AS baseline_publications,
                EXISTS (
                    SELECT 1
                    FROM audit_events
                    WHERE paper_id IS NULL
                    LIMIT 1
                ) AS corpus_audit_events
            """
        )
    ).mappings().one()
    used_features = [
        label
        for key, label in (
            ("candidate_decisions", "candidate decisions"),
            ("baseline_publications", "baseline publications"),
            ("corpus_audit_events", "corpus audit events"),
        )
        if usage[key]
    ]
    if used_features:
        raise RuntimeError(
            "0016_initial_baseline_release cannot be downgraded after use "
            f"({', '.join(used_features)}). Roll back the application code "
            "while keeping the database schema at 0016 or later."
        )

    op.drop_constraint(
        "ck_release_operations_type",
        "release_operations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_release_operations_type",
        "release_operations",
        "operation_type IN ('publish', 'rollback')",
    )
    op.alter_column(
        "release_operations",
        "replaced_release_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.alter_column(
        "audit_events",
        "paper_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )

    op.execute(
        "DROP TRIGGER IF EXISTS trg_import_candidate_decisions_append_only "
        "ON import_candidate_decisions"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "leadtrace_reject_import_candidate_decision_mutation()"
    )
    op.drop_index(
        "ix_import_candidate_decisions_candidate_time",
        table_name="import_candidate_decisions",
    )
    op.drop_table("import_candidate_decisions")
