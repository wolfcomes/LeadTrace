"""Model versioned scientific domains.

Revision ID: 0004_scientific_domains
Revises: 0003_assets
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_scientific_domains"
down_revision = "0003_assets"
branch_labels = None
depends_on = None


def _identity_table(
    name: str,
    *columns: sa.Column,
    constraints: tuple[sa.Constraint, ...] = (),
) -> None:
    op.create_table(
        name,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        *columns,
        sa.ForeignKeyConstraint(
            ["id"],
            ["revisioned_objects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        *constraints,
    )


def upgrade() -> None:
    op.create_table(
        "revisioned_objects",
        sa.Column("object_kind", sa.String(length=24), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    _identity_table(
        "papers",
        sa.Column("paper_key", sa.String(length=128), nullable=False),
        sa.Column("doi", sa.String(length=255), nullable=True),
        constraints=(
            sa.UniqueConstraint("doi", name="uq_papers_doi"),
            sa.UniqueConstraint("paper_key", name="uq_papers_paper_key"),
        ),
    )
    _identity_table(
        "compounds",
        sa.Column("paper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("local_identity", sa.String(length=255), nullable=False),
        sa.Column("display_label", sa.String(length=255), nullable=False),
        sa.Column("normalized_label", sa.String(length=255), nullable=False),
        constraints=(
            sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="RESTRICT"),
            sa.UniqueConstraint(
                "paper_id",
                "local_identity",
                name="uq_compounds_paper_local_identity",
            ),
        ),
    )
    _identity_table(
        "structures",
        sa.Column("paper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("compound_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("structure_key", sa.String(length=255), nullable=False),
        constraints=(
            sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(
                ["compound_id"], ["compounds.id"], ondelete="RESTRICT"
            ),
            sa.UniqueConstraint(
                "compound_id",
                "structure_key",
                name="uq_structures_compound_key",
            ),
        ),
    )
    _identity_table(
        "evidence_records",
        sa.Column("paper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_key", sa.String(length=255), nullable=False),
        constraints=(
            sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="RESTRICT"),
            sa.UniqueConstraint(
                "paper_id", "evidence_key", name="uq_evidence_paper_key"
            ),
        ),
    )
    _identity_table(
        "activity_records",
        sa.Column("paper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("compound_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("activity_key", sa.String(length=255), nullable=False),
        constraints=(
            sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(
                ["compound_id"], ["compounds.id"], ondelete="RESTRICT"
            ),
            sa.UniqueConstraint(
                "paper_id", "activity_key", name="uq_activity_paper_key"
            ),
        ),
    )
    _identity_table(
        "lineages",
        sa.Column("paper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lineage_key", sa.String(length=255), nullable=False),
        constraints=(
            sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="RESTRICT"),
            sa.UniqueConstraint(
                "paper_id", "lineage_key", name="uq_lineages_paper_key"
            ),
        ),
    )
    _identity_table(
        "lineage_edges",
        sa.Column("paper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lineage_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("edge_key", sa.String(length=255), nullable=False),
        sa.Column("parent_compound_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("derived_compound_id", postgresql.UUID(as_uuid=True), nullable=False),
        constraints=(
            sa.CheckConstraint(
                "parent_compound_id IS NULL OR parent_compound_id <> derived_compound_id",
                name="ck_lineage_edges_no_self_loop",
            ),
            sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(
                ["lineage_id"], ["lineages.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(
                ["parent_compound_id"], ["compounds.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(
                ["derived_compound_id"], ["compounds.id"], ondelete="RESTRICT"
            ),
            sa.UniqueConstraint(
                "paper_id", "edge_key", name="uq_lineage_edges_paper_key"
            ),
        ),
    )
    _identity_table(
        "visual_regions",
        sa.Column("paper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("region_key", sa.String(length=255), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=False),
        constraints=(
            sa.CheckConstraint(
                "page_number > 0", name="ck_visual_regions_positive_page"
            ),
            sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="RESTRICT"),
            sa.UniqueConstraint(
                "paper_id", "region_key", name="uq_visual_regions_paper_key"
            ),
        ),
    )
    _identity_table(
        "visual_objects",
        sa.Column("paper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("object_key", sa.String(length=255), nullable=False),
        constraints=(
            sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="RESTRICT"),
            sa.UniqueConstraint(
                "paper_id", "object_key", name="uq_visual_objects_paper_key"
            ),
        ),
    )
    op.create_table(
        "object_revisions",
        sa.Column("object_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("predecessor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("changeset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=True),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("workflow_state", sa.String(length=24), nullable=False),
        sa.Column("is_current_published", sa.Boolean(), nullable=False),
        sa.Column("is_tombstone", sa.Boolean(), nullable=False),
        sa.Column("structure_state", sa.String(length=32), nullable=True),
        sa.Column("evidence_state", sa.String(length=24), nullable=True),
        sa.Column("activity_state", sa.String(length=24), nullable=True),
        sa.Column("canonical_smiles", sa.Text(), nullable=True),
        sa.Column("evidence_text", sa.Text(), nullable=True),
        sa.Column("activity_metric", sa.String(length=120), nullable=True),
        sa.Column("activity_value", sa.String(length=160), nullable=True),
        sa.Column("activity_unit", sa.String(length=80), nullable=True),
        sa.Column("relation_type", sa.String(length=120), nullable=True),
        sa.Column("relation_status", sa.String(length=80), nullable=True),
        sa.Column("region_x0", sa.Float(), nullable=True),
        sa.Column("region_y0", sa.Float(), nullable=True),
        sa.Column("region_x1", sa.Float(), nullable=True),
        sa.Column("region_y1", sa.Float(), nullable=True),
        sa.Column("region_rotation", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "char_length(content_hash) = 64",
            name="ck_object_revisions_content_hash_length",
        ),
        sa.CheckConstraint(
            "NOT is_current_published OR workflow_state = 'published'",
            name="ck_object_revisions_current_is_published",
        ),
        sa.CheckConstraint(
            """
            (region_x0 IS NULL AND region_y0 IS NULL AND region_x1 IS NULL
             AND region_y1 IS NULL)
            OR
            (region_x0 >= 0 AND region_y0 >= 0
             AND region_x1 <= 1 AND region_y1 <= 1
             AND region_x0 < region_x1 AND region_y0 < region_y1)
            """,
            name="ck_object_revisions_normalized_region",
        ),
        sa.CheckConstraint(
            "revision_number > 0", name="ck_object_revisions_positive_number"
        ),
        sa.CheckConstraint(
            "region_rotation IS NULL OR region_rotation IN (0, 90, 180, 270)",
            name="ck_object_revisions_region_rotation",
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["object_id"], ["revisioned_objects.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["predecessor_id"], ["object_revisions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "object_id", "revision_number", name="uq_object_revision_number"
        ),
    )
    op.create_index(
        "ix_object_revisions_object",
        "object_revisions",
        ["object_id", "revision_number"],
    )
    op.create_index(
        "uq_object_revisions_current_published",
        "object_revisions",
        ["object_id"],
        unique=True,
        postgresql_where=sa.text("is_current_published"),
    )
    op.execute(
        """
        CREATE FUNCTION leadtrace_protect_immutable_revision()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.workflow_state IN ('published', 'superseded') THEN
                    RAISE EXCEPTION 'published revision is immutable';
                END IF;
                RETURN OLD;
            END IF;
            IF OLD.workflow_state IN ('published', 'superseded') THEN
                IF OLD.workflow_state = 'published'
                   AND OLD.is_current_published
                   AND NEW.workflow_state = 'superseded'
                   AND NOT NEW.is_current_published
                   AND (to_jsonb(NEW) - ARRAY['workflow_state', 'is_current_published'])
                       = (to_jsonb(OLD) - ARRAY['workflow_state', 'is_current_published'])
                THEN
                    RETURN NEW;
                END IF;
                RAISE EXCEPTION 'published revision is immutable';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_object_revisions_immutable
        BEFORE UPDATE OR DELETE ON object_revisions
        FOR EACH ROW EXECUTE FUNCTION leadtrace_protect_immutable_revision()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_object_revisions_immutable ON object_revisions")
    op.execute("DROP FUNCTION leadtrace_protect_immutable_revision()")
    op.drop_index(
        "uq_object_revisions_current_published", table_name="object_revisions"
    )
    op.drop_index("ix_object_revisions_object", table_name="object_revisions")
    op.drop_table("object_revisions")
    op.drop_table("visual_objects")
    op.drop_table("visual_regions")
    op.drop_table("lineage_edges")
    op.drop_table("lineages")
    op.drop_table("activity_records")
    op.drop_table("evidence_records")
    op.drop_table("structures")
    op.drop_table("compounds")
    op.drop_table("papers")
    op.drop_table("revisioned_objects")
