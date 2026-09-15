"""replace the empty legacy product schema with Paper-centric foundations

Revision ID: 0019_paper_centric_foundation
Revises: 0018_reviewer_scientific_workspace
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0019_paper_centric_foundation"
down_revision: str | None = "0018_reviewer_scientific_workspace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_LEGACY_BUSINESS_TABLES = (
    "crop_job_subscriptions",
    "papers",
    "revisioned_objects",
    "object_revisions",
    "compounds",
    "structures",
    "evidence_records",
    "activity_records",
    "lineages",
    "lineage_edges",
    "visual_regions",
    "visual_objects",
    "visual_object_region_bindings",
    "visual_object_asset_bindings",
    "visual_object_compound_bindings",
    "visual_object_relations",
    "molecule_proposals",
    "import_batches",
    "import_staging_records",
    "import_asset_links",
    "import_release_candidates",
    "import_candidate_decisions",
    "review_tasks",
    "changesets",
    "changeset_items",
    "changeset_submissions",
    "review_comments",
    "review_comment_events",
    "paper_review_scopes",
    "paper_review_attestations",
    "approval_decisions",
    "releases",
    "release_items",
    "release_operations",
    "release_artifact_manifests",
)

_LEGACY_DROP_ORDER = (
    "crop_job_subscriptions",
    "molecule_proposals",
    "paper_review_attestations",
    "paper_review_scopes",
    "approval_decisions",
    "review_comment_events",
    "review_comments",
    "changeset_submissions",
    "visual_object_relations",
    "visual_object_compound_bindings",
    "visual_object_asset_bindings",
    "visual_object_region_bindings",
    "import_candidate_decisions",
    "release_artifact_manifests",
    "release_items",
    "release_operations",
    "activity_records",
    "structures",
    "lineage_edges",
    "evidence_records",
    "visual_objects",
    "visual_regions",
    "lineages",
    "compounds",
)

_LEGACY_FUNCTIONS = (
    "leadtrace_changeset_snapshot(uuid)",
    "leadtrace_changeset_snapshot_hash(uuid)",
    "leadtrace_protect_approval_decision()",
    "leadtrace_protect_changeset_delete()",
    "leadtrace_protect_changeset_item()",
    "leadtrace_protect_changeset_submission()",
    "leadtrace_protect_immutable_revision()",
    "leadtrace_protect_release()",
    "leadtrace_protect_release_artifact_manifest()",
    "leadtrace_protect_release_item()",
    "leadtrace_protect_release_operation()",
    "leadtrace_reject_comment_history_mutation()",
    "leadtrace_reject_import_candidate_decision_mutation()",
    "leadtrace_reject_paper_review_evidence_mutation()",
    "leadtrace_require_changeset_submission()",
    "leadtrace_require_review_task_state()",
    "leadtrace_validate_changeset_insert()",
    "leadtrace_validate_changeset_revision_insert()",
    "leadtrace_validate_changeset_revision_update()",
    "leadtrace_validate_changeset_submission()",
    "leadtrace_validate_changeset_transition()",
    "leadtrace_validate_release_item()",
)


def _refuse_nonempty_legacy_schema() -> None:
    table_values = ", ".join(f"'{table}'" for table in _LEGACY_BUSINESS_TABLES)
    op.execute(
        sa.text(
            f"""
            DO $$
            DECLARE
                legacy_table text;
                has_rows boolean;
            BEGIN
                FOREACH legacy_table IN ARRAY ARRAY[{table_values}]
                LOOP
                    EXECUTE format(
                        'SELECT EXISTS (SELECT 1 FROM %I LIMIT 1)',
                        legacy_table
                    ) INTO has_rows;
                    IF has_rows THEN
                        RAISE EXCEPTION
                            'paper-centric migration refused: legacy table % contains business rows',
                            legacy_table
                            USING ERRCODE = '55000';
                    END IF;
                END LOOP;
            END;
            $$;
            """
        )
    )


def _retire_legacy_schema() -> None:
    op.drop_constraint(
        "fk_assets_import_batch_id",
        "assets",
        type_="foreignkey",
    )
    for constraint_name in (
        "audit_events_paper_id_fkey",
        "audit_events_changeset_id_fkey",
        "audit_events_release_id_fkey",
    ):
        op.drop_constraint(
            constraint_name,
            "audit_events",
            type_="foreignkey",
        )

    for table_name in _LEGACY_DROP_ORDER:
        op.drop_table(table_name)

    # Legacy revision and changeset tables form a deliberate FK cycle.
    op.drop_constraint(
        "fk_object_revisions_changeset_item",
        "object_revisions",
        type_="foreignkey",
    )
    op.drop_table("changeset_items")
    op.drop_table("object_revisions")
    op.drop_table("changesets")
    op.drop_table("review_tasks")
    op.drop_table("releases")
    op.drop_table("import_asset_links")
    op.drop_table("import_release_candidates")
    op.drop_table("import_staging_records")
    op.drop_table("import_batches")
    op.drop_table("papers")
    op.drop_table("revisioned_objects")

    for function_signature in _LEGACY_FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {function_signature}")


def _create_catalog_tables() -> None:
    op.create_table(
        "paper_sources",
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_root_key", sa.String(length=128), nullable=False),
        sa.Column("source_key", sa.String(length=1024), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column(
            "integrity_state",
            sa.Enum(
                "registered",
                "verified",
                "missing",
                "corrupt",
                name="paper_source_integrity_state",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.CheckConstraint(
            "btrim(source_root_key) <> ''",
            name="ck_paper_sources_root_key_required",
        ),
        sa.CheckConstraint(
            "source_root_key ~ '^[A-Za-z0-9][A-Za-z0-9._-]*$' "
            "AND source_root_key NOT IN ('.', '..')",
            name="ck_paper_sources_root_key_logical",
        ),
        sa.CheckConstraint(
            "btrim(source_key) <> ''",
            name="ck_paper_sources_source_key_required",
        ),
        sa.CheckConstraint(
            r"source_key !~ '^/' "
            r"AND source_key !~ '/$' "
            r"AND source_key !~ '(^|/)\.\.?(/|$)' "
            r"AND source_key NOT LIKE '%//%' "
            r"AND strpos(source_key, chr(92)) = 0",
            name="ck_paper_sources_source_key_relative_posix",
        ),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_paper_sources_sha256",
        ),
        sa.CheckConstraint(
            "byte_size > 0",
            name="ck_paper_sources_positive_bytes",
        ),
        sa.CheckConstraint(
            "page_count > 0",
            name="ck_paper_sources_positive_pages",
        ),
        sa.CheckConstraint(
            "integrity_state IN ('registered', 'verified', 'missing', 'corrupt')",
            name="ck_paper_sources_integrity_state",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["assets.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", name="uq_paper_sources_asset"),
        sa.UniqueConstraint(
            "source_root_key",
            "source_key",
            name="uq_paper_sources_logical_key",
        ),
        sa.UniqueConstraint("sha256", name="uq_paper_sources_sha256"),
    )

    op.create_table(
        "papers",
        sa.Column("paper_key", sa.String(length=128), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=1024), nullable=False),
        sa.Column("journal", sa.String(length=255), nullable=False),
        sa.Column("publication_year", sa.Integer(), nullable=False),
        sa.Column("volume", sa.String(length=64), nullable=False),
        sa.Column("issue", sa.String(length=64), nullable=False),
        sa.Column("doi", sa.String(length=255), nullable=True),
        sa.Column(
            "catalog_state",
            sa.Enum(
                "extracted",
                "verified",
                "source_error",
                name="paper_catalog_state",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.CheckConstraint("btrim(paper_key) <> ''", name="ck_papers_key_required"),
        sa.CheckConstraint("btrim(title) <> ''", name="ck_papers_title_required"),
        sa.CheckConstraint(
            "btrim(journal) <> ''", name="ck_papers_journal_required"
        ),
        sa.CheckConstraint(
            "publication_year BETWEEN 1000 AND 9999",
            name="ck_papers_publication_year",
        ),
        sa.CheckConstraint("btrim(volume) <> ''", name="ck_papers_volume_required"),
        sa.CheckConstraint("btrim(issue) <> ''", name="ck_papers_issue_required"),
        sa.CheckConstraint(
            "doi IS NULL OR btrim(doi) <> ''",
            name="ck_papers_doi_nonempty",
        ),
        sa.CheckConstraint(
            "catalog_state IN ('extracted', 'verified', 'source_error')",
            name="ck_papers_catalog_state",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["paper_sources.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("doi", name="uq_papers_doi"),
        sa.UniqueConstraint("paper_key", name="uq_papers_paper_key"),
        sa.UniqueConstraint("source_id", name="uq_papers_source"),
    )


def _create_workspace_tables() -> None:
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
                "assigned",
                "submitted",
                "changes_requested",
                "approved",
                name="review_task_state",
                native_enum=False,
                length=24,
            ),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.CheckConstraint("version > 0", name="ck_review_tasks_positive_version"),
        sa.CheckConstraint(
            "status IN ('assigned', 'submitted', 'changes_requested', 'approved')",
            name="ck_review_tasks_status",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_reviewer_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"], ["papers.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "paper_id", name="uq_review_tasks_id_paper"),
    )
    op.create_index(
        "ix_review_tasks_assignee_status",
        "review_tasks",
        ["assigned_reviewer_id", "status"],
    )
    op.create_index(
        "ix_review_tasks_paper_status",
        "review_tasks",
        ["paper_id", "status"],
    )
    op.create_index(
        "uq_review_tasks_active_paper",
        "review_tasks",
        ["paper_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'approved'"),
    )

    op.create_table(
        "paper_workspaces",
        sa.Column("paper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "editing",
                "submitted",
                "approved",
                name="paper_workspace_state",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.CheckConstraint(
            "version > 0", name="ck_paper_workspaces_positive_version"
        ),
        sa.CheckConstraint(
            "state IN ('editing', 'submitted', 'approved')",
            name="ck_paper_workspaces_state",
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"], ["papers.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["review_task_id", "paper_id"],
            ["review_tasks.id", "review_tasks.paper_id"],
            name="fk_paper_workspaces_task_paper",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "paper_id", name="uq_paper_workspaces_id_paper"
        ),
        sa.UniqueConstraint(
            "review_task_id", name="uq_paper_workspaces_review_task"
        ),
    )
    op.create_index(
        "ix_paper_workspaces_paper_state",
        "paper_workspaces",
        ["paper_id", "state"],
    )

    op.create_table(
        "paper_section_reviews",
        sa.Column("paper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "section_key",
            sa.Enum(
                "bibliography",
                "compounds",
                "structures",
                "lineages",
                "edge_evidence",
                "activities",
                name="paper_section_key",
                native_enum=False,
                length=24,
            ),
            nullable=False,
        ),
        sa.Column(
            "state",
            sa.Enum(
                "pending",
                "completed",
                "not_reported",
                name="paper_section_state",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.CheckConstraint(
            "section_key IN ('bibliography', 'compounds', 'structures', "
            "'lineages', 'edge_evidence', 'activities')",
            name="ck_paper_section_reviews_key",
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'completed', 'not_reported')",
            name="ck_paper_section_reviews_state",
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"], ["papers.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "paper_id"],
            ["paper_workspaces.id", "paper_workspaces.paper_id"],
            name="fk_paper_section_reviews_workspace_paper",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "section_key",
            name="uq_paper_section_reviews_workspace_section",
        ),
    )
    op.create_index(
        "ix_paper_section_reviews_paper",
        "paper_section_reviews",
        ["paper_id", "workspace_id"],
    )

    op.create_table(
        "change_events",
        sa.Column("paper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column(
            "before_value",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "after_value",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "actor_kind",
            sa.Enum(
                "reviewer",
                "admin",
                "ai",
                "system",
                name="change_actor_kind",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ai_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "btrim(entity_type) <> ''",
            name="ck_change_events_entity_type_required",
        ),
        sa.CheckConstraint(
            "btrim(action) <> ''",
            name="ck_change_events_action_required",
        ),
        sa.CheckConstraint(
            "before_value IS NOT NULL OR after_value IS NOT NULL",
            name="ck_change_events_has_value",
        ),
        sa.CheckConstraint(
            "actor_kind IN ('reviewer', 'admin', 'ai', 'system')",
            name="ck_change_events_actor_kind",
        ),
        sa.CheckConstraint(
            "((actor_kind IN ('reviewer', 'admin') AND actor_id IS NOT NULL) "
            "OR (actor_kind IN ('ai', 'system') AND actor_id IS NULL))",
            name="ck_change_events_actor_identity",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"], ["papers.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "paper_id"],
            ["paper_workspaces.id", "paper_workspaces.paper_id"],
            name="fk_change_events_workspace_paper",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_change_events_workspace_time",
        "change_events",
        ["workspace_id", "occurred_at"],
    )
    op.create_index(
        "ix_change_events_entity",
        "change_events",
        ["entity_type", "entity_id"],
    )
    op.create_index(
        "ix_change_events_paper_time",
        "change_events",
        ["paper_id", "occurred_at"],
    )
    op.execute(
        """
        CREATE FUNCTION leadtrace_reject_change_event_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Change events are append-only'
                USING ERRCODE = '55000';
        END;
        $$;
        CREATE TRIGGER trg_change_events_append_only
        BEFORE UPDATE OR DELETE ON change_events
        FOR EACH ROW EXECUTE FUNCTION leadtrace_reject_change_event_mutation();
        """
    )


def upgrade() -> None:
    _refuse_nonempty_legacy_schema()
    _retire_legacy_schema()
    _create_catalog_tables()
    _create_workspace_tables()
    op.create_foreign_key(
        "audit_events_paper_id_fkey",
        "audit_events",
        "papers",
        ["paper_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    raise RuntimeError(
        "paper-centric foundation is irreversible; restore the mandatory "
        "pre-cutover PostgreSQL backup"
    )
