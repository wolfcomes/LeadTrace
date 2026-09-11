"""add append-only audit event hash chain

Revision ID: 0010_audit
Revises: 0009_reviews
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0010_audit"
down_revision: str | None = "0009_reviews"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_chain_head",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("last_sequence_number", sa.BigInteger(), nullable=False),
        sa.Column("last_event_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_audit_chain_head_singleton"),
        sa.CheckConstraint(
            "char_length(last_event_hash) = 64",
            name="ck_audit_chain_head_hash_length",
        ),
        sa.CheckConstraint(
            "last_sequence_number >= 0",
            name="ck_audit_chain_head_nonnegative_sequence",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "INSERT INTO audit_chain_head "
        "(id, last_sequence_number, last_event_hash) "
        f"VALUES (1, 0, '{'0' * 64}')"
    )
    op.create_table(
        "audit_events",
        sa.Column("sequence_number", sa.BigInteger(), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("paper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("changeset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("release_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("before_hash", sa.String(length=64), nullable=False),
        sa.Column("after_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "details", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("previous_event_hash", sa.String(length=64), nullable=False),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "char_length(before_hash) = 64 AND char_length(after_hash) = 64",
            name="ck_audit_events_content_hash_lengths",
        ),
        sa.CheckConstraint(
            "char_length(previous_event_hash) = 64 AND char_length(event_hash) = 64",
            name="ck_audit_events_chain_hash_lengths",
        ),
        sa.CheckConstraint(
            "sequence_number > 0", name="ck_audit_events_positive_sequence"
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["changeset_id"], ["changesets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["release_id"], ["releases.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_actor_time", "audit_events", ["actor_id", "occurred_at"])
    op.create_index("ix_audit_events_changeset_time", "audit_events", ["changeset_id", "occurred_at"])
    op.create_index("ix_audit_events_paper_time", "audit_events", ["paper_id", "occurred_at"])
    op.create_index("uq_audit_events_event_hash", "audit_events", ["event_hash"], unique=True)
    op.create_index("uq_audit_events_sequence", "audit_events", ["sequence_number"], unique=True)
    op.execute(
        """
        CREATE FUNCTION leadtrace_reject_audit_event_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'audit events are append-only'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.create_table(
        "review_comments",
        sa.Column("changeset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("changeset_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_type", sa.String(length=24), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("field_path", sa.String(length=500), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["changeset_id"], ["changesets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["changeset_item_id"], ["changeset_items.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_review_comments_changeset_time",
        "review_comments",
        ["changeset_id", "created_at"],
    )
    op.create_table(
        "review_comment_events",
        sa.Column("comment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "sequence > 0", name="ck_review_comment_events_positive_sequence"
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["comment_id"], ["review_comments.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "comment_id", "sequence", name="uq_review_comment_events_sequence"
        ),
    )
    op.create_index(
        "ix_review_comment_events_comment",
        "review_comment_events",
        ["comment_id", "sequence"],
    )
    op.execute(
        """
        CREATE FUNCTION leadtrace_reject_comment_history_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'review comment history is append-only'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_review_comments_append_only
        BEFORE UPDATE OR DELETE ON review_comments
        FOR EACH ROW EXECUTE FUNCTION leadtrace_reject_comment_history_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_review_comment_events_append_only
        BEFORE UPDATE OR DELETE ON review_comment_events
        FOR EACH ROW EXECUTE FUNCTION leadtrace_reject_comment_history_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_events_append_only
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION leadtrace_reject_audit_event_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_review_comment_events_append_only "
        "ON review_comment_events"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_review_comments_append_only ON review_comments"
    )
    op.execute("DROP FUNCTION IF EXISTS leadtrace_reject_comment_history_mutation()")
    op.drop_index(
        "ix_review_comment_events_comment", table_name="review_comment_events"
    )
    op.drop_table("review_comment_events")
    op.drop_index("ix_review_comments_changeset_time", table_name="review_comments")
    op.drop_table("review_comments")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_events_append_only ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS leadtrace_reject_audit_event_mutation()")
    op.drop_index("uq_audit_events_sequence", table_name="audit_events")
    op.drop_index("uq_audit_events_event_hash", table_name="audit_events")
    op.drop_index("ix_audit_events_paper_time", table_name="audit_events")
    op.drop_index("ix_audit_events_changeset_time", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_time", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("audit_chain_head")
