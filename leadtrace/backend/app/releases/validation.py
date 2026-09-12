from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activities.models import Activity
from app.assets.models import Asset, AssetIntegrityState
from app.assets.storage import LocalAssetStore
from app.compounds.models import Compound
from app.evidence.models import Evidence
from app.lineages.models import Lineage, LineageEdge
from app.releases.manifest import (
    BINDING_COLLECTIONS,
    build_candidate_artifact_snapshot,
    canonical_hash,
    extract_asset_ids,
    get_release_artifact_manifest,
)
from app.releases.models import Release, ReleaseItem
from app.revisions.models import (
    ObjectKind,
    ObjectRevision,
    RevisionedObject,
    StructureState,
)
from app.reviews.models import Changeset, ChangesetItem
from app.structures.models import Structure
from app.visual_objects.models import VisualObject, VisualRegion


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    message: str
    object_id: UUID | None = None

    def as_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["object_id"] = str(self.object_id) if self.object_id else None
        return value


@dataclass(frozen=True, slots=True)
class ReleaseValidationResult:
    valid: bool
    issues: tuple[ValidationIssue, ...]
    release_id: UUID | None = None
    changeset_id: UUID | None = None
    content_fingerprint: str | None = None
    asset_ids: tuple[UUID, ...] = ()
    artifact_snapshot: dict[str, object] | None = None

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return self.issues

    def as_dict(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "issues": [issue.as_dict() for issue in self.issues],
            "release_id": str(self.release_id) if self.release_id else None,
            "changeset_id": str(self.changeset_id) if self.changeset_id else None,
            "content_fingerprint": self.content_fingerprint,
            "asset_ids": [str(asset_id) for asset_id in self.asset_ids],
        }


@dataclass(frozen=True, slots=True)
class _EffectiveItem:
    object_id: UUID
    paper_id: UUID
    object_kind: ObjectKind
    revision: ObjectRevision


_MODEL_BY_KIND = {
    ObjectKind.PAPER: RevisionedObject,
    ObjectKind.COMPOUND: Compound,
    ObjectKind.STRUCTURE: Structure,
    ObjectKind.EVIDENCE: Evidence,
    ObjectKind.ACTIVITY: Activity,
    ObjectKind.LINEAGE: Lineage,
    ObjectKind.LINEAGE_EDGE: LineageEdge,
    ObjectKind.VISUAL_REGION: VisualRegion,
    ObjectKind.VISUAL_OBJECT: VisualObject,
}


def _snapshot_value(
    item: _EffectiveItem,
    field: str,
    artifact: Mapping[str, object],
) -> object | None:
    if field in item.revision.snapshot:
        return item.revision.snapshot[field]
    normalized = item.revision.snapshot.get("normalized_values")
    if isinstance(normalized, Mapping) and field in normalized:
        return normalized[field]
    references = artifact.get("object_references")
    if isinstance(references, Mapping):
        object_references = references.get(str(item.object_id))
        if isinstance(object_references, Mapping):
            return object_references.get(field)
    return None


def _uuid_values(value: object | None) -> tuple[UUID, ...]:
    if value is None or value == "":
        return ()
    values: Iterable[object]
    if isinstance(value, (list, tuple)):
        values = value
    else:
        values = (value,)
    parsed: list[UUID] = []
    for candidate in values:
        if candidate is None or candidate == "":
            continue
        try:
            parsed.append(UUID(str(candidate)))
        except (TypeError, ValueError, AttributeError):
            continue
    return tuple(parsed)


def _effective_items(
    session: Session,
    release: Release,
    changeset_id: UUID | None,
    issues: list[ValidationIssue],
) -> dict[UUID, _EffectiveItem]:
    effective: dict[UUID, _EffectiveItem] = {}
    for release_item in session.scalars(
        select(ReleaseItem)
        .where(ReleaseItem.release_id == release.id)
        .order_by(ReleaseItem.manifest_order, ReleaseItem.id)
    ):
        revision = session.get(ObjectRevision, release_item.revision_id)
        if revision is None or revision.object_id != release_item.object_id:
            issues.append(
                ValidationIssue(
                    "dangling_reference",
                    "Release item references a missing object or revision",
                    release_item.object_id,
                )
            )
            continue
        valid_states = (
            {"published"} if release.is_current else {"published", "superseded"}
        )
        if revision.workflow_state.value not in valid_states:
            issues.append(
                ValidationIssue(
                    "invalid_revision",
                    "Release item revision is not a published revision",
                    release_item.object_id,
                )
            )
        effective[release_item.object_id] = _EffectiveItem(
            release_item.object_id,
            release_item.paper_id,
            release_item.object_kind,
            revision,
        )

    if changeset_id is None:
        return effective
    changeset = session.get(Changeset, changeset_id)
    if changeset is None:
        issues.append(ValidationIssue("changeset_not_found", "Changeset does not exist"))
        return effective
    if changeset.base_release_id != release.id:
        issues.append(
            ValidationIssue(
                "base_release_mismatch", "Changeset does not target this release"
            )
        )
        return effective
    for proposed in session.scalars(
        select(ChangesetItem)
        .where(ChangesetItem.changeset_id == changeset.id)
        .order_by(ChangesetItem.sequence, ChangesetItem.id)
    ):
        revision = (
            session.get(ObjectRevision, proposed.proposed_revision_id)
            if proposed.proposed_revision_id is not None
            else None
        )
        if revision is None or revision.object_id != proposed.object_id:
            issues.append(
                ValidationIssue(
                    "dangling_reference",
                    "Changeset item has no immutable proposed revision",
                    proposed.object_id,
                )
            )
            continue
        if revision.is_tombstone:
            effective.pop(proposed.object_id, None)
            continue
        try:
            kind = ObjectKind(proposed.object_kind)
        except ValueError:
            issues.append(
                ValidationIssue(
                    "object_kind_mismatch",
                    "Changeset item kind is not supported",
                    proposed.object_id,
                )
            )
            continue
        effective[proposed.object_id] = _EffectiveItem(
            proposed.object_id,
            proposed.paper_id,
            kind,
            revision,
        )
    return effective


def _validate_identity(
    session: Session,
    item: _EffectiveItem,
    issues: list[ValidationIssue],
) -> None:
    identity = session.get(RevisionedObject, item.object_id)
    if identity is None or identity.object_kind is not item.object_kind:
        issues.append(
            ValidationIssue(
                "object_kind_mismatch",
                "Release item kind does not match object",
                item.object_id,
            )
        )
        return
    model = _MODEL_BY_KIND[item.object_kind]
    record = identity if model is RevisionedObject else session.get(model, item.object_id)
    if record is None:
        issues.append(
            ValidationIssue(
                "dangling_reference",
                "Release item business object is missing",
                item.object_id,
            )
        )
    elif getattr(record, "paper_id", item.paper_id) != item.paper_id:
        issues.append(
            ValidationIssue(
                "paper_mismatch",
                "Release item Paper does not match object",
                item.object_id,
            )
        )


def _require_references(
    source: _EffectiveItem,
    targets: Iterable[UUID],
    *,
    expected_kind: ObjectKind,
    effective: Mapping[UUID, _EffectiveItem],
    issues: list[ValidationIssue],
    label: str,
    code: str = "dangling_reference",
) -> None:
    for target_id in targets:
        target = effective.get(target_id)
        if (
            target is None
            or target.object_kind is not expected_kind
            or target.paper_id != source.paper_id
        ):
            issues.append(
                ValidationIssue(
                    code,
                    f"{label} points outside the release or Paper",
                    source.object_id,
                )
            )


def _validate_reference_closure(
    effective: Mapping[UUID, _EffectiveItem],
    artifact: Mapping[str, object],
    issues: list[ValidationIssue],
) -> None:
    for item in effective.values():
        if item.object_kind is ObjectKind.STRUCTURE:
            _require_references(
                item,
                _uuid_values(_snapshot_value(item, "compound_id", artifact)),
                expected_kind=ObjectKind.COMPOUND,
                effective=effective,
                issues=issues,
                label="Structure compound reference",
            )
        elif item.object_kind is ObjectKind.EVIDENCE:
            _require_references(
                item,
                _uuid_values(_snapshot_value(item, "compound_ids", artifact)),
                expected_kind=ObjectKind.COMPOUND,
                effective=effective,
                issues=issues,
                label="Evidence compound reference",
            )
        elif item.object_kind is ObjectKind.ACTIVITY:
            _require_references(
                item,
                _uuid_values(_snapshot_value(item, "compound_id", artifact)),
                expected_kind=ObjectKind.COMPOUND,
                effective=effective,
                issues=issues,
                label="Activity compound reference",
            )
            _require_references(
                item,
                _uuid_values(_snapshot_value(item, "evidence_ids", artifact)),
                expected_kind=ObjectKind.EVIDENCE,
                effective=effective,
                issues=issues,
                label="Activity evidence reference",
            )
        elif item.object_kind is ObjectKind.LINEAGE_EDGE:
            _require_references(
                item,
                _uuid_values(_snapshot_value(item, "lineage_id", artifact)),
                expected_kind=ObjectKind.LINEAGE,
                effective=effective,
                issues=issues,
                label="Lineage edge lineage reference",
                code="invalid_endpoint",
            )
            for field in ("parent_compound_id", "derived_compound_id"):
                _require_references(
                    item,
                    _uuid_values(_snapshot_value(item, field, artifact)),
                    expected_kind=ObjectKind.COMPOUND,
                    effective=effective,
                    issues=issues,
                    label=f"Lineage edge {field}",
                    code="invalid_endpoint",
                )
            _require_references(
                item,
                _uuid_values(_snapshot_value(item, "evidence_ids", artifact)),
                expected_kind=ObjectKind.EVIDENCE,
                effective=effective,
                issues=issues,
                label="Lineage edge evidence reference",
            )
            status = item.revision.relation_status or _snapshot_value(
                item, "relation_status", artifact
            )
            pair_ready = _snapshot_value(item, "pair_ready", artifact) is True
            if pair_ready and status in {None, "unresolved", "invalid"}:
                issues.append(
                    ValidationIssue(
                        "unresolved_pair_ready_edge",
                        "Pair-ready lineage edge remains unresolved",
                        item.object_id,
                    )
                )

    bindings = artifact.get("bindings")
    if not isinstance(bindings, Mapping):
        return
    specs = (
        (
            "visual_object_regions",
            "visual_object_id",
            ObjectKind.VISUAL_OBJECT,
            "region_id",
            ObjectKind.VISUAL_REGION,
        ),
        (
            "visual_object_compounds",
            "visual_object_id",
            ObjectKind.VISUAL_OBJECT,
            "compound_id",
            ObjectKind.COMPOUND,
        ),
        (
            "visual_object_relations",
            "source_object_id",
            ObjectKind.VISUAL_OBJECT,
            "target_object_id",
            ObjectKind.VISUAL_OBJECT,
        ),
    )
    for collection, source_field, source_kind, target_field, target_kind in specs:
        rows = bindings.get(collection, [])
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            source_ids = _uuid_values(row.get(source_field))
            target_ids = _uuid_values(row.get(target_field))
            if not source_ids:
                continue
            source = effective.get(source_ids[0])
            if source is None:
                issues.append(
                    ValidationIssue(
                        "dangling_reference",
                        "Visual binding source points outside the release",
                        source_ids[0],
                    )
                )
                continue
            if source.object_kind is not source_kind:
                issues.append(
                    ValidationIssue(
                        "dangling_reference",
                        "Visual binding source has the wrong object kind",
                        source.object_id,
                    )
                )
                continue
            _require_references(
                source,
                target_ids,
                expected_kind=target_kind,
                effective=effective,
                issues=issues,
                label="Visual binding target",
            )


def _asset_issues(
    session: Session,
    asset_id: UUID,
    *,
    object_id: UUID,
    asset_store: LocalAssetStore | None,
) -> list[ValidationIssue]:
    asset = session.get(Asset, asset_id)
    if asset is None:
        return [ValidationIssue("missing_asset", "Referenced asset does not exist", object_id)]
    if asset.integrity_state in {
        AssetIntegrityState.MISSING,
        AssetIntegrityState.CORRUPT,
        AssetIntegrityState.QUARANTINED,
    }:
        return [
            ValidationIssue(
                "invalid_asset",
                f"Asset integrity is {asset.integrity_state.value}",
                object_id,
            )
        ]
    if asset_store is not None:
        try:
            inspected = asset_store.inspect(asset.storage_key)
        except (FileNotFoundError, OSError, ValueError):
            return [
                ValidationIssue(
                    "missing_asset", "Referenced asset bytes are unavailable", object_id
                )
            ]
        if inspected.sha256 != asset.sha256 or inspected.byte_size != asset.byte_size:
            return [
                ValidationIssue(
                    "invalid_asset",
                    "Referenced asset bytes failed integrity verification",
                    object_id,
                )
            ]
    return []


def _validate_assets(
    session: Session,
    effective: Mapping[UUID, _EffectiveItem],
    artifact: Mapping[str, object],
    issues: list[ValidationIssue],
    asset_store: LocalAssetStore | None,
) -> set[UUID]:
    references: dict[UUID, set[UUID]] = {}
    for item in effective.values():
        for asset_id in extract_asset_ids(item.revision.snapshot):
            references.setdefault(asset_id, set()).add(item.object_id)
    region_assets = artifact.get("region_assets", [])
    if isinstance(region_assets, list):
        for row in region_assets:
            if not isinstance(row, Mapping):
                continue
            region_ids = _uuid_values(row.get("region_id"))
            asset_ids = _uuid_values(row.get("asset_id"))
            if region_ids and asset_ids and region_ids[0] in effective:
                references.setdefault(asset_ids[0], set()).add(region_ids[0])
    bindings = artifact.get("bindings")
    if isinstance(bindings, Mapping):
        rows = bindings.get("visual_object_assets", [])
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                object_ids = _uuid_values(row.get("visual_object_id"))
                asset_ids = _uuid_values(row.get("asset_id"))
                if object_ids and asset_ids and object_ids[0] in effective:
                    references.setdefault(asset_ids[0], set()).add(object_ids[0])

    pending = list(references)
    while pending:
        asset_id = pending.pop()
        asset = session.get(Asset, asset_id)
        if asset is None or asset.source_asset_id is None:
            continue
        source_id = asset.source_asset_id
        owners = references.setdefault(source_id, set())
        before = len(owners)
        owners.update(references[asset_id])
        if len(owners) != before:
            pending.append(source_id)
    frozen_assets = artifact.get("asset_manifest", [])
    frozen_by_id: dict[UUID, Mapping[str, object]] = {}
    if isinstance(frozen_assets, list):
        for row in frozen_assets:
            if not isinstance(row, Mapping):
                continue
            parsed_ids = _uuid_values(row.get("id"))
            if parsed_ids:
                frozen_by_id[parsed_ids[0]] = row
    for asset_id in sorted(references, key=str):
        asset = session.get(Asset, asset_id)
        frozen = frozen_by_id.get(asset_id)
        if asset is None or frozen is None:
            issues.append(
                ValidationIssue(
                    "asset_manifest_mismatch",
                    "Referenced asset is missing from the frozen asset manifest",
                    next(iter(references[asset_id]), None),
                )
            )
            continue
        live_identity = {
            "storage_key": asset.storage_key,
            "sha256": asset.sha256,
            "byte_size": asset.byte_size,
            "integrity_state": asset.integrity_state.value,
            "source_asset_id": (
                str(asset.source_asset_id) if asset.source_asset_id else None
            ),
        }
        frozen_identity = {field: frozen.get(field) for field in live_identity}
        if live_identity != frozen_identity:
            issues.append(
                ValidationIssue(
                    "asset_manifest_mismatch",
                    "Live asset identity differs from the frozen release manifest",
                    next(iter(references[asset_id]), None),
                )
            )
    for asset_id in sorted(references, key=str):
        for object_id in sorted(references[asset_id], key=str):
            issues.extend(
                _asset_issues(
                    session,
                    asset_id,
                    object_id=object_id,
                    asset_store=asset_store,
                )
            )
    return set(references)


def validate_release(
    session: Session,
    release_id: UUID | None = None,
    *,
    changeset_id: UUID | None = None,
    asset_store: LocalAssetStore | None = None,
) -> ReleaseValidationResult:
    """Validate one immutable release, or its effective approved candidate."""

    issues: list[ValidationIssue] = []
    release = session.get(Release, release_id) if release_id else None
    if release is None:
        issues.append(ValidationIssue("release_not_found", "Release does not exist"))
        return ReleaseValidationResult(False, tuple(issues), release_id, changeset_id)
    if not release.manifest_finalized:
        issues.append(
            ValidationIssue("manifest_not_finalized", "Release manifest is not finalized")
        )
    effective = _effective_items(session, release, changeset_id, issues)
    artifact: dict[str, object] = {
        "bindings": {collection: [] for collection in BINDING_COLLECTIONS},
        "region_assets": [],
        "release_targets": {},
        "object_references": {},
        "asset_manifest": [],
        "asset_ids": [],
        "schema_version": 1,
        "capture_mode": "unavailable",
    }
    if changeset_id is None:
        artifact_model = get_release_artifact_manifest(session, release.id)
        if artifact_model is None:
            issues.append(
                ValidationIssue(
                    "artifact_manifest_missing",
                    "Release artifact manifest is missing",
                )
            )
        else:
            artifact = dict(artifact_model.snapshot)
            if artifact_model.content_hash != canonical_hash(artifact):
                issues.append(
                    ValidationIssue(
                        "artifact_hash_mismatch",
                        "Release artifact manifest hash does not match its content",
                    )
                )
    else:
        changeset = session.get(Changeset, changeset_id)
        if changeset is not None:
            try:
                artifact = build_candidate_artifact_snapshot(
                    session,
                    base_release_id=release.id,
                    changeset=changeset,
                    content=(
                        (item.object_id, item.object_kind.value, item.revision)
                        for item in effective.values()
                    ),
                )
            except ValueError as error:
                issues.append(
                    ValidationIssue(
                        "artifact_manifest_missing",
                        str(error),
                    )
                )
    for item in effective.values():
        _validate_identity(session, item, issues)
        if (
            item.object_kind is ObjectKind.STRUCTURE
            and item.revision.structure_state is StructureState.SOURCE_STRUCTURE_MISMATCH
            and _snapshot_value(item, "source_mismatch_confirmed", artifact) is not True
        ):
            issues.append(
                ValidationIssue(
                    "source_mismatch_unconfirmed",
                    "Structure source mismatch requires Admin confirmation",
                    item.object_id,
                )
            )
    _validate_reference_closure(effective, artifact, issues)
    asset_ids = _validate_assets(session, effective, artifact, issues, asset_store)
    fingerprint_payload: dict[str, object] = {
        "objects": [
            {
                "object_id": str(item.object_id),
                "paper_id": str(item.paper_id),
                "object_kind": item.object_kind.value,
                "revision_id": str(item.revision.id),
                "content_hash": item.revision.content_hash,
            }
            for item in sorted(effective.values(), key=lambda value: str(value.object_id))
        ],
        "artifact": artifact,
        "asset_metadata": [
            {
                "id": str(asset.id),
                "storage_key": asset.storage_key,
                "sha256": asset.sha256,
                "byte_size": asset.byte_size,
                "integrity_state": asset.integrity_state.value,
                "source_asset_id": str(asset.source_asset_id) if asset.source_asset_id else None,
            }
            for asset in session.scalars(
                select(Asset).where(Asset.id.in_(asset_ids)).order_by(Asset.id)
            )
        ],
    }
    unique_issues = tuple(
        {
            (issue.code, issue.message, issue.object_id): issue for issue in issues
        }.values()
    )
    return ReleaseValidationResult(
        not unique_issues,
        unique_issues,
        release.id,
        changeset_id,
        canonical_hash(fingerprint_payload),
        tuple(sorted(asset_ids, key=str)),
        artifact,
    )


def assert_release_valid(result: ReleaseValidationResult) -> None:
    if not result.valid:
        raise ValueError(
            "Release validation failed: "
            + "; ".join(issue.message for issue in result.issues)
        )


__all__ = [
    "ReleaseValidationResult",
    "ValidationIssue",
    "assert_release_valid",
    "validate_release",
]
