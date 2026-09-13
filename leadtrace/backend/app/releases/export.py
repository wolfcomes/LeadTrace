from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.activities.models import Activity
from app.assets.models import (
    Asset,
    AssetAccessLevel,
    AssetCategory,
    AssetIntegrityState,
)
from app.assets.storage import LocalAssetStore
from app.compounds.models import Compound
from app.evidence.models import Evidence
from app.lineages.models import Lineage, LineageEdge
from app.papers.models import Paper
from app.releases.manifest import (
    canonical_hash,
    capture_release_artifact_manifest,
    get_release_artifact_manifest,
)
from app.releases.models import Release, ReleaseItem
from app.revisions.models import (
    ActivityState,
    EvidenceState,
    ObjectKind,
    ObjectRevision,
    StructureState,
)
from app.security.policies import WorkflowState
from app.revisions.service import canonical_snapshot_hash
from app.structures.models import Structure
from app.users.models import User, UserRole
from app.visual_objects.models import (
    MoleculeObjectType,
    VisualObject,
    VisualObjectAssetBinding,
    VisualObjectCompoundBinding,
    VisualObjectRegionBinding,
    VisualObjectRelation,
    VisualRegion,
)
from app.releases.validation import assert_release_valid, validate_release


def _json_default(value: object) -> str:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"Cannot serialize {type(value)!r}")


def _stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _stable(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_stable(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return value


def _portable_revision(revision: ObjectRevision) -> dict[str, object]:
    fields = (
        "revision_number",
        "reason",
        "content_hash",
        "search_text",
        "snapshot",
        "is_tombstone",
        "structure_state",
        "evidence_state",
        "activity_state",
        "canonical_smiles",
        "evidence_text",
        "activity_metric",
        "activity_value",
        "activity_unit",
        "relation_type",
        "relation_status",
        "region_x0",
        "region_y0",
        "region_x1",
        "region_y1",
        "region_rotation",
    )
    return {field: _stable(getattr(revision, field)) for field in fields}


def build_release_export(
    session: Session,
    release_id: UUID,
    *,
    asset_store: LocalAssetStore | None = None,
) -> dict[str, object]:
    release = session.get(Release, release_id)
    if release is None:
        raise ValueError("Release not found")
    validation = validate_release(session, release_id, asset_store=asset_store)
    if not validation.valid:
        raise ValueError("Cannot export invalid release")
    items = list(
        session.scalars(
            select(ReleaseItem)
            .where(ReleaseItem.release_id == release_id)
            .order_by(ReleaseItem.manifest_order, ReleaseItem.id)
        )
    )
    sections: dict[str, list[dict[str, object]]] = {
        "papers": [],
        "compounds": [],
        "structures": [],
        "lineages": [],
        "lineage_edges": [],
        "evidence": [],
        "activities": [],
        "regions": [],
        "visual_objects": [],
        "revisions": [],
    }
    for item in items:
        revision = session.get(ObjectRevision, item.revision_id)
        sections["revisions"].append(
            {
                "object_id": str(item.object_id),
                "revision_id": str(item.revision_id),
                "object_kind": item.object_kind.value,
                "paper_id": str(item.paper_id),
                "manifest_order": item.manifest_order,
                "snapshot": _stable(revision.snapshot if revision else {}),
                "revision": _portable_revision(revision) if revision else {},
            }
        )
        key = {
            "paper": "papers",
            "compound": "compounds",
            "structure": "structures",
            "lineage": "lineages",
            "lineage_edge": "lineage_edges",
            "evidence": "evidence",
            "activity": "activities",
            "visual_region": "regions",
            "visual_object": "visual_objects",
        }.get(item.object_kind.value)
        if key and revision is not None:
            sections[key].append(
                {
                    "id": str(item.object_id),
                    "paper_id": str(item.paper_id),
                    "revision_id": str(item.revision_id),
                    "snapshot": _stable(revision.snapshot),
                }
            )
    artifact = get_release_artifact_manifest(session, release_id)
    if artifact is None:
        artifact = capture_release_artifact_manifest(session, release_id)
    artifact_snapshot = artifact.snapshot
    bindings = artifact_snapshot.get("bindings", {})
    assets = artifact_snapshot.get("asset_manifest", [])
    payload: dict[str, object] = {
        "schema_version": 1,
        "release": {
            "id": str(release.id),
            "release_key": release.release_key,
            "title": release.title,
            "notes": release.notes,
            "metrics": _stable(release.metrics),
            "published_by_id": str(release.published_by_id),
            "published_at": _stable(release.published_at),
        },
        "papers": sections["papers"],
        "compounds": sections["compounds"],
        "structures": sections["structures"],
        "lineages": sections["lineages"],
        "lineage_edges": sections["lineage_edges"],
        "evidence": sections["evidence"],
        "activities": sections["activities"],
        "regions": sections["regions"],
        "visual_objects": sections["visual_objects"],
        "revisions": sections["revisions"],
        "bindings": bindings,
        "asset_manifest": assets,
        "artifact_manifest": {
            "schema_version": artifact.schema_version,
            "content_hash": artifact.content_hash,
            "snapshot": _stable(artifact_snapshot),
        },
        "vocabularies": {
            "object_kinds": sorted(value.value for value in ObjectKind),
            "workflow_states": sorted(value.value for value in WorkflowState),
            "structure_states": sorted(value.value for value in StructureState),
            "evidence_states": sorted(value.value for value in EvidenceState),
            "activity_states": sorted(value.value for value in ActivityState),
            "asset_categories": sorted(value.value for value in AssetCategory),
            "asset_access_levels": sorted(
                value.value for value in AssetAccessLevel
            ),
            "asset_integrity_states": sorted(
                value.value for value in AssetIntegrityState
            ),
            "molecule_object_types": sorted(
                value.value for value in MoleculeObjectType
            ),
        },
        "release_notes": release.notes,
    }
    canonical = json.dumps(
        _stable(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    payload["sha256_manifest"] = {"payload": hashlib.sha256(canonical).hexdigest()}
    return _stable(payload)


def export_release(
    session: Session,
    release_id: UUID,
    destination: Path | None = None,
    *,
    asset_store: LocalAssetStore | None = None,
) -> dict[str, object]:
    payload = build_release_export(session, release_id, asset_store=asset_store)
    if destination is not None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
    return payload


def verify_release_export(payload: Mapping[str, object]) -> bool:
    manifest = payload.get("sha256_manifest")
    if not isinstance(manifest, Mapping) or not isinstance(
        manifest.get("payload"), str
    ):
        return False
    unsigned = dict(payload)
    unsigned.pop("sha256_manifest", None)
    canonical = json.dumps(
        _stable(unsigned),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest() == manifest["payload"]


def load_release_export(source: Path | bytes | str) -> dict[str, object]:
    if isinstance(source, Path):
        raw = source.read_text(encoding="utf-8")
    elif isinstance(source, bytes):
        raw = source.decode("utf-8")
    else:
        raw = source
    payload = json.loads(raw)
    if not isinstance(payload, dict) or not verify_release_export(payload):
        raise ValueError("Release export SHA-256 manifest is invalid")
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported release export schema version")
    return payload


def _required_mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Release export field {field} is invalid")
    return value


def _records(payload: Mapping[str, object], field: str) -> list[Mapping[str, object]]:
    value = payload.get(field)
    if not isinstance(value, list) or any(not isinstance(row, Mapping) for row in value):
        raise ValueError(f"Release export field {field} is invalid")
    return list(value)  # type: ignore[arg-type]


def _uuid(value: object, field: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise ValueError(f"Release export field {field} is not a UUID") from error


def _optional_uuid(value: object) -> UUID | None:
    return None if value is None or value == "" else _uuid(value, "reference")


def _datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"Release export field {field} is not a timestamp")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"Release export field {field} is not a timestamp") from error


def _snapshot_value(snapshot: Mapping[str, object], *names: str) -> object | None:
    normalized = snapshot.get("normalized_values")
    for name in names:
        if name in snapshot and snapshot[name] is not None and snapshot[name] != "":
            return snapshot[name]
        if (
            isinstance(normalized, Mapping)
            and name in normalized
            and normalized[name] is not None
            and normalized[name] != ""
        ):
            return normalized[name]
    return None


def _export_reference(
    object_id: UUID,
    snapshot: Mapping[str, object],
    object_references: Mapping[str, object],
    field: str,
) -> object | None:
    value = _snapshot_value(snapshot, field)
    if value is not None:
        return value
    saved = object_references.get(str(object_id))
    return saved.get(field) if isinstance(saved, Mapping) else None


def _reference_ids(value: object | None, field: str) -> set[UUID]:
    if value is None or value == "":
        return set()
    values = value if isinstance(value, (list, tuple)) else (value,)
    return {_uuid(candidate, field) for candidate in values}


def _validate_export_reference_closure(
    revisions: list[Mapping[str, object]],
    artifact_snapshot: Mapping[str, object],
    asset_rows: Mapping[UUID, Mapping[str, object]],
) -> None:
    kinds: dict[str, set[UUID]] = {}
    snapshots: dict[UUID, Mapping[str, object]] = {}
    for row in revisions:
        object_id = _uuid(row.get("object_id"), "revision.object_id")
        kind = str(row.get("object_kind") or "")
        kinds.setdefault(kind, set()).add(object_id)
        snapshots[object_id] = _required_mapping(
            row.get("snapshot"), "revision.snapshot"
        )
    object_references = _required_mapping(
        artifact_snapshot.get("object_references", {}),
        "artifact object references",
    )

    def require(
        object_id: UUID,
        field: str,
        expected_kind: str,
        *,
        required: bool = False,
    ) -> None:
        targets = _reference_ids(
            _export_reference(
                object_id,
                snapshots[object_id],
                object_references,
                field,
            ),
            field,
        )
        if required and not targets:
            raise ValueError("Release export reference closure is incomplete")
        if not targets <= kinds.get(expected_kind, set()):
            raise ValueError("Release export reference closure is invalid")

    for object_id in kinds.get("structure", set()):
        require(object_id, "compound_id", "compound", required=True)
    for object_id in kinds.get("evidence", set()):
        require(object_id, "compound_ids", "compound")
    for object_id in kinds.get("activity", set()):
        require(object_id, "compound_id", "compound", required=True)
        require(object_id, "evidence_ids", "evidence")
    for object_id in kinds.get("lineage_edge", set()):
        require(object_id, "lineage_id", "lineage", required=True)
        require(object_id, "parent_compound_id", "compound")
        require(object_id, "derived_compound_id", "compound", required=True)
        require(object_id, "evidence_ids", "evidence")

    bindings = _required_mapping(
        artifact_snapshot.get("bindings", {}), "artifact bindings"
    )
    binding_specs = (
        ("visual_object_regions", "visual_object_id", "visual_object", "region_id", "visual_region"),
        ("visual_object_compounds", "visual_object_id", "visual_object", "compound_id", "compound"),
        ("visual_object_relations", "source_object_id", "visual_object", "target_object_id", "visual_object"),
    )
    for collection, source_field, source_kind, target_field, target_kind in binding_specs:
        rows = bindings.get(collection, [])
        if not isinstance(rows, list):
            raise ValueError("Release export reference closure is invalid")
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError("Release export reference closure is invalid")
            source = _uuid(row.get(source_field), source_field)
            target = _uuid(row.get(target_field), target_field)
            if source not in kinds.get(source_kind, set()) or target not in kinds.get(
                target_kind, set()
            ):
                raise ValueError("Release export reference closure is invalid")
    asset_bindings = bindings.get("visual_object_assets", [])
    if not isinstance(asset_bindings, list):
        raise ValueError("Release export reference closure is invalid")
    for row in asset_bindings:
        if not isinstance(row, Mapping):
            raise ValueError("Release export reference closure is invalid")
        if _uuid(row.get("visual_object_id"), "visual_object_id") not in kinds.get(
            "visual_object", set()
        ) or _uuid(row.get("asset_id"), "asset_id") not in asset_rows:
            raise ValueError("Release export reference closure is invalid")


def _validate_release_export_integrity(
    session: Session,
    payload: Mapping[str, object],
) -> None:
    artifact = _required_mapping(payload.get("artifact_manifest"), "artifact_manifest")
    artifact_snapshot = _required_mapping(artifact.get("snapshot"), "artifact snapshot")
    if str(artifact.get("content_hash") or "") != canonical_hash(
        dict(artifact_snapshot)
    ):
        raise ValueError("Release export artifact content hash is invalid")
    frozen_assets = artifact_snapshot.get("asset_manifest")
    top_assets = _records(payload, "asset_manifest")
    if not isinstance(frozen_assets, list) or _stable(frozen_assets) != _stable(top_assets):
        raise ValueError("Release export asset manifest does not match frozen artifact")
    frozen_bindings = artifact_snapshot.get("bindings")
    if not isinstance(frozen_bindings, Mapping) or _stable(frozen_bindings) != _stable(
        _required_mapping(payload.get("bindings"), "bindings")
    ):
        raise ValueError("Release export bindings do not match frozen artifact")

    revisions = _records(payload, "revisions")
    revision_by_object: dict[UUID, Mapping[str, object]] = {}
    for row in revisions:
        object_id = _uuid(row.get("object_id"), "revision.object_id")
        if object_id in revision_by_object:
            raise ValueError("Release export contains duplicate revisions")
        snapshot = dict(_required_mapping(row.get("snapshot"), "revision.snapshot"))
        revision_data = _required_mapping(row.get("revision"), "revision")
        if _stable(revision_data.get("snapshot")) != _stable(snapshot):
            raise ValueError("Release export revision snapshots are inconsistent")
        supplied_hash = str(revision_data.get("content_hash") or "")
        database_hash = str(
            session.scalar(select(func.leadtrace_jsonb_sha256(cast(snapshot, JSONB))))
            or ""
        )
        if supplied_hash not in {canonical_snapshot_hash(snapshot), database_hash}:
            raise ValueError("Release export revision content hash is invalid")
        revision_by_object[object_id] = row

    section_by_kind = {
        "paper": "papers",
        "compound": "compounds",
        "structure": "structures",
        "lineage": "lineages",
        "lineage_edge": "lineage_edges",
        "evidence": "evidence",
        "activity": "activities",
        "visual_region": "regions",
        "visual_object": "visual_objects",
    }
    for kind, section in section_by_kind.items():
        for row in _records(payload, section):
            object_id = _uuid(row.get("id"), f"{section}.id")
            revision = revision_by_object.get(object_id)
            if revision is None or revision.get("object_kind") != kind:
                raise ValueError("Release export sections do not match revisions")
            if _stable(row.get("snapshot")) != _stable(revision.get("snapshot")):
                raise ValueError("Release export sections do not match revision snapshots")

    asset_rows = {
        _uuid(row.get("id"), "asset.id"): row for row in top_assets
    }
    _validate_export_reference_closure(revisions, artifact_snapshot, asset_rows)


def restore_release_export(
    session: Session,
    payload: Mapping[str, object],
    *,
    asset_store: LocalAssetStore | None = None,
) -> Release:
    """Restore one self-contained release into an empty migrated database."""

    if not verify_release_export(payload):
        raise ValueError("Release export SHA-256 manifest is invalid")
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported release export schema version")
    _validate_release_export_integrity(session, payload)
    if _records(payload, "asset_manifest") and asset_store is None:
        raise ValueError("A physical asset store is required to restore asset releases")
    if session.scalar(select(Release.id).limit(1)) is not None:
        raise ValueError("Release export restoration requires an empty target database")

    release_data = _required_mapping(payload.get("release"), "release")
    publisher_id = _uuid(release_data.get("published_by_id"), "published_by_id")
    publisher = User(
        id=publisher_id,
        username=f"release-import-{publisher_id.hex[:12]}",
        normalized_username=f"release-import-{publisher_id.hex[:12]}",
        display_name="Disabled release import identity",
        role=UserRole.ADMIN,
        is_enabled=False,
        password_hash="!disabled-release-import-identity!",
        must_change_password=False,
    )
    session.add(publisher)
    session.flush()

    asset_rows = {
        _uuid(row.get("id"), "asset.id"): row
        for row in _records(payload, "asset_manifest")
    }
    pending_assets = dict(asset_rows)
    restored_assets: set[UUID] = set()
    while pending_assets:
        progressed = False
        for asset_id, row in list(pending_assets.items()):
            source_id = _optional_uuid(row.get("source_asset_id"))
            if source_id is not None and source_id not in restored_assets:
                if source_id not in pending_assets:
                    raise ValueError("Release export omits a source asset")
                continue
            session.add(
                Asset(
                    id=asset_id,
                    storage_key=str(row.get("storage_key") or ""),
                    original_filename=str(row.get("original_filename") or ""),
                    sha256=str(row.get("sha256") or ""),
                    byte_size=int(row.get("byte_size") or 0),
                    mime_type=str(row.get("mime_type") or "application/octet-stream"),
                    width=int(row["width"]) if row.get("width") is not None else None,
                    height=int(row["height"]) if row.get("height") is not None else None,
                    page_count=(
                        int(row["page_count"])
                        if row.get("page_count") is not None
                        else None
                    ),
                    category=AssetCategory(str(row.get("category"))),
                    access_level=AssetAccessLevel(str(row.get("access_level"))),
                    integrity_state=AssetIntegrityState(
                        str(row.get("integrity_state"))
                    ),
                    import_batch_id=None,
                    source_asset_id=source_id,
                    derivation_metadata=dict(
                        _required_mapping(
                            row.get("derivation_metadata", {}),
                            "asset.derivation_metadata",
                        )
                    ),
                    source_metadata=dict(
                        _required_mapping(
                            row.get("source_metadata", {}), "asset.source_metadata"
                        )
                    ),
                    verified_at=(
                        _datetime(row["verified_at"], "asset.verified_at")
                        if row.get("verified_at")
                        else None
                    ),
                    created_by_id=publisher_id,
                )
            )
            session.flush()
            restored_assets.add(asset_id)
            pending_assets.pop(asset_id)
            progressed = True
        if not progressed:
            raise ValueError("Release export asset derivation graph contains a cycle")

    artifact = _required_mapping(payload.get("artifact_manifest"), "artifact_manifest")
    artifact_snapshot = _required_mapping(artifact.get("snapshot"), "artifact snapshot")
    object_references = artifact_snapshot.get("object_references", {})
    if not isinstance(object_references, Mapping):
        raise ValueError("Release export object references are invalid")
    region_assets = artifact_snapshot.get("region_assets", [])
    region_asset_by_id = {
        _uuid(row.get("region_id"), "region_id"): _optional_uuid(row.get("asset_id"))
        for row in region_assets
        if isinstance(row, Mapping)
    }

    section_order = (
        "papers",
        "compounds",
        "lineages",
        "evidence",
        "structures",
        "activities",
        "lineage_edges",
        "regions",
        "visual_objects",
    )
    records_by_section = {name: _records(payload, name) for name in section_order}

    def reference(object_id: UUID, snapshot: Mapping[str, object], field: str) -> UUID | None:
        value = _snapshot_value(snapshot, field)
        if value is not None and value != "":
            try:
                return UUID(str(value))
            except ValueError:
                pass
        saved = object_references.get(str(object_id))
        if isinstance(saved, Mapping):
            return _optional_uuid(saved.get(field))
        return None

    for section in section_order:
        for row in records_by_section[section]:
            object_id = _uuid(row.get("id"), f"{section}.id")
            paper_id = _uuid(row.get("paper_id"), f"{section}.paper_id")
            snapshot = _required_mapping(row.get("snapshot"), f"{section}.snapshot")
            if section == "papers":
                paper_key = _snapshot_value(snapshot, "paper_key", "paper_id")
                identity = Paper(
                    id=object_id,
                    paper_key=str(paper_key or object_id),
                    doi=(
                        str(_snapshot_value(snapshot, "doi"))
                        if _snapshot_value(snapshot, "doi")
                        else None
                    ),
                )
            elif section == "compounds":
                local_identity = str(
                    _snapshot_value(
                        snapshot,
                        "local_identity",
                        "compound_entity_id",
                        "display_label",
                    )
                    or object_id
                )
                display_label = str(
                    _snapshot_value(snapshot, "display_label", "label")
                    or local_identity
                )
                identity = Compound(
                    id=object_id,
                    paper_id=paper_id,
                    local_identity=local_identity,
                    display_label=display_label,
                    normalized_label=str(
                        _snapshot_value(snapshot, "normalized_label")
                        or display_label.casefold()
                    ),
                )
            elif section == "lineages":
                identity = Lineage(
                    id=object_id,
                    paper_id=paper_id,
                    lineage_key=str(
                        _snapshot_value(snapshot, "lineage_key", "lineage_id")
                        or object_id
                    ),
                )
            elif section == "evidence":
                identity = Evidence(
                    id=object_id,
                    paper_id=paper_id,
                    evidence_key=str(
                        _snapshot_value(snapshot, "evidence_key", "evidence_id")
                        or object_id
                    ),
                )
            elif section == "structures":
                compound_id = reference(object_id, snapshot, "compound_id")
                if compound_id is None:
                    raise ValueError("Structure export omits compound_id")
                identity = Structure(
                    id=object_id,
                    paper_id=paper_id,
                    compound_id=compound_id,
                    structure_key=str(
                        _snapshot_value(snapshot, "structure_key") or object_id
                    ),
                )
            elif section == "activities":
                compound_id = reference(object_id, snapshot, "compound_id")
                if compound_id is None:
                    raise ValueError("Activity export omits compound_id")
                identity = Activity(
                    id=object_id,
                    paper_id=paper_id,
                    compound_id=compound_id,
                    activity_key=str(
                        _snapshot_value(snapshot, "activity_key") or object_id
                    ),
                )
            elif section == "lineage_edges":
                lineage_id = reference(object_id, snapshot, "lineage_id")
                derived_id = reference(object_id, snapshot, "derived_compound_id")
                if lineage_id is None or derived_id is None:
                    raise ValueError("Lineage edge export omits required endpoints")
                identity = LineageEdge(
                    id=object_id,
                    paper_id=paper_id,
                    lineage_id=lineage_id,
                    edge_key=str(_snapshot_value(snapshot, "edge_key") or object_id),
                    parent_compound_id=reference(
                        object_id, snapshot, "parent_compound_id"
                    ),
                    derived_compound_id=derived_id,
                )
            elif section == "regions":
                identity = VisualRegion(
                    id=object_id,
                    paper_id=paper_id,
                    region_key=str(_snapshot_value(snapshot, "region_key") or object_id),
                    asset_id=region_asset_by_id.get(object_id),
                    page_number=int(_snapshot_value(snapshot, "page_number") or 1),
                )
            else:
                identity = VisualObject(
                    id=object_id,
                    paper_id=paper_id,
                    object_key=str(_snapshot_value(snapshot, "object_key") or object_id),
                    object_type=MoleculeObjectType(
                        str(
                            _snapshot_value(snapshot, "object_type")
                            or MoleculeObjectType.UNCERTAIN.value
                        )
                    ),
                )
            session.add(identity)
            session.flush()

    revisions_by_object = {
        _uuid(row.get("object_id"), "revision.object_id"): row
        for row in _records(payload, "revisions")
    }
    restored_revisions: dict[UUID, ObjectRevision] = {}
    for object_id, row in revisions_by_object.items():
        revision_data = _required_mapping(row.get("revision"), "revision")
        revision = ObjectRevision(
            id=_uuid(row.get("revision_id"), "revision_id"),
            object_id=object_id,
            revision_number=int(revision_data.get("revision_number") or 1),
            predecessor_id=None,
            changeset_id=None,
            actor_id=publisher_id,
            reason=str(revision_data.get("reason") or "Restore release export"),
            content_hash=str(revision_data.get("content_hash") or ""),
            search_text=(
                str(revision_data["search_text"])
                if revision_data.get("search_text") is not None
                else None
            ),
            snapshot=dict(_required_mapping(row.get("snapshot"), "revision.snapshot")),
            workflow_state=WorkflowState.PUBLISHED,
            is_current_published=True,
            is_tombstone=False,
            structure_state=(
                StructureState(str(revision_data["structure_state"]))
                if revision_data.get("structure_state")
                else None
            ),
            evidence_state=(
                EvidenceState(str(revision_data["evidence_state"]))
                if revision_data.get("evidence_state")
                else None
            ),
            activity_state=(
                ActivityState(str(revision_data["activity_state"]))
                if revision_data.get("activity_state")
                else None
            ),
            canonical_smiles=revision_data.get("canonical_smiles"),
            evidence_text=revision_data.get("evidence_text"),
            activity_metric=revision_data.get("activity_metric"),
            activity_value=revision_data.get("activity_value"),
            activity_unit=revision_data.get("activity_unit"),
            relation_type=revision_data.get("relation_type"),
            relation_status=revision_data.get("relation_status"),
            region_x0=revision_data.get("region_x0"),
            region_y0=revision_data.get("region_y0"),
            region_x1=revision_data.get("region_x1"),
            region_y1=revision_data.get("region_y1"),
            region_rotation=revision_data.get("region_rotation"),
        )
        session.add(revision)
        session.flush()
        restored_revisions[object_id] = revision

    bindings = _required_mapping(payload.get("bindings"), "bindings")
    binding_specs = (
        (
            "visual_object_regions",
            VisualObjectRegionBinding,
            ("id", "visual_object_id", "region_id", "role", "note"),
        ),
        (
            "visual_object_assets",
            VisualObjectAssetBinding,
            ("id", "visual_object_id", "asset_id", "role", "is_primary"),
        ),
        (
            "visual_object_compounds",
            VisualObjectCompoundBinding,
            (
                "id",
                "visual_object_id",
                "compound_id",
                "label",
                "label_bbox",
                "role",
                "confidence",
                "note",
                "is_primary",
            ),
        ),
        (
            "visual_object_relations",
            VisualObjectRelation,
            ("id", "source_object_id", "target_object_id", "relation_type", "note"),
        ),
    )
    uuid_fields = {
        "id",
        "visual_object_id",
        "region_id",
        "asset_id",
        "compound_id",
        "source_object_id",
        "target_object_id",
    }
    for collection, model, fields in binding_specs:
        rows = bindings.get(collection, [])
        if not isinstance(rows, list):
            raise ValueError(f"Release export binding {collection} is invalid")
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError(f"Release export binding {collection} is invalid")
            values = {
                field: _uuid(row.get(field), field)
                if field in uuid_fields
                else row.get(field)
                for field in fields
            }
            session.add(model(**values))
    session.flush()

    release = Release(
        id=_uuid(release_data.get("id"), "release.id"),
        release_key=str(release_data.get("release_key") or ""),
        title=str(release_data.get("title") or ""),
        notes=str(release_data.get("notes") or ""),
        metrics=dict(_required_mapping(release_data.get("metrics", {}), "metrics")),
        published_by_id=publisher_id,
        published_at=_datetime(release_data.get("published_at"), "published_at"),
        is_current=False,
        manifest_finalized=False,
    )
    session.add(release)
    session.flush()
    for row in _records(payload, "revisions"):
        object_id = _uuid(row.get("object_id"), "release_item.object_id")
        session.add(
            ReleaseItem(
                release_id=release.id,
                object_id=object_id,
                revision_id=restored_revisions[object_id].id,
                paper_id=_uuid(row.get("paper_id"), "release_item.paper_id"),
                object_kind=ObjectKind(str(row.get("object_kind"))),
                manifest_order=int(row.get("manifest_order") or 0),
            )
        )
    session.flush()
    capture_release_artifact_manifest(
        session,
        release.id,
        snapshot=artifact_snapshot,
    )
    release.manifest_finalized = True
    session.flush([release])
    assert_release_valid(
        validate_release(session, release.id, asset_store=asset_store)
    )
    release.is_current = True
    session.flush([release])
    return release


__all__ = [
    "build_release_export",
    "export_release",
    "load_release_export",
    "restore_release_export",
    "verify_release_export",
]
