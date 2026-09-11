"""Add review tasks and immutable changesets.

Revision ID: 0009_reviews
Revises: 0008_release_hardening
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0009_reviews"
down_revision = "0008_release_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    workflow_values = [
        "draft",
        "revised_draft",
        "submitted",
        "changes_requested",
        "approved",
        "published",
        "superseded",
        "rejected",
    ]
    task_values = ["open", "in_progress", "submitted", "changes_requested", "completed"]

    op.create_table(
        "review_tasks",
        sa.Column("paper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "assigned_reviewer_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                *task_values,
                name="review_task_status",
                native_enum=False,
                length=24,
            ),
            nullable=False,
            server_default="open",
        ),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_review_tasks_positive_version"),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["assigned_reviewer_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "paper_id",
            "assigned_reviewer_id",
            name="uq_review_tasks_id_paper_assignee",
        ),
    )
    op.create_index(
        "ix_review_tasks_assignee_status",
        "review_tasks",
        ["assigned_reviewer_id", "status"],
    )
    op.create_index(
        "ix_review_tasks_paper_status", "review_tasks", ["paper_id", "status"]
    )
    op.create_index(
        "uq_review_tasks_active_assignment",
        "review_tasks",
        ["paper_id", "assigned_reviewer_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'completed'"),
    )

    op.create_table(
        "changesets",
        sa.Column("review_task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("paper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("base_release_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "workflow_state",
            sa.Enum(
                *workflow_values,
                name="changeset_workflow_state",
                native_enum=False,
                length=24,
            ),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "validation_results",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "submitted_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("submitted_content_hash", sa.String(length=64), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_changesets_positive_version"),
        sa.CheckConstraint(
            "submitted_content_hash IS NULL OR "
            "char_length(submitted_content_hash) = 64",
            name="ck_changesets_submitted_content_hash_length",
        ),
        sa.ForeignKeyConstraint(
            ["review_task_id", "paper_id", "owner_id"],
            [
                "review_tasks.id",
                "review_tasks.paper_id",
                "review_tasks.assigned_reviewer_id",
            ],
            name="fk_changesets_task_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["base_release_id"], ["releases.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "paper_id", name="uq_changesets_id_paper"),
        sa.UniqueConstraint("review_task_id", name="uq_changesets_review_task"),
    )
    op.create_index(
        "ix_changesets_paper_state", "changesets", ["paper_id", "workflow_state"]
    )
    op.create_index(
        "ix_changesets_owner_state", "changesets", ["owner_id", "workflow_state"]
    )

    # Pre-0009 changeset IDs had no referential meaning because review tables did
    # not exist. Clear them before enforcing the new review ownership contract.
    op.execute("ALTER TABLE object_revisions DISABLE TRIGGER trg_object_revisions_immutable")
    op.execute(
        "UPDATE object_revisions SET changeset_id = NULL "
        "WHERE changeset_id IS NOT NULL"
    )
    op.execute("ALTER TABLE object_revisions ENABLE TRIGGER trg_object_revisions_immutable")
    op.create_unique_constraint(
        "uq_object_revisions_changeset_object_id",
        "object_revisions",
        ["changeset_id", "object_id", "id"],
    )

    op.create_table(
        "changeset_items",
        sa.Column("changeset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("paper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("object_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("object_kind", sa.String(length=24), nullable=False),
        sa.Column("base_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "proposed_revision_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "proposed_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("sequence > 0", name="ck_changeset_items_positive_sequence"),
        sa.CheckConstraint(
            "char_length(content_hash) = 64",
            name="ck_changeset_items_content_hash_length",
        ),
        sa.ForeignKeyConstraint(
            ["changeset_id", "paper_id"],
            ["changesets.id", "changesets.paper_id"],
            name="fk_changeset_items_changeset_paper",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["object_id"],
            ["revisioned_objects.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["object_id", "base_revision_id"],
            ["object_revisions.object_id", "object_revisions.id"],
            name="fk_changeset_items_object_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["changeset_id", "object_id", "proposed_revision_id"],
            [
                "object_revisions.changeset_id",
                "object_revisions.object_id",
                "object_revisions.id",
            ],
            name="fk_changeset_items_proposed_revision",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "changeset_id", "sequence", name="uq_changeset_items_sequence"
        ),
        sa.UniqueConstraint(
            "changeset_id", "object_id", name="uq_changeset_items_object"
        ),
    )
    op.create_index(
        "ix_changeset_items_changeset", "changeset_items", ["changeset_id", "sequence"]
    )

    op.create_table(
        "changeset_submissions",
        sa.Column("changeset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("submission_number", sa.Integer(), nullable=False),
        sa.Column("changeset_version", sa.Integer(), nullable=False),
        sa.Column("submitted_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "submission_number > 0", name="ck_changeset_submissions_positive_number"
        ),
        sa.CheckConstraint(
            "changeset_version > 0", name="ck_changeset_submissions_positive_version"
        ),
        sa.CheckConstraint(
            "char_length(content_hash) = 64",
            name="ck_changeset_submissions_content_hash_length",
        ),
        sa.ForeignKeyConstraint(
            ["changeset_id"], ["changesets.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["submitted_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "changeset_id", "submission_number", name="uq_changeset_submissions_number"
        ),
        sa.UniqueConstraint(
            "changeset_id", "changeset_version", name="uq_changeset_submissions_version"
        ),
    )
    op.create_index(
        "ix_changeset_submissions_changeset",
        "changeset_submissions",
        ["changeset_id", "submission_number"],
    )
    op.create_foreign_key(
        "fk_object_revisions_changeset_item",
        "object_revisions",
        "changeset_items",
        ["changeset_id", "object_id"],
        ["changeset_id", "object_id"],
        ondelete="RESTRICT",
    )

    op.execute(
        """
        CREATE FUNCTION leadtrace_validate_changeset_revision_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            changeset_state text;
        BEGIN
            IF NEW.changeset_id IS NULL THEN
                RETURN NEW;
            END IF;
            IF NEW.content_hash <> leadtrace_jsonb_sha256(NEW.snapshot) THEN
                RAISE EXCEPTION 'changeset-linked revision content hash mismatch';
            END IF;
            SELECT workflow_state::text INTO changeset_state
            FROM changesets
            WHERE id = NEW.changeset_id
            FOR UPDATE;
            IF changeset_state IS NULL THEN
                RAISE EXCEPTION 'revision must belong to an editable draft changeset';
            END IF;
            IF changeset_state NOT IN ('draft', 'revised_draft')
            THEN
                RAISE EXCEPTION
                    'revision must belong to an editable draft changeset';
            END IF;
            IF NEW.workflow_state NOT IN ('draft', 'revised_draft')
               OR NEW.is_current_published
            THEN
                RAISE EXCEPTION
                    'changeset-linked revision cannot be published before approval';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER validate_changeset_revision_insert
        BEFORE INSERT ON object_revisions
        FOR EACH ROW EXECUTE FUNCTION leadtrace_validate_changeset_revision_insert();

        CREATE FUNCTION leadtrace_validate_changeset_revision_update()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            changeset_state text;
        BEGIN
            IF NEW.changeset_id IS NULL THEN
                RETURN NEW;
            END IF;
            IF NEW.content_hash <> leadtrace_jsonb_sha256(NEW.snapshot) THEN
                RAISE EXCEPTION 'changeset-linked revision content hash mismatch';
            END IF;
            SELECT workflow_state::text INTO changeset_state
            FROM changesets
            WHERE id = NEW.changeset_id;
            IF changeset_state IS NULL THEN
                RAISE EXCEPTION 'revision changeset does not exist';
            END IF;
            IF NEW.workflow_state IS NOT DISTINCT FROM OLD.workflow_state
               AND NEW.is_current_published IS NOT DISTINCT FROM OLD.is_current_published
            THEN
                RETURN NEW;
            END IF;
            IF changeset_state NOT IN ('approved', 'published', 'superseded')
            THEN
                RAISE EXCEPTION
                    'linked revision cannot advance before changeset approval';
            END IF;
            IF NOT (
                (changeset_state = 'approved'
                 AND NEW.workflow_state IN ('submitted', 'approved')
                 AND NOT NEW.is_current_published)
                OR
                (changeset_state = 'published'
                 AND NEW.workflow_state IN ('submitted', 'approved', 'published')
                 AND (NOT NEW.is_current_published
                      OR NEW.workflow_state = 'published'))
                OR
                (changeset_state = 'superseded'
                 AND NEW.workflow_state = 'superseded'
                 AND NOT NEW.is_current_published)
            ) THEN
                RAISE EXCEPTION
                    'linked revision state is inconsistent with changeset state';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER validate_changeset_revision_update
        BEFORE UPDATE ON object_revisions
        FOR EACH ROW EXECUTE FUNCTION leadtrace_validate_changeset_revision_update();

        CREATE FUNCTION leadtrace_validate_changeset_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.workflow_state <> 'draft'
               OR NEW.version <> 1
               OR NEW.submitted_at IS NOT NULL
               OR NEW.submitted_snapshot IS NOT NULL
               OR NEW.submitted_content_hash IS NOT NULL
            THEN
                RAISE EXCEPTION 'new changesets must start as version-one drafts';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER validate_changeset_insert
        BEFORE INSERT ON changesets
        FOR EACH ROW EXECUTE FUNCTION leadtrace_validate_changeset_insert();

        CREATE FUNCTION leadtrace_validate_changeset_transition()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NOT (
                (OLD.workflow_state = 'draft' AND NEW.workflow_state = 'submitted') OR
                (OLD.workflow_state = 'revised_draft' AND NEW.workflow_state = 'submitted') OR
                (OLD.workflow_state = 'submitted' AND NEW.workflow_state IN ('changes_requested', 'rejected', 'approved')) OR
                (OLD.workflow_state = 'changes_requested' AND NEW.workflow_state = 'revised_draft') OR
                (OLD.workflow_state = 'approved' AND NEW.workflow_state = 'published') OR
                (OLD.workflow_state = 'published' AND NEW.workflow_state = 'superseded') OR
                (OLD.workflow_state = NEW.workflow_state AND OLD.workflow_state IN ('draft', 'revised_draft'))
            ) THEN
                RAISE EXCEPTION 'invalid changeset workflow transition from % to %', OLD.workflow_state, NEW.workflow_state;
            END IF;

            IF NEW.version <> OLD.version + 1 THEN
                RAISE EXCEPTION 'changeset version must increment exactly once';
            END IF;

            IF NEW.workflow_state IN ('submitted', 'changes_requested', 'rejected', 'approved', 'published', 'superseded')
               AND (NEW.submitted_at IS NULL
                    OR NEW.submitted_snapshot IS NULL
                    OR NEW.submitted_content_hash IS NULL)
            THEN
                RAISE EXCEPTION 'submitted changesets require a timestamp and snapshot';
            END IF;

            IF OLD.workflow_state = NEW.workflow_state
               AND OLD.workflow_state IN ('draft', 'revised_draft')
               AND (NEW.submitted_at IS DISTINCT FROM OLD.submitted_at
                    OR NEW.submitted_snapshot IS DISTINCT FROM OLD.submitted_snapshot
                    OR NEW.submitted_content_hash IS DISTINCT FROM OLD.submitted_content_hash)
            THEN
                RAISE EXCEPTION 'changeset submission metadata is immutable while editing a draft';
            END IF;

            IF OLD.submitted_at IS NOT NULL
               AND NEW.submitted_at IS DISTINCT FROM OLD.submitted_at
            THEN
                RAISE EXCEPTION 'changeset submission metadata is immutable after first submission';
            END IF;

            IF OLD.workflow_state = NEW.workflow_state
               AND OLD.workflow_state IN ('draft', 'revised_draft')
               AND (to_jsonb(NEW) - ARRAY[
                        'title', 'reason', 'validation_results', 'version', 'updated_at'
                   ])
                   <> (to_jsonb(OLD) - ARRAY[
                        'title', 'reason', 'validation_results', 'version', 'updated_at'
                   ])
            THEN
                RAISE EXCEPTION 'changeset scope is immutable';
            ELSIF OLD.workflow_state IN ('draft', 'revised_draft')
               AND NEW.workflow_state = 'submitted'
               AND (to_jsonb(NEW) - ARRAY[
                        'workflow_state', 'version', 'updated_at',
                        'submitted_at', 'submitted_snapshot',
                        'submitted_content_hash'
                   ])
                   <> (to_jsonb(OLD) - ARRAY[
                        'workflow_state', 'version', 'updated_at',
                        'submitted_at', 'submitted_snapshot',
                        'submitted_content_hash'
                   ])
            THEN
                RAISE EXCEPTION 'changeset scope cannot change during submission';
            ELSIF OLD.workflow_state NOT IN ('draft', 'revised_draft')
               AND (to_jsonb(NEW) - ARRAY['workflow_state', 'version', 'updated_at'])
                   <> (to_jsonb(OLD) - ARRAY['workflow_state', 'version', 'updated_at'])
            THEN
                RAISE EXCEPTION 'changeset content is immutable after submission';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER validate_changeset_transition
        BEFORE UPDATE ON changesets
        FOR EACH ROW EXECUTE FUNCTION leadtrace_validate_changeset_transition();

        CREATE FUNCTION leadtrace_protect_changeset_delete()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.workflow_state NOT IN ('draft', 'revised_draft') THEN
                RAISE EXCEPTION 'changeset is immutable after submission';
            END IF;
            RETURN OLD;
        END;
        $$;

        CREATE TRIGGER protect_changeset_delete
        BEFORE DELETE ON changesets
        FOR EACH ROW EXECUTE FUNCTION leadtrace_protect_changeset_delete();

        CREATE FUNCTION leadtrace_protect_changeset_item()
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

        CREATE TRIGGER protect_changeset_item
        BEFORE INSERT OR UPDATE OR DELETE ON changeset_items
        FOR EACH ROW EXECUTE FUNCTION leadtrace_protect_changeset_item();

        CREATE FUNCTION leadtrace_changeset_snapshot(target_changeset_id uuid)
        RETURNS jsonb
        LANGUAGE sql
        STABLE
        AS $$
            SELECT jsonb_build_object(
                'changeset_id', c.id::text,
                'review_task_id', c.review_task_id::text,
                'paper_id', c.paper_id::text,
                'owner_id', c.owner_id::text,
                'base_release_id', c.base_release_id::text,
                'title', c.title,
                'reason', c.reason,
                'validation_results', c.validation_results,
                'items', COALESCE(
                    (
                        SELECT jsonb_agg(
                            jsonb_build_object(
                                'id', ci.id::text,
                                'object_id', ci.object_id::text,
                                'object_kind', ci.object_kind,
                                'base_revision_id', ci.base_revision_id::text,
                                'proposed_revision_id', ci.proposed_revision_id::text,
                                'proposed_snapshot', ci.proposed_snapshot,
                                'content_hash', ci.content_hash,
                                'sequence', ci.sequence
                            )
                            ORDER BY ci.sequence, ci.id
                        )
                        FROM changeset_items ci
                        WHERE ci.changeset_id = c.id
                    ),
                    '[]'::jsonb
                )
            )
            FROM changesets c
            WHERE c.id = target_changeset_id
        $$;

        CREATE FUNCTION leadtrace_jsonb_sha256(payload jsonb)
        RETURNS text
        LANGUAGE sql
        IMMUTABLE
        STRICT
        AS $$
            SELECT encode(sha256(convert_to(payload::text, 'UTF8')), 'hex')
        $$;

        CREATE FUNCTION leadtrace_changeset_snapshot_hash(target_changeset_id uuid)
        RETURNS text
        LANGUAGE sql
        STABLE
        STRICT
        AS $$
            SELECT leadtrace_jsonb_sha256(
                leadtrace_changeset_snapshot(target_changeset_id)
            )
        $$;

        CREATE FUNCTION leadtrace_protect_changeset_submission()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'changeset submission snapshots are immutable';
        END;
        $$;

        CREATE TRIGGER protect_changeset_submission
        BEFORE UPDATE OR DELETE ON changeset_submissions
        FOR EACH ROW EXECUTE FUNCTION leadtrace_protect_changeset_submission();

        CREATE FUNCTION leadtrace_validate_changeset_submission()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            current_state text;
            current_version integer;
            current_snapshot jsonb;
            current_hash text;
            current_owner uuid;
            submitter_role text;
            submission_count integer;
            canonical_snapshot jsonb;
            canonical_hash text;
        BEGIN
            SELECT workflow_state::text, version, submitted_snapshot,
                   submitted_content_hash, owner_id
            INTO current_state, current_version, current_snapshot, current_hash,
                 current_owner
            FROM changesets WHERE id = NEW.changeset_id;
            SELECT role::text INTO submitter_role
            FROM users WHERE id = NEW.submitted_by_id;
            SELECT count(*) INTO submission_count
            FROM changeset_submissions WHERE changeset_id = NEW.changeset_id;
            canonical_snapshot := leadtrace_changeset_snapshot(NEW.changeset_id);
            canonical_hash := leadtrace_jsonb_sha256(canonical_snapshot);
            IF NEW.snapshot <> canonical_snapshot
               OR NEW.content_hash <> canonical_hash
               OR jsonb_array_length(canonical_snapshot -> 'items') = 0
               OR EXISTS (
                    SELECT 1 FROM changeset_items ci
                    WHERE ci.changeset_id = NEW.changeset_id
                      AND ci.proposed_revision_id IS NULL
               )
            THEN
                RAISE EXCEPTION 'submission does not match canonical changeset content';
            END IF;
            IF current_state <> 'submitted'
               OR current_version <> NEW.changeset_version
               OR current_snapshot <> NEW.snapshot
               OR current_hash <> NEW.content_hash
               OR (NEW.submitted_by_id <> current_owner
                   AND submitter_role <> 'admin')
               OR NEW.submission_number <> submission_count
            THEN
                RAISE EXCEPTION 'submission snapshot does not match submitted changeset';
            END IF;
            RETURN NULL;
        END;
        $$;

        CREATE TRIGGER validate_changeset_submission
        AFTER INSERT ON changeset_submissions
        FOR EACH ROW EXECUTE FUNCTION leadtrace_validate_changeset_submission();

        CREATE FUNCTION leadtrace_require_changeset_submission()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.workflow_state = 'submitted' THEN
                IF NOT EXISTS (
                    SELECT 1 FROM changeset_submissions cs
                    WHERE cs.changeset_id = NEW.id
                      AND cs.changeset_version = NEW.version
                      AND cs.snapshot = NEW.submitted_snapshot
                      AND cs.content_hash = NEW.submitted_content_hash
                ) THEN
                    RAISE EXCEPTION 'submitted changeset requires a matching snapshot';
                END IF;
            END IF;
            RETURN NULL;
        END;
        $$;

        CREATE CONSTRAINT TRIGGER require_changeset_submission
        AFTER INSERT OR UPDATE ON changesets
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION leadtrace_require_changeset_submission();

        CREATE FUNCTION leadtrace_require_review_task_state()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            target_task_id uuid;
            changeset_state text;
            task_state text;
            expected_task_state text;
        BEGIN
            IF TG_TABLE_NAME = 'changesets' THEN
                target_task_id := NEW.review_task_id;
            ELSE
                target_task_id := NEW.id;
            END IF;
            SELECT c.workflow_state::text, rt.status::text
            INTO changeset_state, task_state
            FROM review_tasks rt
            LEFT JOIN changesets c ON c.review_task_id = rt.id
            WHERE rt.id = target_task_id;
            IF changeset_state IS NULL THEN
                RETURN NULL;
            END IF;
            expected_task_state := CASE
                WHEN changeset_state IN ('draft', 'revised_draft')
                    THEN 'in_progress'
                WHEN changeset_state = 'submitted'
                    THEN 'submitted'
                WHEN changeset_state = 'changes_requested'
                    THEN 'changes_requested'
                ELSE 'completed'
            END;
            IF task_state <> expected_task_state THEN
                RAISE EXCEPTION
                    'changeset and review task states are inconsistent: expected %, got %',
                    expected_task_state, task_state;
            END IF;
            RETURN NULL;
        END;
        $$;

        CREATE CONSTRAINT TRIGGER require_changeset_review_task_state
        AFTER INSERT OR UPDATE ON changesets
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION leadtrace_require_review_task_state();

        CREATE CONSTRAINT TRIGGER require_review_task_changeset_state
        AFTER INSERT OR UPDATE ON review_tasks
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION leadtrace_require_review_task_state();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS require_review_task_changeset_state "
        "ON review_tasks"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS require_changeset_review_task_state "
        "ON changesets"
    )
    op.execute("DROP FUNCTION IF EXISTS leadtrace_require_review_task_state()")
    op.execute(
        "DROP TRIGGER IF EXISTS validate_changeset_revision_update "
        "ON object_revisions"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS leadtrace_validate_changeset_revision_update()"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS validate_changeset_revision_insert "
        "ON object_revisions"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS leadtrace_validate_changeset_revision_insert()"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS require_changeset_submission ON changesets"
    )
    op.execute("DROP FUNCTION IF EXISTS leadtrace_require_changeset_submission()")
    op.execute(
        "DROP TRIGGER IF EXISTS validate_changeset_submission "
        "ON changeset_submissions"
    )
    op.execute("DROP FUNCTION IF EXISTS leadtrace_validate_changeset_submission()")
    op.execute(
        "DROP TRIGGER IF EXISTS protect_changeset_submission ON changeset_submissions"
    )
    op.execute("DROP FUNCTION IF EXISTS leadtrace_protect_changeset_submission()")
    op.execute("DROP FUNCTION IF EXISTS leadtrace_changeset_snapshot_hash(uuid)")
    op.execute("DROP FUNCTION IF EXISTS leadtrace_jsonb_sha256(jsonb)")
    op.execute("DROP FUNCTION IF EXISTS leadtrace_changeset_snapshot(uuid)")
    op.execute("DROP TRIGGER IF EXISTS protect_changeset_item ON changeset_items")
    op.execute("DROP FUNCTION IF EXISTS leadtrace_protect_changeset_item()")
    op.execute("DROP TRIGGER IF EXISTS protect_changeset_delete ON changesets")
    op.execute("DROP FUNCTION IF EXISTS leadtrace_protect_changeset_delete()")
    op.execute("DROP TRIGGER IF EXISTS validate_changeset_transition ON changesets")
    op.execute("DROP FUNCTION IF EXISTS leadtrace_validate_changeset_transition()")
    op.execute("DROP TRIGGER IF EXISTS validate_changeset_insert ON changesets")
    op.execute("DROP FUNCTION IF EXISTS leadtrace_validate_changeset_insert()")
    op.drop_index(
        "ix_changeset_submissions_changeset", table_name="changeset_submissions"
    )
    op.drop_table("changeset_submissions")
    op.drop_constraint(
        "fk_object_revisions_changeset_item",
        "object_revisions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_changeset_items_proposed_revision",
        "changeset_items",
        type_="foreignkey",
    )
    op.execute("ALTER TABLE object_revisions DISABLE TRIGGER trg_object_revisions_immutable")
    op.execute(
        "UPDATE object_revisions SET changeset_id = NULL "
        "WHERE changeset_id IS NOT NULL"
    )
    op.execute("ALTER TABLE object_revisions ENABLE TRIGGER trg_object_revisions_immutable")
    op.drop_index("ix_changeset_items_changeset", table_name="changeset_items")
    op.drop_table("changeset_items")
    op.drop_constraint(
        "uq_object_revisions_changeset_object_id",
        "object_revisions",
        type_="unique",
    )
    op.drop_index("ix_changesets_owner_state", table_name="changesets")
    op.drop_index("ix_changesets_paper_state", table_name="changesets")
    op.drop_table("changesets")
    op.drop_index("ix_review_tasks_paper_status", table_name="review_tasks")
    op.drop_index("uq_review_tasks_active_assignment", table_name="review_tasks")
    op.drop_index("ix_review_tasks_assignee_status", table_name="review_tasks")
    op.drop_table("review_tasks")
