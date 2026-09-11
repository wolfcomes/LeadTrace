"""Finalize release manifests and validate release item identity.

Revision ID: 0008_release_hardening
Revises: 0007_releases
"""
from __future__ import annotations

from alembic import op


revision = "0008_release_hardening"
down_revision = "0007_releases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE releases
        ADD COLUMN IF NOT EXISTS manifest_finalized boolean NOT NULL DEFAULT false
        """
    )
    op.execute("DROP TRIGGER IF EXISTS validate_release_item ON release_items")
    op.execute("DROP FUNCTION IF EXISTS leadtrace_validate_release_item()")
    op.execute("DROP TRIGGER IF EXISTS protect_release ON releases")
    op.execute("DROP FUNCTION IF EXISTS leadtrace_protect_release()")
    op.execute(
        """
        CREATE FUNCTION leadtrace_validate_release_item()
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
                ELSE
                    actual_paper_id := NULL;
            END CASE;
            IF actual_paper_id IS NULL OR actual_paper_id <> NEW.paper_id THEN
                RAISE EXCEPTION 'release item paper does not match object';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER validate_release_item
        BEFORE INSERT ON release_items
        FOR EACH ROW EXECUTE FUNCTION leadtrace_validate_release_item();
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
            IF (OLD.is_current AND NOT NEW.is_current
                AND (to_jsonb(NEW) - 'is_current') = (to_jsonb(OLD) - 'is_current'))
               OR ((NOT OLD.manifest_finalized) AND NEW.manifest_finalized
                AND (to_jsonb(NEW) - 'manifest_finalized') = (to_jsonb(OLD) - 'manifest_finalized'))
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
    op.execute("DROP TRIGGER IF EXISTS validate_release_item ON release_items")
    op.execute("DROP FUNCTION IF EXISTS leadtrace_validate_release_item()")
    op.execute("DROP TRIGGER IF EXISTS protect_release ON releases")
    op.execute("DROP FUNCTION IF EXISTS leadtrace_protect_release()")
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
    op.execute("ALTER TABLE releases DROP COLUMN IF EXISTS manifest_finalized")
