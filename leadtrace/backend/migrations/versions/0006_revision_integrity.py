"""Make every persisted scientific revision content-immutable.

Revision ID: 0006_revision_integrity
Revises: 0005_imports
"""
from __future__ import annotations

from alembic import op


revision = "0006_revision_integrity"
down_revision = "0005_imports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION leadtrace_protect_immutable_revision()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            content_is_unchanged boolean;
            transition_is_allowed boolean;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'revision is immutable';
            END IF;

            content_is_unchanged :=
                (to_jsonb(NEW) - ARRAY['workflow_state', 'is_current_published'])
                =
                (to_jsonb(OLD) - ARRAY['workflow_state', 'is_current_published']);

            transition_is_allowed :=
                (OLD.workflow_state IN ('draft', 'revised_draft')
                 AND NEW.workflow_state = 'submitted'
                 AND NOT OLD.is_current_published
                 AND NOT NEW.is_current_published)
                OR
                (OLD.workflow_state = 'submitted'
                 AND NEW.workflow_state IN
                     ('changes_requested', 'rejected', 'approved')
                 AND NOT OLD.is_current_published
                 AND NOT NEW.is_current_published)
                OR
                (OLD.workflow_state = 'approved'
                 AND NEW.workflow_state = 'published'
                 AND NOT OLD.is_current_published)
                OR
                (OLD.workflow_state = 'published'
                 AND OLD.is_current_published
                 AND NEW.workflow_state = 'superseded'
                 AND NOT NEW.is_current_published);

            IF content_is_unchanged AND transition_is_allowed THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'revision is immutable';
        END;
        $$
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION leadtrace_protect_immutable_revision()
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
