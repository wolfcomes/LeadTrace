from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assets.models import Asset
from app.activities.models import Activity
from app.lineages.models import LineageEdge
from app.molecule_proposals.models import MoleculeProposal
from app.releases.models import ReleaseArtifactManifest, ReleaseItem
from app.revisions.models import ObjectRevision
from app.reviews.models import Changeset
from app.structures.models import Structure
from app.visual_objects.models import (
    VisualObjectAssetBinding,
    VisualObjectCompoundBinding,
    VisualObjectRegionBinding,
    VisualObjectRelation,
    VisualRegion,
)


ASSET_REFERENCE_FIELDS = frozenset(
    {
        "asset_id",
        "asset_ids",
        "crop_asset_id",
        "drawing_asset_id",
        "source_asset_id",
    }
)
BINDING_COLLECTIONS = (
    "visual_object_regions",
    "visual_object_assets",
    "visual_object_compounds",
    "visual_object_relations",
)


def stable_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): stable_value(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [stable_value(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    return value


def canonical_hash(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        stable_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def binding_base_hash(row: Mapping[str, object]) -> str:
    values = {
        str(key): str(value)
        for key, value in row.items()
        if key not in {"changeset_id", "operation", "base_hash"}
    }
    return hashlib.sha256(
        json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _canonical_binding_logical_key(
    collection: str,
    row: Mapping[str, object],
) -> str:
    if collection == "visual_object_regions":
        return f"region:{row.get('visual_object_id')}:{row.get('region_id')}"
    if collection == "visual_object_assets":
        return f"asset:{row.get('visual_object_id')}:{row.get('asset_id')}"
    if collection == "visual_object_compounds":
        return (
            f"compound:{row.get('visual_object_id')}:"
            f"{row.get('compound_id')}:{row.get('label')}"
        )
    if collection == "visual_object_relations":
        return (
            f"relation:{row.get('source_object_id')}:"
            f"{row.get('target_object_id')}:{row.get('relation_type')}"
        )
    raise ValueError(f"Unknown binding collection: {collection}")


def binding_logical_key(collection: str, row: Mapping[str, object]) -> str:
    canonical = _canonical_binding_logical_key(collection, row)
    if "logical_key" in row:
        saved = row["logical_key"]
        if saved is None or saved == "":
            raise ValueError("Persisted binding logical key is empty")
        if str(saved) != canonical:
            raise ValueError("Binding logical key does not match its identity fields")
    return canonical


def frozen_base_binding(
    session: Session,
    changeset: Changeset,
    collection: str,
    binding_id: UUID,
) -> dict[str, object]:
    if collection not in BINDING_COLLECTIONS:
        raise ValueError(f"Unknown binding collection: {collection}")
    artifact = get_release_artifact_manifest(session, changeset.base_release_id)
    bindings = artifact.snapshot.get("bindings") if artifact is not None else None
    rows = bindings.get(collection) if isinstance(bindings, Mapping) else None
    if not isinstance(rows, list):
        raise ValueError("Binding source is not present in the frozen base release")
    for row in rows:
        if isinstance(row, Mapping) and str(row.get("id")) == str(binding_id):
            return stable_value(dict(row))
    raise ValueError("Binding source is not present in the frozen base release")


def frozen_base_binding_by_key(
    session: Session,
    changeset: Changeset,
    collection: str,
    logical_key: str,
) -> dict[str, object] | None:
    if collection not in BINDING_COLLECTIONS:
        raise ValueError(f"Unknown binding collection: {collection}")
    artifact = get_release_artifact_manifest(session, changeset.base_release_id)
    bindings = artifact.snapshot.get("bindings") if artifact is not None else None
    rows = bindings.get(collection) if isinstance(bindings, Mapping) else None
    if not isinstance(rows, list):
        return None
    for row in rows:
        if (
            isinstance(row, Mapping)
            and binding_logical_key(collection, row) == logical_key
        ):
            return stable_value(dict(row))
    return None


def row_snapshot(record: object) -> dict[str, object]:
    return {
        column.name: stable_value(getattr(record, column.name))
        for column in record.__table__.columns  # type: ignore[attr-defined]
    }


def extract_asset_ids(value: object) -> set[UUID]:
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
        if key not in ASSET_REFERENCE_FIELDS or candidate in {None, ""}:
            return
        try:
            found.add(UUID(str(candidate)))
        except (TypeError, ValueError, AttributeError):
            return

    visit(value)
    return found


def _binding_rows_for_visual_objects(
    session: Session,
    visual_object_ids: set[UUID],
    *,
    changeset_id: UUID | None = None,
) -> dict[str, list[dict[str, object]]]:
    filters = (
        VisualObjectRegionBinding.changeset_id == changeset_id,
        VisualObjectAssetBinding.changeset_id == changeset_id,
        VisualObjectCompoundBinding.changeset_id == changeset_id,
        VisualObjectRelation.changeset_id == changeset_id,
    )
    statements = (
        select(VisualObjectRegionBinding).where(
            VisualObjectRegionBinding.visual_object_id.in_(visual_object_ids)
        ),
        select(VisualObjectAssetBinding).where(
            VisualObjectAssetBinding.visual_object_id.in_(visual_object_ids)
        ),
        select(VisualObjectCompoundBinding).where(
            VisualObjectCompoundBinding.visual_object_id.in_(visual_object_ids)
        ),
        select(VisualObjectRelation).where(
            VisualObjectRelation.source_object_id.in_(visual_object_ids)
            | VisualObjectRelation.target_object_id.in_(visual_object_ids)
        ),
    )
    models = (
        VisualObjectRegionBinding,
        VisualObjectAssetBinding,
        VisualObjectCompoundBinding,
        VisualObjectRelation,
    )
    rows: dict[str, list[dict[str, object]]] = {}
    for collection, statement, model, attribution_filter in zip(
        BINDING_COLLECTIONS,
        statements,
        models,
        filters,
        strict=True,
    ):
        if changeset_id is not None:
            statement = statement.where(attribution_filter)
        records = session.scalars(statement.order_by(model.id))
        rows[collection] = [row_snapshot(record) for record in records]
    return rows


def binding_delta_for_changeset(
    session: Session,
    changeset: Changeset,
    *,
    visual_object_ids: set[UUID],
) -> dict[str, list[dict[str, object]]]:
    submitted = changeset.submitted_snapshot
    if isinstance(submitted, Mapping):
        frozen = submitted.get("binding_delta")
        if isinstance(frozen, Mapping):
            return {
                collection: [
                    stable_value(dict(row))
                    for row in frozen.get(collection, [])
                    if isinstance(row, Mapping)
                ]
                for collection in BINDING_COLLECTIONS
            }
    return _binding_rows_for_visual_objects(
        session,
        visual_object_ids,
        changeset_id=changeset.id,
    )


def draft_binding_delta_for_changeset(
    session: Session,
    changeset_id: UUID,
) -> dict[str, list[dict[str, object]]]:
    models = (
        VisualObjectRegionBinding,
        VisualObjectAssetBinding,
        VisualObjectCompoundBinding,
        VisualObjectRelation,
    )
    return {
        collection: [
            row_snapshot(record)
            for record in session.scalars(
                select(model)
                .where(model.changeset_id == changeset_id)
                .order_by(model.id)
            )
        ]
        for collection, model in zip(BINDING_COLLECTIONS, models, strict=True)
    }


def merge_binding_snapshots(
    base: Mapping[str, object],
    delta: Mapping[str, object],
) -> dict[str, list[dict[str, object]]]:
    merged: dict[str, list[dict[str, object]]] = {}
    for collection in BINDING_COLLECTIONS:
        base_rows = [
            dict(row)
            for row in base.get(collection, [])
            if isinstance(row, Mapping)
        ]
        delta_rows = [
            dict(row)
            for row in delta.get(collection, [])
            if isinstance(row, Mapping)
        ]
        frozen_by_key: dict[str, dict[str, object]] = {}
        for row in base_rows:
            key = binding_logical_key(collection, row)
            if key in frozen_by_key:
                raise ValueError("Binding base contains a duplicate logical key")
            frozen_by_key[key] = stable_value(row)
        by_key = {key: dict(row) for key, row in frozen_by_key.items()}
        delta_keys: set[str] = set()
        for row in delta_rows:
            key = binding_logical_key(collection, row)
            if key in delta_keys:
                raise ValueError("Binding delta contains a duplicate logical key")
            delta_keys.add(key)
            operation = str(row.get("operation", "add"))
            expected_base_hash = row.get("base_hash")
            base_row = frozen_by_key.get(key)
            if operation not in {"add", "update", "remove"}:
                raise ValueError(f"Binding delta operation is invalid: {operation}")
            if operation == "add":
                if base_row is not None:
                    raise ValueError("Binding delta add already exists in the base release")
                if expected_base_hash is not None:
                    raise ValueError("Binding delta add cannot declare a base hash")
            else:
                if base_row is None:
                    raise ValueError(
                        f"Binding delta {operation} is missing from the base release"
                    )
                if expected_base_hash is None:
                    raise ValueError(f"Binding delta {operation} requires a base hash")
                if str(expected_base_hash) != binding_base_hash(base_row):
                    raise ValueError("Binding delta base hash does not match the base release")
            if (
                operation != "remove"
                and collection in {"visual_object_assets", "visual_object_compounds"}
                and row.get("is_primary") is True
            ):
                for existing_key, existing in by_key.items():
                    if (
                        existing_key != key
                        and existing.get("visual_object_id") == row.get("visual_object_id")
                    ):
                        existing["is_primary"] = False
            if operation == "remove":
                by_key.pop(key, None)
            else:
                by_key[key] = stable_value(row)
        merged[collection] = [by_key[key] for key in sorted(by_key)]
    return merged


def validate_changeset_binding_delta(
    session: Session,
    changeset: Changeset,
    *,
    delta: Mapping[str, object] | None = None,
) -> None:
    artifact = get_release_artifact_manifest(session, changeset.base_release_id)
    frozen_bindings = (
        artifact.snapshot.get("bindings") if artifact is not None else None
    )
    base = frozen_bindings if isinstance(frozen_bindings, Mapping) else {}
    candidate = (
        delta
        if delta is not None
        else draft_binding_delta_for_changeset(session, changeset.id)
    )
    merge_binding_snapshots(base, candidate)


def build_artifact_snapshot_for_content(
    session: Session,
    content: Iterable[tuple[UUID, str, ObjectRevision]],
    *,
    bindings: Mapping[str, object] | None = None,
) -> dict[str, object]:
    entries = list(content)
    visual_object_ids = {
        object_id for object_id, kind, _ in entries if kind == "visual_object"
    }
    region_ids = {
        object_id for object_id, kind, _ in entries if kind == "visual_region"
    }
    compound_ids = {
        object_id for object_id, kind, _ in entries if kind == "compound"
    }
    object_references: dict[str, dict[str, object]] = {}
    for object_id, kind, _ in entries:
        references: dict[str, object] = {}
        if kind == "structure":
            structure = session.get(Structure, object_id)
            if structure is not None:
                references["compound_id"] = str(structure.compound_id)
        elif kind == "activity":
            activity = session.get(Activity, object_id)
            if activity is not None:
                references["compound_id"] = str(activity.compound_id)
        elif kind == "lineage_edge":
            edge = session.get(LineageEdge, object_id)
            if edge is not None:
                references.update(
                    lineage_id=str(edge.lineage_id),
                    parent_compound_id=(
                        str(edge.parent_compound_id)
                        if edge.parent_compound_id is not None
                        else None
                    ),
                    derived_compound_id=str(edge.derived_compound_id),
                )
        elif kind == "molecule_proposal":
            proposal = session.get(MoleculeProposal, object_id)
            if proposal is not None:
                references.update(
                    visual_object_id=str(proposal.visual_object_id),
                    crop_asset_id=(
                        str(proposal.crop_asset_id)
                        if proposal.crop_asset_id is not None
                        else None
                    ),
                    source_region_id=(
                        str(proposal.source_region_id)
                        if proposal.source_region_id is not None
                        else None
                    ),
                )
        if references:
            object_references[str(object_id)] = references
    binding_rows = (
        _binding_rows_for_visual_objects(session, visual_object_ids)
        if bindings is None
        else {
            collection: [
                stable_value(dict(row))
                for row in bindings.get(collection, [])
                if isinstance(row, Mapping)
            ]
            for collection in BINDING_COLLECTIONS
        }
    )
    region_assets = [
        {
            "region_id": str(region.id),
            "asset_id": str(region.asset_id) if region.asset_id else None,
        }
        for region in session.scalars(
            select(VisualRegion)
            .where(VisualRegion.id.in_(region_ids))
            .order_by(VisualRegion.id)
        )
    ]
    snapshot: dict[str, object] = {
        "bindings": {
            collection: binding_rows[collection]
            for collection in BINDING_COLLECTIONS
        },
        "region_assets": region_assets,
        "release_targets": {
            "visual_object_ids": sorted(str(value) for value in visual_object_ids),
            "region_ids": sorted(str(value) for value in region_ids),
            "compound_ids": sorted(str(value) for value in compound_ids),
        },
        "object_references": object_references,
    }
    asset_ids: set[UUID] = set()
    for _, _, revision in entries:
        asset_ids.update(extract_asset_ids(revision.snapshot))
    bindings = snapshot["bindings"]
    assert isinstance(bindings, Mapping)
    for binding in bindings.get("visual_object_assets", []):
        if isinstance(binding, Mapping) and binding.get("asset_id"):
            asset_ids.add(UUID(str(binding["asset_id"])))
    for region in snapshot["region_assets"]:
        if isinstance(region, Mapping) and region.get("asset_id"):
            asset_ids.add(UUID(str(region["asset_id"])))

    pending = list(asset_ids)
    assets: dict[UUID, Asset] = {}
    while pending:
        asset_id = pending.pop()
        if asset_id in assets:
            continue
        asset = session.get(Asset, asset_id)
        if asset is None:
            continue
        assets[asset_id] = asset
        if asset.source_asset_id is not None and asset.source_asset_id not in assets:
            asset_ids.add(asset.source_asset_id)
            pending.append(asset.source_asset_id)
    snapshot["asset_manifest"] = [
        row_snapshot(assets[asset_id]) for asset_id in sorted(assets, key=str)
    ]
    snapshot["asset_ids"] = sorted(str(asset_id) for asset_id in asset_ids)
    snapshot["schema_version"] = 1
    snapshot["capture_mode"] = "runtime_exact"
    return stable_value(snapshot)


def build_candidate_artifact_snapshot(
    session: Session,
    *,
    base_release_id: UUID,
    changeset: Changeset,
    content: Iterable[tuple[UUID, str, ObjectRevision]],
) -> dict[str, object]:
    entries = list(content)
    base_artifact = get_release_artifact_manifest(session, base_release_id)
    if base_artifact is None:
        raise ValueError("Base release artifact manifest is missing")
    base_bindings = base_artifact.snapshot.get("bindings")
    if not isinstance(base_bindings, Mapping):
        raise ValueError("Base release binding manifest is invalid")
    visual_object_ids = {
        object_id for object_id, kind, _ in entries if kind == "visual_object"
    }
    delta = binding_delta_for_changeset(
        session,
        changeset,
        visual_object_ids=visual_object_ids,
    )
    return build_artifact_snapshot_for_content(
        session,
        entries,
        bindings=merge_binding_snapshots(base_bindings, delta),
    )


def build_release_artifact_snapshot(
    session: Session,
    release_id: UUID,
) -> dict[str, object]:
    items = list(
        session.scalars(
            select(ReleaseItem).where(ReleaseItem.release_id == release_id)
        )
    )
    content: list[tuple[UUID, str, ObjectRevision]] = []
    for item in items:
        revision = session.get(ObjectRevision, item.revision_id)
        if revision is not None:
            content.append((item.object_id, item.object_kind.value, revision))
    return build_artifact_snapshot_for_content(session, content)


def get_release_artifact_manifest(
    session: Session,
    release_id: UUID,
) -> ReleaseArtifactManifest | None:
    return session.get(ReleaseArtifactManifest, release_id)


def capture_release_artifact_manifest(
    session: Session,
    release_id: UUID,
    *,
    snapshot: Mapping[str, object] | None = None,
) -> ReleaseArtifactManifest:
    existing = get_release_artifact_manifest(session, release_id)
    prepared = stable_value(
        dict(snapshot) if snapshot is not None else build_release_artifact_snapshot(session, release_id)
    )
    content_hash = canonical_hash(prepared)
    if existing is not None:
        if existing.content_hash != content_hash:
            raise ValueError("Release artifact manifest is immutable")
        return existing
    manifest = ReleaseArtifactManifest(
        release_id=release_id,
        schema_version=1,
        snapshot=prepared,
        content_hash=content_hash,
    )
    session.add(manifest)
    session.flush()
    return manifest


__all__ = [
    "ASSET_REFERENCE_FIELDS",
    "BINDING_COLLECTIONS",
    "binding_delta_for_changeset",
    "binding_base_hash",
    "binding_logical_key",
    "build_candidate_artifact_snapshot",
    "build_artifact_snapshot_for_content",
    "build_release_artifact_snapshot",
    "canonical_hash",
    "capture_release_artifact_manifest",
    "extract_asset_ids",
    "frozen_base_binding",
    "get_release_artifact_manifest",
    "merge_binding_snapshots",
    "row_snapshot",
    "stable_value",
]
