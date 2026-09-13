from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from collections.abc import Mapping
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.api.errors import APIError
from app.activities.models import Activity
from app.assets.models import Asset, AssetIntegrityState
from app.assets.storage import LocalAssetStore
from app.audit.service import canonical_content_hash, persisted_json_value
from app.compounds.models import Compound
from app.evidence.models import Evidence
from app.imports.models import (
    ImportAssetLink,
    ImportBatch,
    ImportCandidateDecision,
    ImportReleaseCandidate,
)
from app.lineages.models import Lineage, LineageEdge
from app.papers.models import Paper
from app.releases.aggregate import (
    OVERVIEW_METRIC_KEYS,
    overview_metrics_from_counts,
    recompute_release_aggregate,
)
from app.releases.manifest import (
    build_release_artifact_snapshot,
    canonical_hash,
    capture_release_artifact_manifest,
    get_release_artifact_manifest,
)
from app.releases.models import Release, ReleaseItem, ReleaseOperation
from app.releases.validation import (
    ReleaseValidationResult,
    ValidationIssue,
    assert_release_valid,
    validate_release,
)
from app.revisions.models import ObjectKind, ObjectRevision, RevisionedObject
from app.revisions.service import RevisionService
from app.reviews.models import Changeset, ChangesetItem
from app.reviews.service import ReviewService
from app.security.policies import WorkflowState
from app.structures.models import Structure
from app.users.models import User, UserRole
from app.visual_objects.models import VisualObject, VisualRegion


@dataclass(frozen=True, slots=True)
class PublishedRelease:
    id: UUID
    key: str
    title: str
    published_at: datetime
    metrics: dict[str, object]

    @classmethod
    def from_model(cls, release: Release) -> "PublishedRelease":
        return cls(
            id=release.id,
            key=release.release_key,
            title=release.title,
            published_at=release.published_at,
            metrics=release.metrics,
        )


def get_current_release(session: Session) -> Release:
    release = session.scalar(
        select(Release).where(
            Release.is_current.is_(True),
            Release.manifest_finalized.is_(True),
        )
    )
    if release is None:
        raise APIError(
            404,
            "CURRENT_RELEASE_NOT_FOUND",
            "No published release is currently available",
        )
    return release


class ReleaseConflict(RuntimeError):
    """A release operation cannot be completed in the current state."""


class BaselineValidationError(ValueError):
    """An approved imported baseline does not satisfy publication gates."""


@dataclass(frozen=True, slots=True)
class ReleaseOperationResult:
    release: Release
    validation: ReleaseValidationResult
    idempotent: bool = False
    replaced_release_id: UUID | None = None
    operation_id: UUID | None = None


def _advisory_lock(session: Session) -> None:
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('leadtrace.release.pointer'))")
    )


def _require_admin(session: Session, actor_id: UUID) -> None:
    actor = session.get(User, actor_id)
    if actor is None or not actor.is_enabled or actor.role is not UserRole.ADMIN:
        raise ReleaseConflict("Only an enabled Admin can publish or roll back releases")


def _release_for_changeset(session: Session, changeset_id: UUID) -> Release | None:
    return session.scalar(
        select(Release)
        .where(
            or_(
                Release.metrics["changeset_id"].astext == str(changeset_id),
                Release.metrics["operation"]["changeset_id"].astext
                == str(changeset_id),
            )
        )
        .order_by(Release.created_at.desc())
    )


def _metrics_with_operation(
    source: Mapping[str, object],
    operation: Mapping[str, object],
) -> dict[str, object]:
    metrics = {
        key: source[key]
        for key in OVERVIEW_METRIC_KEYS
        if key in source
    }
    metrics["operation"] = dict(operation)
    return metrics


def _replay_baseline_validation(
    operation: ReleaseOperation,
) -> ReleaseValidationResult:
    snapshot = operation.delta.get("validation")
    if not isinstance(snapshot, Mapping):
        raise ReleaseConflict("Idempotent baseline validation is unavailable")
    issues_value = snapshot.get("issues")
    asset_ids_value = snapshot.get("asset_ids")
    if (
        not isinstance(snapshot.get("valid"), bool)
        or not isinstance(issues_value, list)
        or not isinstance(asset_ids_value, list)
    ):
        raise ReleaseConflict("Idempotent baseline validation is invalid")
    try:
        release_id_value = snapshot.get("release_id")
        release_id = UUID(str(release_id_value)) if release_id_value else None
        changeset_id_value = snapshot.get("changeset_id")
        changeset_id = UUID(str(changeset_id_value)) if changeset_id_value else None
        asset_ids = tuple(UUID(str(asset_id)) for asset_id in asset_ids_value)
        issues: list[ValidationIssue] = []
        for issue_value in issues_value:
            if not isinstance(issue_value, Mapping):
                raise ValueError("validation issue is not an object")
            code = issue_value.get("code")
            message = issue_value.get("message")
            if not isinstance(code, str) or not isinstance(message, str):
                raise ValueError("validation issue text is invalid")
            object_id_value = issue_value.get("object_id")
            issues.append(
                ValidationIssue(
                    code=code,
                    message=message,
                    object_id=(
                        UUID(str(object_id_value)) if object_id_value else None
                    ),
                )
            )
    except (TypeError, ValueError, AttributeError) as error:
        raise ReleaseConflict("Idempotent baseline validation is invalid") from error
    content_fingerprint = snapshot.get("content_fingerprint")
    if content_fingerprint is not None and not isinstance(content_fingerprint, str):
        raise ReleaseConflict("Idempotent baseline validation is invalid")
    validation = ReleaseValidationResult(
        valid=snapshot["valid"],
        issues=tuple(issues),
        release_id=release_id,
        changeset_id=changeset_id,
        content_fingerprint=content_fingerprint,
        asset_ids=asset_ids,
    )
    if not validation.valid or validation.release_id != operation.result_release_id:
        raise ReleaseConflict("Idempotent baseline validation is invalid")
    return validation


_BASELINE_KIND_SPECS = (
    (ObjectKind.PAPER, Paper, "paper_key"),
    (ObjectKind.COMPOUND, Compound, "local_identity"),
    (ObjectKind.STRUCTURE, Structure, "structure_key"),
    (ObjectKind.EVIDENCE, Evidence, "evidence_key"),
    (ObjectKind.ACTIVITY, Activity, "activity_key"),
    (ObjectKind.LINEAGE, Lineage, "lineage_key"),
    (ObjectKind.LINEAGE_EDGE, LineageEdge, "edge_key"),
    (ObjectKind.VISUAL_REGION, VisualRegion, "region_key"),
    (ObjectKind.VISUAL_OBJECT, VisualObject, "object_key"),
)
_BASELINE_KIND_RANK = {
    kind: rank for rank, (kind, _, _) in enumerate(_BASELINE_KIND_SPECS)
}


def _baseline_release_items(
    session: Session,
    *,
    expected_revision_count: int,
) -> list[tuple[UUID, UUID, UUID, ObjectKind, int]]:
    objects: list[tuple[UUID, UUID, ObjectKind, str]] = []
    for kind, model, key_name in _BASELINE_KIND_SPECS:
        key_column = getattr(model, key_name)
        for record in session.scalars(select(model).order_by(key_column, model.id)):
            paper_id = record.id if kind is ObjectKind.PAPER else record.paper_id
            objects.append((record.id, paper_id, kind, str(getattr(record, key_name))))

    revisions = list(session.scalars(select(ObjectRevision)))
    if len(objects) != expected_revision_count or len(revisions) != expected_revision_count:
        raise BaselineValidationError(
            "Imported baseline object and revision counts do not match the candidate"
        )
    revisions_by_object: dict[UUID, list[ObjectRevision]] = {}
    for revision in revisions:
        revisions_by_object.setdefault(revision.object_id, []).append(revision)

    paper_keys = {
        paper.id: paper.paper_key for paper in session.scalars(select(Paper))
    }
    ordered: list[tuple[str, int, str, str, UUID, UUID, UUID, ObjectKind]] = []
    for object_id, paper_id, kind, stable_key in objects:
        object_revisions = revisions_by_object.get(object_id, [])
        if len(object_revisions) != 1:
            raise BaselineValidationError(
                "Each imported baseline object must have exactly one revision"
            )
        revision = object_revisions[0]
        if (
            revision.revision_number != 1
            or revision.predecessor_id is not None
            or revision.changeset_id is not None
            or revision.workflow_state is not WorkflowState.APPROVED
            or revision.is_current_published
            or revision.is_tombstone
        ):
            raise BaselineValidationError(
                "Imported baseline revision is not eligible for publication"
            )
        paper_key = paper_keys.get(paper_id)
        if paper_key is None:
            raise BaselineValidationError(
                "Imported baseline object references a missing Paper"
            )
        ordered.append(
            (
                paper_key,
                _BASELINE_KIND_RANK[kind],
                stable_key,
                str(object_id),
                object_id,
                revision.id,
                paper_id,
                kind,
            )
        )
    ordered.sort(key=lambda value: value[:4])
    return [
        (object_id, revision_id, paper_id, kind, order)
        for order, (
            _,
            _,
            _,
            _,
            object_id,
            revision_id,
            paper_id,
            kind,
        ) in enumerate(ordered, start=1)
    ]


def _validate_baseline_assets(
    session: Session,
    *,
    batch_id: UUID,
    asset_store: LocalAssetStore | None,
) -> list[Asset]:
    asset_ids = set(
        session.scalars(
            select(ImportAssetLink.asset_id).where(
                ImportAssetLink.import_batch_id == batch_id
            )
        )
    )
    assets = list(
        session.scalars(
            select(Asset).where(Asset.id.in_(asset_ids)).order_by(Asset.id)
        )
    ) if asset_ids else []
    if len(assets) != len(asset_ids):
        raise BaselineValidationError("Imported baseline asset record is missing")
    for asset in assets:
        if asset.integrity_state is not AssetIntegrityState.VERIFIED:
            raise BaselineValidationError(
                "Imported baseline asset is not in the verified state"
            )
        if asset_store is None:
            continue
        try:
            inspected = asset_store.inspect(asset.storage_key)
        except (OSError, ValueError) as error:
            raise BaselineValidationError(
                "Imported baseline asset bytes are unavailable or invalid"
            ) from error
        if (
            inspected.sha256 != asset.sha256
            or inspected.byte_size != asset.byte_size
            or inspected.mime_type != asset.mime_type
        ):
            raise BaselineValidationError(
                "Imported baseline asset bytes failed integrity verification"
            )
    return assets


def _approved_baseline_context(
    session: Session,
    candidate: ImportReleaseCandidate,
) -> tuple[ImportBatch, ImportCandidateDecision, dict[str, object], int]:
    if candidate.status != "approved":
        raise ReleaseConflict("Only an approved import candidate can be published")
    batch = session.get(ImportBatch, candidate.import_batch_id)
    if batch is None or batch.status != "completed" or batch.completed_at is None:
        raise ReleaseConflict("Approved candidate import batch is incomplete")
    decision = session.scalar(
        select(ImportCandidateDecision).where(
            ImportCandidateDecision.candidate_id == candidate.id,
            ImportCandidateDecision.decision == "approve",
        )
    )
    if decision is None:
        raise ReleaseConflict("Approved candidate decision is missing")
    manifest = persisted_json_value(session, candidate.manifest)
    if not isinstance(manifest, dict):
        raise ReleaseConflict("Approved candidate manifest is invalid")
    if (
        canonical_content_hash(manifest) != decision.manifest_hash
        or manifest != decision.manifest
    ):
        raise ReleaseConflict("Approved candidate manifest changed after decision")
    required_manifest = {
        "schema_version": 1,
        "source_fingerprint": batch.source_fingerprint,
        "status": "imported_baseline",
        "is_current": False,
        "counts": batch.counts,
        "integrity": batch.integrity,
        "asset_linkage": batch.asset_linkage,
    }
    if any(manifest.get(key) != value for key, value in required_manifest.items()):
        raise ReleaseConflict("Approved candidate no longer matches its import batch")
    revision_count = manifest.get("revision_count")
    if (
        isinstance(revision_count, bool)
        or not isinstance(revision_count, int)
        or revision_count < 1
    ):
        raise BaselineValidationError(
            "Approved candidate revision_count must be a positive integer"
        )
    return batch, decision, manifest, revision_count


def _revision_columns(revision: ObjectRevision) -> dict[str, object]:
    return {
        "search_text": revision.search_text,
        "structure_state": revision.structure_state,
        "evidence_state": revision.evidence_state,
        "activity_state": revision.activity_state,
        "canonical_smiles": revision.canonical_smiles,
        "evidence_text": revision.evidence_text,
        "activity_metric": revision.activity_metric,
        "activity_value": revision.activity_value,
        "activity_unit": revision.activity_unit,
        "relation_type": revision.relation_type,
        "relation_status": revision.relation_status,
        "region_bounds": (
            (
                revision.region_x0,
                revision.region_y0,
                revision.region_x1,
                revision.region_y1,
            )
            if revision.region_x0 is not None
            else None
        ),
        "region_rotation": revision.region_rotation,
    }


def preview_approved_changeset(
    session: Session,
    *,
    changeset_id: UUID,
    actor_id: UUID,
    asset_store: LocalAssetStore | None = None,
) -> dict[str, object]:
    """Return the exact candidate delta and a fresh pre-publication validation."""

    _require_admin(session, actor_id)
    changeset = session.get(Changeset, changeset_id)
    if changeset is None:
        raise ReleaseConflict("Changeset not found")
    if changeset.workflow_state is not WorkflowState.APPROVED:
        raise ReleaseConflict("Only an approved changeset can be previewed")
    current = get_current_release(session)
    if changeset.base_release_id != current.id:
        raise ReleaseConflict("Changeset base release is not current")
    validation = validate_release(
        session,
        current.id,
        changeset_id=changeset.id,
        asset_store=asset_store,
    )
    current_object_ids = set(
        session.scalars(
            select(ReleaseItem.object_id).where(ReleaseItem.release_id == current.id)
        )
    )
    counts = {"create": 0, "update": 0, "tombstone": 0, "total": 0}
    by_object_kind: dict[str, dict[str, int]] = {}
    objects: list[dict[str, object]] = []
    for item in session.scalars(
        select(ChangesetItem)
        .where(ChangesetItem.changeset_id == changeset.id)
        .order_by(ChangesetItem.sequence, ChangesetItem.id)
    ):
        revision = (
            session.get(ObjectRevision, item.proposed_revision_id)
            if item.proposed_revision_id is not None
            else None
        )
        action = (
            "tombstone"
            if revision is not None and revision.is_tombstone
            else "update"
            if item.object_id in current_object_ids
            else "create"
        )
        counts[action] += 1
        counts["total"] += 1
        kind_counts = by_object_kind.setdefault(
            item.object_kind,
            {"create": 0, "update": 0, "tombstone": 0, "total": 0},
        )
        kind_counts[action] += 1
        kind_counts["total"] += 1
        objects.append(
            {
                "object_id": str(item.object_id),
                "object_kind": item.object_kind,
                "paper_id": str(item.paper_id),
                "action": action,
                "base_revision_id": (
                    str(item.base_revision_id) if item.base_revision_id else None
                ),
                "proposed_revision_id": (
                    str(item.proposed_revision_id)
                    if item.proposed_revision_id
                    else None
                ),
            }
        )
    return {
        "changeset_id": str(changeset.id),
        "base_release_id": str(current.id),
        "counts": counts,
        "by_object_kind": by_object_kind,
        "objects": objects,
        "affected_asset_ids": [str(asset_id) for asset_id in validation.asset_ids],
        "validation": validation.as_dict(),
    }


def publish_approved_baseline(
    session: Session,
    *,
    candidate_id: UUID,
    actor_id: UUID,
    title: str | None = None,
    notes: str = "",
    idempotency_key: str | None = None,
    fail_stage: str | None = None,
    asset_store: LocalAssetStore | None = None,
) -> ReleaseOperationResult:
    """Publish one approved import candidate as the first complete release."""

    operation_key = (idempotency_key or f"internal-{uuid4()}").strip()
    if not operation_key or len(operation_key) > 200:
        raise ValueError("idempotency_key must contain 1 to 200 characters")
    clean_title = (title or "LeadTrace initial baseline").strip()
    if not clean_title or len(clean_title) > 255:
        raise ValueError("title must contain 1 to 255 characters")
    clean_notes = notes.strip()
    request_hash = canonical_hash(
        {
            "candidate_id": str(candidate_id),
            "title": clean_title,
            "notes": clean_notes,
        }
    )

    _advisory_lock(session)
    _require_admin(session, actor_id)
    existing_operation = session.scalar(
        select(ReleaseOperation)
        .where(
            ReleaseOperation.actor_id == actor_id,
            ReleaseOperation.operation_type == "baseline_publish",
            ReleaseOperation.idempotency_key == operation_key,
        )
        .with_for_update()
    )
    if existing_operation is not None:
        if existing_operation.request_hash != request_hash:
            raise ReleaseConflict(
                "Idempotency key was already used for another baseline publication"
            )
        existing_release = session.get(
            Release,
            existing_operation.result_release_id,
        )
        if (
            existing_release is None
            or existing_release.source_candidate_id != candidate_id
        ):
            raise ReleaseConflict("Idempotent baseline publication is unavailable")
        validation = _replay_baseline_validation(existing_operation)
        return ReleaseOperationResult(
            existing_release,
            validation,
            idempotent=True,
            replaced_release_id=None,
            operation_id=existing_operation.id,
        )

    candidate = session.scalar(
        select(ImportReleaseCandidate)
        .where(ImportReleaseCandidate.id == candidate_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if candidate is None:
        raise ReleaseConflict("Import candidate not found")
    batch, _, _, revision_count = _approved_baseline_context(session, candidate)
    if session.scalar(select(func.count()).select_from(Release)):
        raise ReleaseConflict("A release already exists; baseline bootstrap is closed")

    release_items = _baseline_release_items(
        session,
        expected_revision_count=revision_count,
    )
    linked_assets = _validate_baseline_assets(
        session,
        batch_id=batch.id,
        asset_store=asset_store,
    )
    if fail_stage == "final_transaction":
        raise RuntimeError("Injected failure in final transaction")

    metrics: dict[str, object] = overview_metrics_from_counts(batch.counts)
    metrics["baseline"] = {
        "candidate_id": str(candidate.id),
        "batch_id": str(batch.id),
        "source_fingerprint": batch.source_fingerprint,
        "counts": batch.counts,
        "integrity": batch.integrity,
        "asset_linkage": batch.asset_linkage,
        "item_count": len(release_items),
    }
    release = Release(
        release_key=f"baseline-{candidate.id}",
        title=clean_title,
        notes=clean_notes,
        metrics=metrics,
        source_candidate_id=candidate.id,
        published_by_id=actor_id,
        published_at=datetime.now(UTC),
        is_current=False,
        manifest_finalized=False,
    )
    session.add(release)
    session.flush()

    revision_ids = {revision_id for _, revision_id, _, _, _ in release_items}
    revisions = list(
        session.scalars(
            select(ObjectRevision)
            .where(ObjectRevision.id.in_(revision_ids))
            .with_for_update()
        )
    )
    if len(revisions) != len(revision_ids):
        raise BaselineValidationError("Imported baseline revision disappeared")
    for revision in revisions:
        revision.workflow_state = WorkflowState.PUBLISHED
        revision.is_current_published = True
        session.flush([revision])

    session.add_all(
        [
            ReleaseItem(
                release_id=release.id,
                object_id=object_id,
                revision_id=revision_id,
                paper_id=paper_id,
                object_kind=kind,
                manifest_order=order,
            )
            for object_id, revision_id, paper_id, kind, order in release_items
        ]
    )
    session.flush()
    artifact_snapshot = build_release_artifact_snapshot(session, release.id)
    artifact_snapshot["baseline_import"] = {
        "candidate_id": str(candidate.id),
        "batch_id": str(batch.id),
        "asset_ids": [str(asset.id) for asset in linked_assets],
    }
    capture_release_artifact_manifest(
        session,
        release.id,
        snapshot=artifact_snapshot,
    )
    release.manifest_finalized = True
    session.flush([release])
    validation = validate_release(
        session,
        release.id,
        asset_store=asset_store,
    )
    assert_release_valid(validation)
    aggregate = recompute_release_aggregate(
        session,
        release,
        asset_store=asset_store,
        validation=validation,
    )
    if aggregate.counts != batch.counts:
        raise BaselineValidationError(
            "Published baseline counts do not match the approved import"
        )
    if aggregate.integrity != batch.integrity:
        raise BaselineValidationError(
            "Published baseline integrity does not match the approved import"
        )

    operation = ReleaseOperation(
        operation_type="baseline_publish",
        actor_id=actor_id,
        idempotency_key=operation_key,
        request_hash=request_hash,
        target_release_id=None,
        replaced_release_id=None,
        result_release_id=release.id,
        reason=clean_notes or f"Publish approved baseline {candidate.id}",
        delta={
            "candidate_id": str(candidate.id),
            "batch_id": str(batch.id),
            "item_count": len(release_items),
            "content_fingerprint": validation.content_fingerprint,
            "validation": validation.as_dict(),
        },
    )
    session.add(operation)
    session.flush([operation])
    if fail_stage == "before_pointer_switch":
        raise RuntimeError("Injected failure before pointer switch")
    release.is_current = True
    session.flush([release])
    candidate.status = "published"
    candidate.is_current = True
    session.flush([candidate])
    return ReleaseOperationResult(
        release,
        validation,
        replaced_release_id=None,
        operation_id=operation.id,
    )


def publish_approved_changeset(
    session: Session,
    *,
    changeset_id: UUID,
    actor_id: UUID,
    title: str | None = None,
    notes: str = "",
    idempotency_key: str | None = None,
    fail_stage: str | None = None,
    asset_store: LocalAssetStore | None = None,
) -> ReleaseOperationResult:
    """Publish an approved changeset as one atomic, pointer-switched release."""

    operation_key = (idempotency_key or f"internal-{uuid4()}").strip()
    if not operation_key or len(operation_key) > 200:
        raise ValueError("idempotency_key must contain 1 to 200 characters")
    request_hash = canonical_hash(
        {
            "changeset_id": str(changeset_id),
            "title": title,
            "notes": notes,
        }
    )
    _require_admin(session, actor_id)
    changeset = session.get(Changeset, changeset_id)
    if changeset is None:
        raise ReleaseConflict("Changeset not found")
    if changeset.workflow_state is WorkflowState.PUBLISHED:
        existing = _release_for_changeset(session, changeset.id)
        if existing is None:
            raise ReleaseConflict("Published changeset release is unavailable")
        if fail_stage == "before_asset_preparation":
            raise RuntimeError("Injected failure before asset preparation")
        prepared_validation = validate_release(
            session,
            existing.id,
            asset_store=asset_store,
        )
        assert_release_valid(prepared_validation)
        if fail_stage == "after_asset_preparation":
            raise RuntimeError("Injected failure after asset preparation")
    elif changeset.workflow_state is not WorkflowState.APPROVED:
        raise ReleaseConflict("Only an approved changeset can be published")
    else:
        current = get_current_release(session)
        if changeset.base_release_id != current.id:
            raise ReleaseConflict("Changeset base release is not current")
        if fail_stage == "before_asset_preparation":
            raise RuntimeError("Injected failure before asset preparation")
        prepared_validation = validate_release(
            session,
            current.id,
            changeset_id=changeset.id,
            asset_store=asset_store,
        )
        assert_release_valid(prepared_validation)
        if fail_stage == "after_asset_preparation":
            raise RuntimeError("Injected failure after asset preparation")

    _advisory_lock(session)
    _require_admin(session, actor_id)
    changeset = session.scalar(
        select(Changeset)
        .where(Changeset.id == changeset_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if changeset is None:
        raise ReleaseConflict("Changeset not found")
    existing_operation = session.scalar(
        select(ReleaseOperation)
        .where(
            ReleaseOperation.actor_id == actor_id,
            ReleaseOperation.operation_type == "publish",
            ReleaseOperation.idempotency_key == operation_key,
        )
        .with_for_update()
    )
    if existing_operation is not None:
        if existing_operation.request_hash != request_hash:
            raise ReleaseConflict("Idempotency key was already used for another publication")
        existing_release = session.get(
            Release, existing_operation.result_release_id
        )
        if existing_release is None:
            raise ReleaseConflict("Idempotent publication result is unavailable")
        validation = validate_release(session, existing_release.id)
        assert_release_valid(validation)
        if validation.content_fingerprint != prepared_validation.content_fingerprint:
            raise ReleaseConflict("Publication result changed during asset preparation")
        return ReleaseOperationResult(
            existing_release,
            validation,
            idempotent=True,
            replaced_release_id=existing_operation.replaced_release_id,
            operation_id=existing_operation.id,
        )
    if changeset.workflow_state is WorkflowState.PUBLISHED:
        raise ReleaseConflict("Changeset is already published")
    if changeset.workflow_state is not WorkflowState.APPROVED:
        raise ReleaseConflict("Only an approved changeset can be published")
    current = get_current_release(session)
    if changeset.base_release_id != current.id:
        raise ReleaseConflict("Changeset base release is not current")
    locked_validation = validate_release(
        session,
        current.id,
        changeset_id=changeset.id,
    )
    assert_release_valid(locked_validation)
    if locked_validation.content_fingerprint != prepared_validation.content_fingerprint:
        raise ReleaseConflict("Release candidate changed during asset preparation")

    current_items = list(
        session.scalars(
            select(ReleaseItem)
            .where(ReleaseItem.release_id == current.id)
            .order_by(ReleaseItem.manifest_order, ReleaseItem.id)
        )
    )
    changes = {
        item.object_id: item
        for item in session.scalars(
            select(ChangesetItem).where(ChangesetItem.changeset_id == changeset.id)
        )
    }
    publication_revisions: dict[UUID, ObjectRevision] = {}
    for proposed in changes.values():
        if proposed.proposed_revision_id is None:
            raise ReleaseConflict("Changeset item has no proposed revision")
        revision = session.scalar(
            select(ObjectRevision)
            .where(
                ObjectRevision.id == proposed.proposed_revision_id,
                ObjectRevision.object_id == proposed.object_id,
            )
            .with_for_update()
        )
        if revision is None:
            raise ReleaseConflict("Changeset proposed revision is missing")
        # Once the changeset has been approved, linked revisions may advance
        # through approved and then published while retaining their identity.
        if revision.workflow_state in {
            WorkflowState.DRAFT,
            WorkflowState.REVISED_DRAFT,
        }:
            revision.workflow_state = WorkflowState.SUBMITTED
            session.flush([revision])
        if revision.workflow_state is WorkflowState.SUBMITTED:
            revision.workflow_state = WorkflowState.APPROVED
            session.flush([revision])
        publication_revisions[proposed.object_id] = revision

    release_items: list[tuple[UUID, UUID, UUID, ObjectKind, int]] = []
    current_object_ids = {item.object_id for item in current_items}
    for current_item in current_items:
        revision = publication_revisions.get(current_item.object_id)
        if revision is None:
            release_items.append(
                (
                    current_item.object_id,
                    current_item.revision_id,
                    current_item.paper_id,
                    current_item.object_kind,
                    current_item.manifest_order,
                )
            )
            continue
        if revision.is_tombstone:
            continue
        release_items.append(
            (
                current_item.object_id,
                revision.id,
                current_item.paper_id,
                current_item.object_kind,
                current_item.manifest_order,
            )
        )
    next_order = max((item.manifest_order for item in current_items), default=0)
    for proposed in sorted(changes.values(), key=lambda item: (item.sequence, item.id)):
        if proposed.object_id in current_object_ids:
            continue
        revision = publication_revisions[proposed.object_id]
        if revision.is_tombstone:
            continue
        next_order += 1
        release_items.append(
            (
                proposed.object_id,
                revision.id,
                proposed.paper_id,
                ObjectKind(proposed.object_kind),
                next_order,
            )
        )

    if fail_stage == "final_transaction":
        raise RuntimeError("Injected failure in final transaction")
    new_release = Release(
        release_key=f"release-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}",
        title=title or f"Release for {changeset.title}",
        notes=notes,
        metrics=_metrics_with_operation(
            current.metrics,
            {
                "type": "publish",
                "changeset_id": str(changeset.id),
                "item_count": len(release_items),
            },
        ),
        published_by_id=actor_id,
        published_at=datetime.now(UTC),
        is_current=False,
        manifest_finalized=False,
    )
    session.add(new_release)
    session.flush()
    # Changeset state must be published before linked revisions can be marked
    # published by the revision integrity trigger.
    ReviewService().transition_changeset(
        session,
        changeset_id=changeset.id,
        actor_id=actor_id,
        expected_version=changeset.version,
        next_state=WorkflowState.PUBLISHED,
    )
    for object_id, revision in publication_revisions.items():
        prior = session.scalar(
            select(ObjectRevision)
            .where(
                ObjectRevision.object_id == object_id,
                ObjectRevision.is_current_published.is_(True),
                ObjectRevision.id != revision.id,
            )
            .with_for_update()
        )
        if prior is not None:
            prior.workflow_state = WorkflowState.SUPERSEDED
            prior.is_current_published = False
            session.flush([prior])
        revision.workflow_state = WorkflowState.PUBLISHED
        revision.is_current_published = True
        session.flush([revision])
    session.add_all(
        [
            ReleaseItem(
                release_id=new_release.id,
                object_id=object_id,
                revision_id=revision_id,
                paper_id=paper_id,
                object_kind=kind,
                manifest_order=order,
            )
            for object_id, revision_id, paper_id, kind, order in release_items
        ]
    )
    session.flush()
    if locked_validation.artifact_snapshot is None:
        raise ReleaseConflict("Release candidate artifact is unavailable")
    capture_release_artifact_manifest(
        session,
        new_release.id,
        snapshot=locked_validation.artifact_snapshot,
    )
    new_release.manifest_finalized = True
    session.flush([new_release])
    validation = validate_release(session, new_release.id)
    assert_release_valid(validation)
    if fail_stage == "before_pointer_switch":
        raise RuntimeError("Injected failure before pointer switch")
    current.is_current = False
    session.flush([current])
    new_release.is_current = True
    session.flush([new_release])
    current_by_object = {item.object_id: item for item in current_items}
    delta_objects: list[dict[str, object]] = []
    for object_id, revision in publication_revisions.items():
        current_item = current_by_object.get(object_id)
        before_revision = (
            session.get(ObjectRevision, current_item.revision_id)
            if current_item is not None
            else None
        )
        delta_objects.append(
            {
                "paper_id": str(changes[object_id].paper_id),
                "object_id": str(object_id),
                "object_kind": changes[object_id].object_kind,
                "action": (
                    "remove"
                    if revision.is_tombstone
                    else "create"
                    if before_revision is None
                    else "update"
                ),
                "before_revision_id": (
                    str(before_revision.id) if before_revision is not None else None
                ),
                "after_revision_id": str(revision.id),
                "before_hash": (
                    before_revision.content_hash if before_revision is not None else None
                ),
                "after_hash": revision.content_hash,
            }
        )
    operation = ReleaseOperation(
        operation_type="publish",
        actor_id=actor_id,
        idempotency_key=operation_key,
        request_hash=request_hash,
        target_release_id=None,
        replaced_release_id=current.id,
        result_release_id=new_release.id,
        reason=notes.strip() or f"Publish changeset {changeset.id}",
        delta={"changeset_id": str(changeset.id), "objects": delta_objects},
    )
    session.add(operation)
    session.flush([operation])
    return ReleaseOperationResult(
        new_release,
        validation,
        replaced_release_id=current.id,
        operation_id=operation.id,
    )


def rollback_release(
    session: Session,
    *,
    target_release_id: UUID,
    actor_id: UUID,
    reason: str,
    idempotency_key: str | None = None,
    fail_stage: str | None = None,
    asset_store: LocalAssetStore | None = None,
) -> ReleaseOperationResult:
    """Create an auditable release whose content matches a historical release."""

    clean_reason = reason.strip()
    if not clean_reason:
        raise ValueError("reason is required")
    _require_admin(session, actor_id)
    target = session.get(Release, target_release_id)
    if target is None or not target.manifest_finalized:
        raise ReleaseConflict("Target release is not available")
    if fail_stage == "before_asset_preparation":
        raise RuntimeError("Injected failure before asset preparation")
    prepared_validation = validate_release(
        session,
        target.id,
        asset_store=asset_store,
    )
    assert_release_valid(prepared_validation)
    if fail_stage == "after_asset_preparation":
        raise RuntimeError("Injected failure after asset preparation")

    operation_key = (idempotency_key or f"internal-{uuid4()}").strip()
    if not operation_key or len(operation_key) > 200:
        raise ValueError("idempotency_key must contain 1 to 200 characters")
    request_hash = canonical_hash(
        {
            "target_release_id": str(target_release_id),
            "reason": clean_reason,
        }
    )

    _advisory_lock(session)
    _require_admin(session, actor_id)
    existing_operation = session.scalar(
        select(ReleaseOperation)
        .where(
            ReleaseOperation.actor_id == actor_id,
            ReleaseOperation.operation_type == "rollback",
            ReleaseOperation.idempotency_key == operation_key,
        )
        .with_for_update()
    )
    if existing_operation is not None:
        if existing_operation.request_hash != request_hash:
            raise ReleaseConflict("Idempotency key was already used for another rollback")
        existing_release = session.get(
            Release, existing_operation.result_release_id
        )
        if existing_release is None:
            raise ReleaseConflict("Idempotent rollback result is unavailable")
        validation = validate_release(session, existing_release.id)
        assert_release_valid(validation)
        return ReleaseOperationResult(
            existing_release,
            validation,
            idempotent=True,
            replaced_release_id=existing_operation.replaced_release_id,
            operation_id=existing_operation.id,
        )

    target = session.scalar(
        select(Release).where(Release.id == target_release_id).with_for_update()
    )
    if target is None or not target.manifest_finalized:
        raise ReleaseConflict("Target release is not available")
    locked_validation = validate_release(session, target.id)
    assert_release_valid(locked_validation)
    if locked_validation.content_fingerprint != prepared_validation.content_fingerprint:
        raise ReleaseConflict("Rollback target changed during asset preparation")
    current = get_current_release(session)
    if target.id == current.id:
        raise ReleaseConflict("Target release is already current")
    current_items = list(
        session.scalars(
            select(ReleaseItem)
            .where(ReleaseItem.release_id == current.id)
            .order_by(ReleaseItem.manifest_order, ReleaseItem.id)
        )
    )
    target_items = list(
        session.scalars(
            select(ReleaseItem)
            .where(ReleaseItem.release_id == target.id)
            .order_by(ReleaseItem.manifest_order, ReleaseItem.id)
        )
    )
    target_artifact = get_release_artifact_manifest(session, target.id)
    if target_artifact is None:
        target_artifact = capture_release_artifact_manifest(session, target.id)
    current_by_object = {item.object_id: item for item in current_items}
    cloned_items: list[tuple[UUID, UUID, UUID, ObjectKind, int]] = []
    rollback_revisions: dict[UUID, ObjectRevision] = {}
    changed_revisions: dict[UUID, ObjectRevision] = {}
    delta_objects: list[dict[str, object]] = []
    for item in target_items:
        source = session.scalar(
            select(ObjectRevision).where(
                ObjectRevision.id == item.revision_id,
                ObjectRevision.object_id == item.object_id,
            )
        )
        if source is None:
            raise ReleaseConflict("Historical revision is missing")
        current_item = current_by_object.get(item.object_id)
        current_revision = (
            session.get(ObjectRevision, current_item.revision_id)
            if current_item is not None
            else session.scalar(
                select(ObjectRevision).where(
                    ObjectRevision.object_id == item.object_id,
                    ObjectRevision.is_current_published.is_(True),
                )
            )
        )
        revision = current_revision
        if revision is None or revision.content_hash != source.content_hash:
            identity = session.get(RevisionedObject, item.object_id)
            if identity is None:
                raise ReleaseConflict("Historical object is missing")
            revision = RevisionService().create_revision(
                session,
                object_identity=identity,
                actor_id=actor_id,
                reason=clean_reason,
                snapshot=dict(source.snapshot),
                predecessor=current_revision or source,
                workflow_state=WorkflowState.APPROVED,
                is_current_published=False,
                **_revision_columns(source),
            )
            changed_revisions[item.object_id] = revision
            delta_objects.append(
                {
                    "paper_id": str(item.paper_id),
                    "object_id": str(item.object_id),
                    "object_kind": item.object_kind.value,
                    "action": "restore",
                    "before_revision_id": (
                        str(current_revision.id) if current_revision is not None else None
                    ),
                    "after_revision_id": str(revision.id),
                    "before_hash": (
                        current_revision.content_hash
                        if current_revision is not None
                        else None
                    ),
                    "after_hash": revision.content_hash,
                }
            )
        assert revision is not None
        rollback_revisions[item.object_id] = revision
        cloned_items.append(
            (
                item.object_id,
                revision.id,
                item.paper_id,
                item.object_kind,
                item.manifest_order,
            )
        )
    target_object_ids = set(rollback_revisions)
    for item in current_items:
        if item.object_id in target_object_ids:
            continue
        current_revision = session.get(ObjectRevision, item.revision_id)
        identity = session.get(RevisionedObject, item.object_id)
        if current_revision is None or identity is None:
            raise ReleaseConflict("Current release object or revision is missing")
        rollback_revisions[item.object_id] = RevisionService().create_revision(
            session,
            object_identity=identity,
            actor_id=actor_id,
            reason=clean_reason,
            snapshot=dict(current_revision.snapshot),
            predecessor=current_revision,
            workflow_state=WorkflowState.APPROVED,
            is_current_published=False,
            is_tombstone=True,
            **_revision_columns(current_revision),
        )
        changed_revisions[item.object_id] = rollback_revisions[item.object_id]
        delta_objects.append(
            {
                "paper_id": str(item.paper_id),
                "object_id": str(item.object_id),
                "object_kind": item.object_kind.value,
                "action": "remove",
                "before_revision_id": str(current_revision.id),
                "after_revision_id": str(rollback_revisions[item.object_id].id),
                "before_hash": current_revision.content_hash,
                "after_hash": rollback_revisions[item.object_id].content_hash,
            }
        )
    if fail_stage == "final_transaction":
        raise RuntimeError("Injected failure in final transaction")
    new_release = Release(
        release_key=f"rollback-{target.release_key}-{uuid4().hex[:8]}",
        title=f"Rollback to {target.title}",
        notes=clean_reason,
        metrics=_metrics_with_operation(
            target.metrics,
            {
                "type": "rollback",
                "rollback_of": str(target.id),
                "replaced_release_id": str(current.id),
                "item_count": len(cloned_items),
                "tombstone_count": len(rollback_revisions) - len(cloned_items),
            },
        ),
        published_by_id=actor_id,
        published_at=datetime.now(UTC),
        is_current=False,
        manifest_finalized=False,
    )
    session.add(new_release)
    session.flush()
    changed_current_revision_ids = [
        current_by_object[object_id].revision_id
        for object_id in changed_revisions
        if object_id in current_by_object
    ]
    current_changeset_ids = set(
        session.scalars(
            select(ObjectRevision.changeset_id).where(
                ObjectRevision.id.in_(changed_current_revision_ids),
                ObjectRevision.changeset_id.is_not(None),
            )
        )
    ) if changed_current_revision_ids else set()
    for current_changeset_id in current_changeset_ids:
        current_changeset = session.get(Changeset, current_changeset_id)
        if (
            current_changeset is not None
            and current_changeset.workflow_state is WorkflowState.PUBLISHED
        ):
            ReviewService().transition_changeset(
                session,
                changeset_id=current_changeset.id,
                actor_id=actor_id,
                expected_version=current_changeset.version,
                next_state=WorkflowState.SUPERSEDED,
            )
    for object_id, revision in changed_revisions.items():
        prior = session.scalar(
            select(ObjectRevision)
            .where(
                ObjectRevision.object_id == object_id,
                ObjectRevision.is_current_published.is_(True),
                ObjectRevision.id != revision.id,
            )
            .with_for_update()
        )
        if prior is not None:
            prior.workflow_state = WorkflowState.SUPERSEDED
            prior.is_current_published = False
            session.flush([prior])
        revision.workflow_state = WorkflowState.PUBLISHED
        revision.is_current_published = True
        session.flush([revision])
    session.add_all(
        [
            ReleaseItem(
                release_id=new_release.id,
                object_id=object_id,
                revision_id=revision_id,
                paper_id=paper_id,
                object_kind=kind,
                manifest_order=order,
            )
            for object_id, revision_id, paper_id, kind, order in cloned_items
        ]
    )
    session.flush()
    capture_release_artifact_manifest(
        session,
        new_release.id,
        snapshot=target_artifact.snapshot,
    )
    new_release.manifest_finalized = True
    session.flush([new_release])
    validation = validate_release(session, new_release.id)
    assert_release_valid(validation)
    if fail_stage == "before_pointer_switch":
        raise RuntimeError("Injected failure before pointer switch")
    current.is_current = False
    session.flush([current])
    new_release.is_current = True
    session.flush([new_release])
    paper_counts: dict[str, dict[str, int | str]] = {}
    for entry in delta_objects:
        paper_id = str(entry["paper_id"])
        counts = paper_counts.setdefault(
            paper_id,
            {"paper_id": paper_id, "restore": 0, "remove": 0},
        )
        action = str(entry["action"])
        counts[action] = int(counts[action]) + 1
    operation = ReleaseOperation(
        operation_type="rollback",
        actor_id=actor_id,
        idempotency_key=operation_key,
        request_hash=request_hash,
        target_release_id=target.id,
        replaced_release_id=current.id,
        result_release_id=new_release.id,
        reason=clean_reason,
        delta={
            "objects": delta_objects,
            "papers": [paper_counts[key] for key in sorted(paper_counts)],
        },
    )
    session.add(operation)
    session.flush([operation])
    return ReleaseOperationResult(
        new_release,
        validation,
        replaced_release_id=current.id,
        operation_id=operation.id,
    )
