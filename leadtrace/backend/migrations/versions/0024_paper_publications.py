"""add immutable Admin decisions and Published Paper versions

Revision ID: 0024_paper_publications
Revises: 0023_paper_submissions
Create Date: 2026-09-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0024_paper_publications"
down_revision: Union[str, Sequence[str], None] = "0023_paper_submissions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_paper_submissions_id_paper_hash",
        "paper_submissions",
        ["id", "paper_id", "content_hash"],
    )
    op.create_table(
        "admin_decisions",
        sa.Column("submission_id", sa.UUID(), nullable=False),
        sa.Column("paper_id", sa.UUID(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("decided_by_id", sa.UUID(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["submission_id", "paper_id", "content_hash"],
            [
                "paper_submissions.id",
                "paper_submissions.paper_id",
                "paper_submissions.content_hash",
            ],
            name="fk_admin_decisions_submission_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("submission_id", name="uq_admin_decisions_submission"),
        sa.UniqueConstraint(
            "decided_by_id",
            "idempotency_key",
            name="uq_admin_decisions_actor_idempotency",
        ),
        sa.UniqueConstraint(
            "id",
            "paper_id",
            "submission_id",
            "content_hash",
            "action",
            name="uq_admin_decisions_id_submission_identity",
        ),
        sa.CheckConstraint(
            "action IN ('approve', 'request_changes')",
            name="ck_admin_decisions_action",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_admin_decisions_content_hash",
        ),
        sa.CheckConstraint("btrim(reason) <> ''", name="ck_admin_decisions_reason"),
        sa.CheckConstraint(
            "btrim(idempotency_key) <> ''", name="ck_admin_decisions_idempotency"
        ),
    )
    op.create_index(
        "ix_admin_decisions_time", "admin_decisions", ["decided_at", "id"]
    )
    op.create_table(
        "published_paper_versions",
        sa.Column("paper_id", sa.UUID(), nullable=False),
        sa.Column("submission_id", sa.UUID(), nullable=False),
        sa.Column("admin_decision_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("decision_action", sa.String(length=24), nullable=False),
        sa.Column("published_by_id", sa.UUID(), nullable=False),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["submission_id", "paper_id", "content_hash"],
            [
                "paper_submissions.id",
                "paper_submissions.paper_id",
                "paper_submissions.content_hash",
            ],
            name="fk_published_versions_submission_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "admin_decision_id",
                "paper_id",
                "submission_id",
                "content_hash",
                "decision_action",
            ],
            [
                "admin_decisions.id",
                "admin_decisions.paper_id",
                "admin_decisions.submission_id",
                "admin_decisions.content_hash",
                "admin_decisions.action",
            ],
            name="fk_published_versions_decision_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["published_by_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "submission_id", name="uq_published_versions_submission"
        ),
        sa.UniqueConstraint(
            "admin_decision_id", name="uq_published_versions_admin_decision"
        ),
        sa.UniqueConstraint(
            "paper_id",
            "version_number",
            name="uq_published_versions_paper_number",
        ),
        sa.UniqueConstraint("id", "paper_id", name="uq_published_versions_id_paper"),
        sa.CheckConstraint(
            "version_number > 0", name="ck_published_versions_positive_number"
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_published_versions_content_hash",
        ),
        sa.CheckConstraint(
            "decision_action = 'approve'",
            name="ck_published_versions_approved_decision",
        ),
    )
    op.create_index(
        "ix_published_versions_paper_time",
        "published_paper_versions",
        ["paper_id", "published_at"],
    )
    op.add_column(
        "papers", sa.Column("current_published_version_id", sa.UUID(), nullable=True)
    )
    op.create_index(
        "ix_papers_current_published_version",
        "papers",
        ["current_published_version_id"],
    )
    op.create_foreign_key(
        "fk_papers_current_published_version",
        "papers",
        "published_paper_versions",
        ["current_published_version_id", "id"],
        ["id", "paper_id"],
        ondelete="RESTRICT",
    )
    op.execute(
        sa.text(
            """
            CREATE FUNCTION leadtrace_protect_publication_history()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION '% rows are immutable', TG_TABLE_NAME
                    USING ERRCODE = '55000';
            END;
            $$;
            CREATE TRIGGER protect_admin_decision
            BEFORE UPDATE OR DELETE ON admin_decisions
            FOR EACH ROW EXECUTE FUNCTION leadtrace_protect_publication_history();
            CREATE TRIGGER protect_published_paper_version
            BEFORE UPDATE OR DELETE ON published_paper_versions
            FOR EACH ROW EXECUTE FUNCTION leadtrace_protect_publication_history();
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER protect_admin_decision ON admin_decisions"))
    op.execute(
        sa.text(
            "DROP TRIGGER protect_published_paper_version "
            "ON published_paper_versions"
        )
    )
    op.execute(sa.text("DROP FUNCTION leadtrace_protect_publication_history()"))
    op.drop_constraint(
        "fk_papers_current_published_version", "papers", type_="foreignkey"
    )
    op.drop_index("ix_papers_current_published_version", table_name="papers")
    op.drop_column("papers", "current_published_version_id")
    op.drop_index(
        "ix_published_versions_paper_time", table_name="published_paper_versions"
    )
    op.drop_table("published_paper_versions")
    op.drop_index("ix_admin_decisions_time", table_name="admin_decisions")
    op.drop_table("admin_decisions")
    op.drop_constraint(
        "uq_paper_submissions_id_paper_hash",
        "paper_submissions",
        type_="unique",
    )
