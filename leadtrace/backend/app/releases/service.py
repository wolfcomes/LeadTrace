from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.errors import APIError
from app.assets.storage import LocalAssetStore
from app.releases.manifest import (
    canonical_hash,
    capture_release_artifact_manifest,
    get_release_artifact_manifest,
)
from app.releases.models import Release, ReleaseItem, ReleaseOperation
from app.releases.validation import (
    ReleaseValidationResult,
    assert_release_valid,
    validate_release,
)
from app.revisions.models import ObjectKind, ObjectRevision, RevisionedObject
from app.revisions.service import RevisionService
from app.reviews.models import Changeset, ChangesetItem
from app.reviews.service import ReviewService
from app.security.policies import WorkflowState
from app.users.models import User, UserRole


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
        .where(Release.metrics["changeset_id"].astext == str(changeset_id))
        .order_by(Release.created_at.desc())
    )


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
        metrics={"changeset_id": str(changeset.id), "item_count": len(release_items)},
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
        metrics={
            "rollback_of": str(target.id),
            "replaced_release_id": str(current.id),
            "item_count": len(cloned_items),
            "tombstone_count": len(rollback_revisions) - len(cloned_items),
        },
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
