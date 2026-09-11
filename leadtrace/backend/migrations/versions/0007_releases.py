"""Add explicit published releases and release-pinned revisions.

Revision ID: 0007_releases
Revises: 0006_revision_integrity
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0007_releases"
down_revision = "0006_revision_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_object_revisions_object_id_id",
        "object_revisions",
        ["object_id", "id"],
    )
    op.create_table(
        "releases",
        sa.Column("release_key", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column(
            "metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "source_candidate_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "published_by_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["published_by_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_candidate_id"],
            ["import_release_candidates.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_releases_key", "releases", ["release_key"], unique=True)
    op.create_index(
        "uq_releases_current",
        "releases",
        ["is_current"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.create_table(
        "release_items",
        sa.Column("release_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("object_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("paper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("object_kind", sa.String(length=24), nullable=False),
        sa.Column("manifest_order", sa.Integer(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["object_id", "revision_id"],
            ["object_revisions.object_id", "object_revisions.id"],
            name="fk_release_items_object_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"],
            ["papers.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["releases.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "release_id",
            "manifest_order",
            name="uq_release_items_manifest_order",
        ),
        sa.UniqueConstraint(
            "release_id",
            "object_id",
            name="uq_release_items_object",
        ),
        sa.UniqueConstraint(
            "release_id",
            "revision_id",
            name="uq_release_items_revision",
        ),
    )
    op.create_index(
        "ix_release_items_paper_kind",
        "release_items",
        ["release_id", "paper_id", "object_kind"],
    )
    op.create_index(
        "ix_compounds_normalized_label",
        "compounds",
        ["normalized_label"],
    )
    op.create_index(
        "ix_object_revisions_relation_status",
        "object_revisions",
        ["relation_status"],
    )
    op.create_index(
        "ix_object_revisions_structure_state",
        "object_revisions",
        ["structure_state"],
    )
    op.create_index(
        "ix_object_revisions_normalized_title",
        "object_revisions",
        [sa.text("lower(snapshot #>> '{normalized_values,title_guess}')")],
    )
    op.create_index(
        "ix_object_revisions_review_status",
        "object_revisions",
        [sa.text("(snapshot #>> '{normalized_values,review_status}')")],
    )
    op.execute(
        """
        CREATE INDEX ix_object_revisions_search_tsv
        ON object_revisions
        USING gin (to_tsvector('simple', coalesce(search_text, '')))
        """
    )
    op.execute(
        """
        CREATE FUNCTION leadtrace_protect_release_item()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'release item is immutable';
        END;
        $$;

        CREATE TRIGGER protect_release_item
        BEFORE UPDATE OR DELETE ON release_items
        FOR EACH ROW EXECUTE FUNCTION leadtrace_protect_release_item();
        """
    )
    op.execute(
        """
        CREATE FUNCTION leadtrace_protect_release()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'release is immutable';
            END IF;
            IF OLD.is_current
               AND NOT NEW.is_current
               AND (to_jsonb(NEW) - 'is_current') = (to_jsonb(OLD) - 'is_current')
            THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'release is immutable';
        END;
        $$;

        CREATE TRIGGER protect_release
        BEFORE UPDATE OR DELETE ON releases
        FOR EACH ROW EXECUTE FUNCTION leadtrace_protect_release();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER protect_release ON releases")
    op.execute("DROP FUNCTION leadtrace_protect_release()")
    op.execute("DROP TRIGGER protect_release_item ON release_items")
    op.execute("DROP FUNCTION leadtrace_protect_release_item()")
    op.drop_index("ix_object_revisions_search_tsv", table_name="object_revisions")
    op.drop_index("ix_object_revisions_review_status", table_name="object_revisions")
    op.drop_index("ix_object_revisions_normalized_title", table_name="object_revisions")
    op.drop_index("ix_object_revisions_structure_state", table_name="object_revisions")
    op.drop_index("ix_object_revisions_relation_status", table_name="object_revisions")
    op.drop_index("ix_compounds_normalized_label", table_name="compounds")
    op.drop_index("ix_release_items_paper_kind", table_name="release_items")
    op.drop_table("release_items")
    op.drop_index("uq_releases_current", table_name="releases")
    op.drop_index("uq_releases_key", table_name="releases")
    op.drop_table("releases")
    op.drop_constraint(
        "uq_object_revisions_object_id_id",
        "object_revisions",
        type_="unique",
    )
