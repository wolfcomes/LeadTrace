"""Add immutable administrative approval decisions and release pointer support.

Revision ID: 0013_approvals
Revises: 0012_molecule_objects
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0013_approvals"
down_revision: str | None = "0012_molecule_objects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_ASSET_REFERENCE_FIELDS = frozenset(
    {"asset_id", "asset_ids", "drawing_asset_id", "source_asset_id"}
)


def _stable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _stable(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_stable(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    return value


def _canonical_hash(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        _stable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _uuid(value: object) -> UUID | None:
    if value is None or value == "":
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _extract_asset_ids(value: object) -> set[UUID]:
    found: set[UUID] = set()

    def visit(candidate: object, key: str | None = None) -> None:
        if isinstance(candidate, Mapping):
            for nested_key, nested_value in candidate.items():
                visit(nested_value, str(nested_key))
            return
        if isinstance(candidate, (list, tuple)):
            for nested_value in candidate:
                visit(nested_value, key)
            return
        if key not in _ASSET_REFERENCE_FIELDS or candidate is None or candidate == "":
            return
        parsed = _uuid(candidate)
        if parsed is not None:
            found.add(parsed)

    visit(value)
    return found


def _rows(
    connection: sa.engine.Connection,
    statement: str,
    parameters: Mapping[str, object],
) -> list[dict[str, object]]:
    return [
        _stable(dict(row))
        for row in connection.execute(sa.text(statement), dict(parameters)).mappings()
    ]


def _rows_for_ids(
    connection: sa.engine.Connection,
    statement: str,
    *,
    parameter: str,
    values: set[UUID],
) -> list[dict[str, object]]:
    if not values:
        return []
    query = sa.text(statement).bindparams(sa.bindparam(parameter, expanding=True))
    return [
        _stable(dict(row))
        for row in connection.execute(
            query,
            {parameter: sorted(values, key=str)},
        ).mappings()
    ]


def _build_release_artifact_snapshot(
    connection: sa.engine.Connection,
    release_id: UUID,
) -> dict[str, object]:
    items = _rows(
        connection,
        """
        SELECT ri.object_id, ri.object_kind, revisions.snapshot,
               structures.compound_id AS structure_compound_id,
               activities.compound_id AS activity_compound_id,
               edges.lineage_id AS edge_lineage_id,
               edges.parent_compound_id AS edge_parent_compound_id,
               edges.derived_compound_id AS edge_derived_compound_id
        FROM release_items AS ri
        JOIN object_revisions AS revisions ON revisions.id = ri.revision_id
        LEFT JOIN structures ON structures.id = ri.object_id
        LEFT JOIN activity_records AS activities ON activities.id = ri.object_id
        LEFT JOIN lineage_edges AS edges ON edges.id = ri.object_id
        WHERE ri.release_id = :release_id
        ORDER BY ri.manifest_order, ri.id
        """,
        {"release_id": release_id},
    )
    visual_object_ids = {
        parsed
        for item in items
        if item["object_kind"] == "visual_object"
        and (parsed := _uuid(item["object_id"])) is not None
    }
    region_ids = {
        parsed
        for item in items
        if item["object_kind"] == "visual_region"
        and (parsed := _uuid(item["object_id"])) is not None
    }
    compound_ids = {
        parsed
        for item in items
        if item["object_kind"] == "compound"
        and (parsed := _uuid(item["object_id"])) is not None
    }
    object_references: dict[str, dict[str, object]] = {}
    for item in items:
        object_id = str(item["object_id"])
        references: dict[str, object] = {}
        if item["object_kind"] == "structure" and item["structure_compound_id"]:
            references["compound_id"] = str(item["structure_compound_id"])
        elif item["object_kind"] == "activity" and item["activity_compound_id"]:
            references["compound_id"] = str(item["activity_compound_id"])
        elif item["object_kind"] == "lineage_edge" and item["edge_lineage_id"]:
            references = {
                "lineage_id": str(item["edge_lineage_id"]),
                "parent_compound_id": (
                    str(item["edge_parent_compound_id"])
                    if item["edge_parent_compound_id"]
                    else None
                ),
                "derived_compound_id": str(item["edge_derived_compound_id"]),
            }
        if references:
            object_references[object_id] = references

    region_bindings = _rows_for_ids(
        connection,
        """
        SELECT * FROM visual_object_region_bindings
        WHERE visual_object_id IN :visual_object_ids
        ORDER BY id
        """,
        parameter="visual_object_ids",
        values=visual_object_ids,
    )
    region_bindings = [
        row
        for row in region_bindings
        if _uuid(row.get("region_id")) in region_ids
    ]
    asset_bindings = _rows_for_ids(
        connection,
        """
        SELECT * FROM visual_object_asset_bindings
        WHERE visual_object_id IN :visual_object_ids
        ORDER BY id
        """,
        parameter="visual_object_ids",
        values=visual_object_ids,
    )
    compound_bindings = _rows_for_ids(
        connection,
        """
        SELECT * FROM visual_object_compound_bindings
        WHERE visual_object_id IN :visual_object_ids
        ORDER BY id
        """,
        parameter="visual_object_ids",
        values=visual_object_ids,
    )
    compound_bindings = [
        row
        for row in compound_bindings
        if _uuid(row.get("compound_id")) in compound_ids
    ]
    relations: list[dict[str, object]] = []
    if visual_object_ids:
        relation_query = sa.text(
            """
            SELECT * FROM visual_object_relations
            WHERE source_object_id IN :source_ids
               OR target_object_id IN :target_ids
            ORDER BY id
            """
        ).bindparams(
            sa.bindparam("source_ids", expanding=True),
            sa.bindparam("target_ids", expanding=True),
        )
        ordered_ids = sorted(visual_object_ids, key=str)
        relations = [
            _stable(dict(row))
            for row in connection.execute(
                relation_query,
                {"source_ids": ordered_ids, "target_ids": ordered_ids},
            ).mappings()
        ]
        relations = [
            row
            for row in relations
            if _uuid(row.get("source_object_id")) in visual_object_ids
            and _uuid(row.get("target_object_id")) in visual_object_ids
        ]
    region_rows = _rows_for_ids(
        connection,
        """
        SELECT id AS region_id, asset_id FROM visual_regions
        WHERE id IN :region_ids
        ORDER BY id
        """,
        parameter="region_ids",
        values=region_ids,
    )
    region_assets = [
        {
            "region_id": str(row["region_id"]),
            "asset_id": str(row["asset_id"]) if row["asset_id"] else None,
        }
        for row in region_rows
    ]
    snapshot: dict[str, object] = {
        "bindings": {
            "visual_object_regions": region_bindings,
            "visual_object_assets": asset_bindings,
            "visual_object_compounds": compound_bindings,
            "visual_object_relations": relations,
        },
        "region_assets": region_assets,
        "release_targets": {
            "visual_object_ids": sorted(str(value) for value in visual_object_ids),
            "region_ids": sorted(str(value) for value in region_ids),
            "compound_ids": sorted(str(value) for value in compound_ids),
        },
        "object_references": object_references,
        "capture_mode": "migration_best_effort",
    }
    asset_ids: set[UUID] = set()
    for item in items:
        asset_ids.update(_extract_asset_ids(item["snapshot"]))
    for binding in asset_bindings:
        parsed = _uuid(binding.get("asset_id"))
        if parsed is not None:
            asset_ids.add(parsed)
    for region in region_assets:
        parsed = _uuid(region.get("asset_id"))
        if parsed is not None:
            asset_ids.add(parsed)

    pending = list(asset_ids)
    assets: dict[UUID, dict[str, object]] = {}
    while pending:
        asset_id = pending.pop()
        if asset_id in assets:
            continue
        rows = _rows(
            connection,
            "SELECT * FROM assets WHERE id = :asset_id",
            {"asset_id": asset_id},
        )
        if not rows:
            continue
        asset = rows[0]
        assets[asset_id] = asset
        source_id = _uuid(asset.get("source_asset_id"))
        if source_id is not None and source_id not in assets:
            asset_ids.add(source_id)
            pending.append(source_id)
    snapshot["asset_manifest"] = [
        assets[asset_id] for asset_id in sorted(assets, key=str)
    ]
    snapshot["asset_ids"] = sorted(str(asset_id) for asset_id in asset_ids)
    snapshot["schema_version"] = 1
    return _stable(snapshot)


def _backfill_release_artifact_manifests() -> None:
    if context.is_offline_mode():
        op.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM releases) THEN
                    RAISE EXCEPTION
                        'offline migration requires an empty legacy releases table';
                END IF;
            END;
            $$
            """
        )
        return
    connection = op.get_bind()
    release_ids = list(
        connection.scalars(sa.text("SELECT id FROM releases ORDER BY id"))
    )
    for release_id in release_ids:
        snapshot = _build_release_artifact_snapshot(connection, release_id)
        connection.execute(
            sa.text(
                """
                INSERT INTO release_artifact_manifests (
                    release_id, schema_version, snapshot, content_hash
                ) VALUES (
                    :release_id, 1, CAST(:snapshot AS jsonb), :content_hash
                )
                """
            ),
            {
                "release_id": release_id,
                "snapshot": json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                "content_hash": _canonical_hash(snapshot),
            },
        )


def upgrade() -> None:
    binding_tables = {
        "visual_object_region_bindings": (
            "ix_visual_object_region_changeset",
            "concat('region:', visual_object_id::text, ':', region_id::text)",
            "uq_visual_object_region_binding",
        ),
        "visual_object_asset_bindings": (
            "ix_visual_object_asset_changeset",
            "concat('asset:', visual_object_id::text, ':', asset_id::text)",
            "uq_visual_object_asset_binding",
        ),
        "visual_object_compound_bindings": (
            "ix_visual_object_compound_changeset",
            "concat('compound:', visual_object_id::text, ':', compound_id::text, ':', label)",
            "uq_visual_object_compound_label",
        ),
        "visual_object_relations": (
            "ix_visual_object_relations_changeset",
            "concat('relation:', source_object_id::text, ':', target_object_id::text, ':', relation_type)",
            "uq_visual_object_relation",
        ),
    }
    for table_name, (index_name, logical_key_template, unique_name) in binding_tables.items():
        op.add_column(
            table_name,
            sa.Column("changeset_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column("operation", sa.String(length=16), nullable=False, server_default="add"),
        )
        op.add_column(
            table_name,
            sa.Column("logical_key", sa.String(length=512), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column("base_hash", sa.String(length=64), nullable=True),
        )
        op.execute(
            sa.text(
                f"UPDATE {table_name} SET logical_key = {logical_key_template}"
            )
        )
        op.alter_column(table_name, "logical_key", nullable=False)
        op.alter_column(table_name, "operation", server_default=None)
        op.drop_constraint(unique_name, table_name, type_="unique")
        op.create_foreign_key(
            f"fk_{table_name}_changeset",
            table_name,
            "changesets",
            ["changeset_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        op.create_index(
            index_name,
            table_name,
            ["changeset_id"],
        )
        op.create_unique_constraint(
            unique_name,
            table_name,
            ["changeset_id", "logical_key"],
        )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION leadtrace_changeset_snapshot(target_changeset_id uuid)
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
                ),
                'binding_delta', jsonb_build_object(
                    'visual_object_regions', COALESCE(
                        (
                            SELECT jsonb_agg(to_jsonb(binding) ORDER BY binding.id)
                            FROM visual_object_region_bindings binding
                            WHERE binding.changeset_id = c.id
                        ),
                        '[]'::jsonb
                    ),
                    'visual_object_assets', COALESCE(
                        (
                            SELECT jsonb_agg(to_jsonb(binding) ORDER BY binding.id)
                            FROM visual_object_asset_bindings binding
                            WHERE binding.changeset_id = c.id
                        ),
                        '[]'::jsonb
                    ),
                    'visual_object_compounds', COALESCE(
                        (
                            SELECT jsonb_agg(to_jsonb(binding) ORDER BY binding.id)
                            FROM visual_object_compound_bindings binding
                            WHERE binding.changeset_id = c.id
                        ),
                        '[]'::jsonb
                    ),
                    'visual_object_relations', COALESCE(
                        (
                            SELECT jsonb_agg(to_jsonb(binding) ORDER BY binding.id)
                            FROM visual_object_relations binding
                            WHERE binding.changeset_id = c.id
                        ),
                        '[]'::jsonb
                    )
                )
            )
            FROM changesets c
            WHERE c.id = target_changeset_id
        $$;
        """
    )
    op.create_table(
        "approval_decisions",
        sa.Column("changeset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("submission_version", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "decision IN ('approve', 'request_changes', 'reject')",
            name="ck_approval_decisions_decision",
        ),
        sa.CheckConstraint(
            "char_length(snapshot_hash) = 64",
            name="ck_approval_decisions_snapshot_hash",
        ),
        sa.ForeignKeyConstraint(
            ["changeset_id"], ["changesets.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "changeset_id",
            "submission_version",
            "decision",
            name="uq_approval_decisions_submission_decision",
        ),
    )
    op.create_index(
        "ix_approval_decisions_changeset",
        "approval_decisions",
        ["changeset_id", "created_at"],
    )
    op.create_table(
        "release_artifact_manifests",
        sa.Column("release_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "schema_version > 0",
            name="ck_release_artifact_manifests_schema_version",
        ),
        sa.CheckConstraint(
            "char_length(content_hash) = 64",
            name="ck_release_artifact_manifests_content_hash",
        ),
        sa.ForeignKeyConstraint(
            ["release_id"], ["releases.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("release_id"),
    )
    op.create_table(
        "release_operations",
        sa.Column("operation_type", sa.String(length=16), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("target_release_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("replaced_release_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("result_release_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("delta", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "operation_type IN ('publish', 'rollback')",
            name="ck_release_operations_type",
        ),
        sa.CheckConstraint(
            "char_length(request_hash) = 64",
            name="ck_release_operations_request_hash",
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["target_release_id"], ["releases.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["replaced_release_id"], ["releases.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["result_release_id"], ["releases.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "actor_id",
            "operation_type",
            "idempotency_key",
            name="uq_release_operations_actor_key",
        ),
    )
    op.create_index(
        "ix_release_operations_result",
        "release_operations",
        ["result_release_id"],
    )
    _backfill_release_artifact_manifests()
    op.execute(
        """
        CREATE FUNCTION leadtrace_protect_approval_decision()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'approval decision is immutable'; END;
        $$;
        CREATE TRIGGER protect_approval_decision
        BEFORE UPDATE OR DELETE ON approval_decisions
        FOR EACH ROW EXECUTE FUNCTION leadtrace_protect_approval_decision();
        """
    )
    op.execute(
        """
        CREATE FUNCTION leadtrace_protect_release_operation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'release operation is immutable'; END;
        $$;
        CREATE TRIGGER protect_release_operation
        BEFORE UPDATE OR DELETE ON release_operations
        FOR EACH ROW EXECUTE FUNCTION leadtrace_protect_release_operation();
        """
    )
    op.execute(
        """
        CREATE FUNCTION leadtrace_protect_release_artifact_manifest()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'release artifact manifest is immutable'; END;
        $$;
        CREATE TRIGGER protect_release_artifact_manifest
        BEFORE UPDATE OR DELETE ON release_artifact_manifests
        FOR EACH ROW EXECUTE FUNCTION leadtrace_protect_release_artifact_manifest();
        """
    )
    # A prepared release is finalized before switching the public pointer. The
    # pointer update itself is the only mutable release metadata operation.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION leadtrace_protect_release()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'release is immutable'; END IF;
            IF (OLD.is_current AND NOT NEW.is_current
                AND (to_jsonb(NEW) - 'is_current') = (to_jsonb(OLD) - 'is_current'))
               OR ((NOT OLD.is_current AND NEW.is_current
                AND (to_jsonb(NEW) - 'is_current') = (to_jsonb(OLD) - 'is_current')))
               OR ((NOT OLD.manifest_finalized) AND NEW.manifest_finalized
                AND (to_jsonb(NEW) - 'manifest_finalized') = (to_jsonb(OLD) - 'manifest_finalized'))
            THEN RETURN NEW; END IF;
            RAISE EXCEPTION 'release is immutable';
        END;
        $$;
        """
    )


def downgrade() -> None:
    # Restore the 0012 schema contract before removing approval/release tables.
    # The snapshot trigger in 0009 expects this function shape on re-upgrade.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION leadtrace_changeset_snapshot(target_changeset_id uuid)
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
        """
    )
    binding_tables = {
        "visual_object_region_bindings": (
            "ix_visual_object_region_changeset",
            "uq_visual_object_region_binding",
        ),
        "visual_object_asset_bindings": (
            "ix_visual_object_asset_changeset",
            "uq_visual_object_asset_binding",
        ),
        "visual_object_compound_bindings": (
            "ix_visual_object_compound_changeset",
            "uq_visual_object_compound_label",
        ),
        "visual_object_relations": (
            "ix_visual_object_relations_changeset",
            "uq_visual_object_relation",
        ),
    }
    for table_name, (index_name, unique_name) in binding_tables.items():
        # The 0012 schema has no changeset-scoped binding delta representation.
        # Discard draft operations before restoring its global logical uniques.
        op.execute(
            sa.text(f"DELETE FROM {table_name} WHERE changeset_id IS NOT NULL")
        )
        op.drop_constraint(unique_name, table_name, type_="unique")
        op.create_unique_constraint(
            unique_name,
            table_name,
            {
                "visual_object_region_bindings": ["visual_object_id", "region_id"],
                "visual_object_asset_bindings": ["visual_object_id", "asset_id"],
                "visual_object_compound_bindings": [
                    "visual_object_id", "compound_id", "label"
                ],
                "visual_object_relations": [
                    "source_object_id", "target_object_id", "relation_type"
                ],
            }[table_name],
        )
        op.drop_index(index_name, table_name=table_name)
        op.drop_constraint(
            f"fk_{table_name}_changeset",
            table_name,
            type_="foreignkey",
        )
        op.drop_column(table_name, "base_hash")
        op.drop_column(table_name, "logical_key")
        op.drop_column(table_name, "operation")
        op.drop_column(table_name, "changeset_id")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION leadtrace_protect_release()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'release is immutable'; END IF;
            IF (OLD.is_current AND NOT NEW.is_current
                AND (to_jsonb(NEW) - 'is_current') = (to_jsonb(OLD) - 'is_current'))
               OR ((NOT OLD.manifest_finalized) AND NEW.manifest_finalized
                AND (to_jsonb(NEW) - 'manifest_finalized') = (to_jsonb(OLD) - 'manifest_finalized'))
            THEN RETURN NEW; END IF;
            RAISE EXCEPTION 'release is immutable';
        END;
        $$;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS protect_approval_decision ON approval_decisions")
    op.execute("DROP FUNCTION IF EXISTS leadtrace_protect_approval_decision()")
    op.execute(
        "DROP TRIGGER IF EXISTS protect_release_artifact_manifest "
        "ON release_artifact_manifests"
    )
    op.execute("DROP FUNCTION IF EXISTS leadtrace_protect_release_artifact_manifest()")
    op.execute("DROP TRIGGER IF EXISTS protect_release_operation ON release_operations")
    op.execute("DROP FUNCTION IF EXISTS leadtrace_protect_release_operation()")
    op.drop_index("ix_release_operations_result", table_name="release_operations")
    op.drop_table("release_operations")
    op.drop_table("release_artifact_manifests")
    op.drop_index("ix_approval_decisions_changeset", table_name="approval_decisions")
    op.drop_table("approval_decisions")
