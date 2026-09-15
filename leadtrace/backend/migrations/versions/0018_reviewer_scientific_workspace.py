"""add Reviewer proposal evidence, frozen scopes, and attestations

Revision ID: 0018_reviewer_scientific_workspace
Revises: 0017_unique_active_review_task
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0018_reviewer_scientific_workspace"
down_revision: str | None = "0017_unique_active_review_task"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _release_item_validation_function(*, include_proposal: bool) -> str:
    proposal_branch = """
                WHEN 'molecule_proposal' THEN
                    SELECT mp.paper_id INTO actual_paper_id
                    FROM molecule_proposals mp WHERE mp.id = NEW.object_id;
""" if include_proposal else ""
    return f"""
        CREATE OR REPLACE FUNCTION leadtrace_validate_release_item()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            release_finalized boolean;
            actual_kind text;
            actual_paper_id uuid;
            revision_state text;
        BEGIN
            SELECT manifest_finalized INTO release_finalized
            FROM releases WHERE id = NEW.release_id;
            IF release_finalized THEN
                RAISE EXCEPTION 'release manifest is finalized';
            END IF;

            SELECT ro.object_kind::text INTO actual_kind
            FROM revisioned_objects ro WHERE ro.id = NEW.object_id;
            IF actual_kind IS NULL OR actual_kind <> NEW.object_kind THEN
                RAISE EXCEPTION 'release item object kind does not match object';
            END IF;

            SELECT orv.workflow_state::text INTO revision_state
            FROM object_revisions orv
            WHERE orv.id = NEW.revision_id AND orv.object_id = NEW.object_id;
            IF revision_state IS NULL OR revision_state <> 'published' THEN
                RAISE EXCEPTION 'release item revision is not published';
            END IF;

            CASE NEW.object_kind
                WHEN 'paper' THEN
                    SELECT p.id INTO actual_paper_id FROM papers p WHERE p.id = NEW.object_id;
                WHEN 'compound' THEN
                    SELECT c.paper_id INTO actual_paper_id FROM compounds c WHERE c.id = NEW.object_id;
                WHEN 'structure' THEN
                    SELECT s.paper_id INTO actual_paper_id FROM structures s WHERE s.id = NEW.object_id;
                WHEN 'evidence' THEN
                    SELECT e.paper_id INTO actual_paper_id FROM evidence_records e WHERE e.id = NEW.object_id;
                WHEN 'activity' THEN
                    SELECT a.paper_id INTO actual_paper_id FROM activity_records a WHERE a.id = NEW.object_id;
                WHEN 'lineage' THEN
                    SELECT l.paper_id INTO actual_paper_id FROM lineages l WHERE l.id = NEW.object_id;
                WHEN 'lineage_edge' THEN
                    SELECT le.paper_id INTO actual_paper_id FROM lineage_edges le WHERE le.id = NEW.object_id;
                WHEN 'visual_region' THEN
                    SELECT vr.paper_id INTO actual_paper_id FROM visual_regions vr WHERE vr.id = NEW.object_id;
                WHEN 'visual_object' THEN
                    SELECT vo.paper_id INTO actual_paper_id FROM visual_objects vo WHERE vo.id = NEW.object_id;
                {proposal_branch}
                ELSE
                    actual_paper_id := NULL;
            END CASE;
            IF actual_paper_id IS NULL OR actual_paper_id <> NEW.paper_id THEN
                RAISE EXCEPTION 'release item paper does not match object';
            END IF;
            RETURN NEW;
        END;
        $$;
    """


def _changeset_item_validation_function(*, include_proposal: bool) -> str:
    proposal_branch = """
                    WHEN 'molecule_proposal' THEN
                        SELECT paper_id INTO actual_paper_id
                        FROM molecule_proposals WHERE id = NEW.object_id;
""" if include_proposal else ""
    return f"""
        CREATE OR REPLACE FUNCTION leadtrace_protect_changeset_item()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            old_state text;
            new_state text;
            actual_kind text;
            actual_paper_id uuid;
        BEGIN
            IF TG_OP IN ('UPDATE', 'DELETE') THEN
                SELECT workflow_state::text INTO old_state
                FROM changesets WHERE id = OLD.changeset_id;
                IF old_state IS NULL THEN
                    RAISE EXCEPTION 'changeset not found';
                END IF;
                IF old_state NOT IN ('draft', 'revised_draft') THEN
                    RAISE EXCEPTION 'changeset items are immutable after submission';
                END IF;
            END IF;

            IF TG_OP IN ('INSERT', 'UPDATE') THEN
                SELECT workflow_state::text INTO new_state
                FROM changesets WHERE id = NEW.changeset_id;
                IF new_state IS NULL THEN
                    RAISE EXCEPTION 'changeset not found';
                END IF;
                IF new_state NOT IN ('draft', 'revised_draft') THEN
                    RAISE EXCEPTION 'changeset items are immutable after submission';
                END IF;
                IF NEW.content_hash <> leadtrace_jsonb_sha256(NEW.proposed_snapshot)
                THEN
                    RAISE EXCEPTION 'changeset item content hash mismatch';
                END IF;
                IF TG_OP = 'UPDATE'
                   AND (NEW.changeset_id <> OLD.changeset_id
                        OR NEW.paper_id <> OLD.paper_id)
                THEN
                    RAISE EXCEPTION 'changeset item scope is immutable';
                END IF;

                PERFORM 1
                FROM changesets
                WHERE id = NEW.changeset_id AND paper_id = NEW.paper_id;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'changeset item paper does not match changeset';
                END IF;

                SELECT object_kind::text INTO actual_kind
                FROM revisioned_objects WHERE id = NEW.object_id;
                IF actual_kind IS NULL OR actual_kind <> NEW.object_kind THEN
                    RAISE EXCEPTION 'changeset item object kind does not match object';
                END IF;

                CASE NEW.object_kind
                    WHEN 'paper' THEN
                        SELECT id INTO actual_paper_id FROM papers WHERE id = NEW.object_id;
                    WHEN 'compound' THEN
                        SELECT paper_id INTO actual_paper_id FROM compounds WHERE id = NEW.object_id;
                    WHEN 'structure' THEN
                        SELECT paper_id INTO actual_paper_id FROM structures WHERE id = NEW.object_id;
                    WHEN 'evidence' THEN
                        SELECT paper_id INTO actual_paper_id FROM evidence_records WHERE id = NEW.object_id;
                    WHEN 'activity' THEN
                        SELECT paper_id INTO actual_paper_id FROM activity_records WHERE id = NEW.object_id;
                    WHEN 'lineage' THEN
                        SELECT paper_id INTO actual_paper_id FROM lineages WHERE id = NEW.object_id;
                    WHEN 'lineage_edge' THEN
                        SELECT paper_id INTO actual_paper_id FROM lineage_edges WHERE id = NEW.object_id;
                    WHEN 'visual_region' THEN
                        SELECT paper_id INTO actual_paper_id FROM visual_regions WHERE id = NEW.object_id;
                    WHEN 'visual_object' THEN
                        SELECT paper_id INTO actual_paper_id FROM visual_objects WHERE id = NEW.object_id;
                    {proposal_branch}
                    ELSE
                        actual_paper_id := NULL;
                END CASE;
                IF actual_paper_id IS NULL OR actual_paper_id <> NEW.paper_id THEN
                    RAISE EXCEPTION 'changeset item paper does not match object';
                END IF;
                IF NEW.proposed_revision_id IS NOT NULL THEN
                    PERFORM 1
                    FROM object_revisions proposed
                    WHERE proposed.id = NEW.proposed_revision_id
                      AND proposed.changeset_id = NEW.changeset_id
                      AND proposed.object_id = NEW.object_id
                      AND proposed.snapshot = NEW.proposed_snapshot
                      AND proposed.content_hash = NEW.content_hash
                      AND proposed.workflow_state IN ('draft', 'revised_draft')
                      AND NOT proposed.is_current_published;
                    IF NOT FOUND THEN
                        RAISE EXCEPTION
                            'changeset proposed revision does not match item content';
                    END IF;
                END IF;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$;
    """


def upgrade() -> None:
    # The descriptive revision identifier is longer than Alembic's historical
    # 32-character default. Widen only Alembic's own version marker before it
    # records this revision.
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=32),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    # Evidence-only backfills are explicit successor Release operations. Keep
    # the operation type in the same append-only audit table so idempotency and
    # historical Release provenance remain queryable.
    op.drop_constraint(
        "ck_release_operations_type",
        "release_operations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_release_operations_type",
        "release_operations",
        "operation_type IN ('baseline_publish', 'publish', 'rollback', 'machine_evidence')",
    )
    op.add_column(
        "object_revisions",
        sa.Column("proposal_disposition", sa.String(length=24), nullable=True),
    )
    op.create_check_constraint(
        "ck_object_revisions_proposal_disposition",
        "object_revisions",
        "proposal_disposition IS NULL OR proposal_disposition IN ("
        "'pending', 'accepted', 'corrected', 'rejected', 'not_applicable'"
        ")",
    )

    op.create_table(
        "molecule_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("paper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "visual_object_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("proposal_key", sa.String(length=255), nullable=False),
        sa.Column("model_run_key", sa.String(length=255), nullable=False),
        sa.Column("crop_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_region_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["id"], ["revisioned_objects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"], ["papers.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["visual_object_id"], ["visual_objects.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["crop_asset_id"], ["assets.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_region_id"], ["visual_regions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "paper_id",
            "visual_object_id",
            "proposal_key",
            "model_run_key",
            name="uq_molecule_proposals_identity",
        ),
    )
    op.create_index(
        "ix_molecule_proposals_paper", "molecule_proposals", ["paper_id"]
    )
    op.create_index(
        "ix_molecule_proposals_visual_object",
        "molecule_proposals",
        ["visual_object_id"],
    )

    op.create_table(
        "paper_review_scopes",
        sa.Column("changeset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("paper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("base_release_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "base_paper_revision_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("scope_hash", sa.String(length=64), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "char_length(scope_hash) = 64",
            name="ck_paper_review_scopes_hash_length",
        ),
        sa.CheckConstraint(
            "item_count >= 0", name="ck_paper_review_scopes_nonnegative_items"
        ),
        sa.ForeignKeyConstraint(
            ["base_paper_revision_id"],
            ["object_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["base_release_id"], ["releases.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["changeset_id"], ["changesets.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"], ["papers.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "changeset_id", name="uq_paper_review_scopes_changeset"
        ),
    )
    op.create_index(
        "ix_paper_review_scopes_paper", "paper_review_scopes", ["paper_id"]
    )

    op.create_table(
        "paper_review_attestations",
        sa.Column("changeset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("paper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("paper_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("changeset_version", sa.Integer(), nullable=False),
        sa.Column("scope_hash", sa.String(length=64), nullable=False),
        sa.Column("reviewer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("resolved_count", sa.Integer(), nullable=False),
        sa.Column("blocker_count", sa.Integer(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "char_length(scope_hash) = 64",
            name="ck_paper_review_attestations_hash_length",
        ),
        sa.CheckConstraint(
            "changeset_version > 0",
            name="ck_paper_review_attestations_positive_version",
        ),
        sa.CheckConstraint(
            "item_count >= 0 AND resolved_count >= 0 "
            "AND resolved_count <= item_count AND blocker_count >= 0 "
            "AND blocker_count <= item_count",
            name="ck_paper_review_attestations_counts",
        ),
        sa.ForeignKeyConstraint(
            ["changeset_id"], ["changesets.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"], ["papers.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["paper_revision_id"],
            ["object_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["scope_id"], ["paper_review_scopes.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "changeset_id",
            "changeset_version",
            name="uq_paper_review_attestations_version",
        ),
    )
    op.create_index(
        "ix_paper_review_attestations_paper",
        "paper_review_attestations",
        ["paper_id", "created_at"],
    )

    op.execute(
        """
        CREATE FUNCTION leadtrace_reject_paper_review_evidence_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Paper review evidence is append-only'
                USING ERRCODE = '55000';
        END;
        $$;
        CREATE TRIGGER trg_paper_review_scopes_append_only
        BEFORE UPDATE OR DELETE ON paper_review_scopes
        FOR EACH ROW EXECUTE FUNCTION leadtrace_reject_paper_review_evidence_mutation();
        CREATE TRIGGER trg_paper_review_attestations_append_only
        BEFORE UPDATE OR DELETE ON paper_review_attestations
        FOR EACH ROW EXECUTE FUNCTION leadtrace_reject_paper_review_evidence_mutation();
        """
    )
    op.execute(_release_item_validation_function(include_proposal=True))
    op.execute(_changeset_item_validation_function(include_proposal=True))


def downgrade() -> None:
    used = op.get_bind().execute(
        sa.text(
            """
            SELECT EXISTS (SELECT 1 FROM molecule_proposals LIMIT 1)
                OR EXISTS (SELECT 1 FROM paper_review_scopes LIMIT 1)
                OR EXISTS (SELECT 1 FROM paper_review_attestations LIMIT 1)
                OR EXISTS (
                    SELECT 1 FROM object_revisions
                    WHERE proposal_disposition IS NOT NULL LIMIT 1
                )
                OR EXISTS (
                    SELECT 1 FROM release_operations
                    WHERE operation_type = 'machine_evidence' LIMIT 1
                )
            """
        )
    ).scalar_one()
    if used:
        raise RuntimeError(
            "reviewer scientific workspace cannot be downgraded after use"
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

    op.execute(_changeset_item_validation_function(include_proposal=False))
    op.execute(_release_item_validation_function(include_proposal=False))
    op.execute(
        "DROP TRIGGER trg_paper_review_attestations_append_only "
        "ON paper_review_attestations"
    )
    op.execute(
        "DROP TRIGGER trg_paper_review_scopes_append_only ON paper_review_scopes"
    )
    op.execute("DROP FUNCTION leadtrace_reject_paper_review_evidence_mutation()")
    op.drop_index(
        "ix_paper_review_attestations_paper",
        table_name="paper_review_attestations",
    )
    op.drop_table("paper_review_attestations")
    op.drop_index("ix_paper_review_scopes_paper", table_name="paper_review_scopes")
    op.drop_table("paper_review_scopes")
    op.drop_index(
        "ix_molecule_proposals_visual_object", table_name="molecule_proposals"
    )
    op.drop_index("ix_molecule_proposals_paper", table_name="molecule_proposals")
    op.drop_table("molecule_proposals")
    op.drop_constraint(
        "ck_object_revisions_proposal_disposition",
        "object_revisions",
        type_="check",
    )
    op.drop_column("object_revisions", "proposal_disposition")
