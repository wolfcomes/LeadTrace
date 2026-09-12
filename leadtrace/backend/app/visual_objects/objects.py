from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.revisions.models import ObjectRevision
from app.revisions.service import RevisionService, canonical_snapshot_hash
from app.reviews.models import Changeset, ChangesetItem
from app.security.policies import WorkflowState
from app.visual_objects.models import MoleculeObjectType, VisualObject


class ObjectValidationError(ValueError):
    """Raised when a visual object's semantic type or identity is invalid."""


class ObjectVersionConflict(RuntimeError):
    """Raised when a visual-object draft was changed after it was loaded."""

    def __init__(self, expected_version: int, current_version: int) -> None:
        self.expected_version = expected_version
        self.current_version = current_version
        super().__init__(
            f"Visual object draft changed concurrently: expected {expected_version}, "
            f"current {current_version}"
        )


def check_expected_version(current_version: int, *, expected_version: int) -> None:
    if expected_version != current_version:
        raise ObjectVersionConflict(expected_version, current_version)


def normalize_object_type(value: str | MoleculeObjectType) -> MoleculeObjectType:
    try:
        return value if isinstance(value, MoleculeObjectType) else MoleculeObjectType(value.strip())
    except (AttributeError, ValueError) as error:
        raise ObjectValidationError("Unknown molecule object type") from error


def build_object_snapshot(
    *,
    object_key: str,
    object_type: MoleculeObjectType,
    label: str | None = None,
) -> dict[str, object]:
    clean_key = object_key.strip()
    if not clean_key:
        raise ObjectValidationError("object_key is required")
    snapshot: dict[str, object] = {
        "object_key": clean_key,
        "object_type": normalize_object_type(object_type).value,
    }
    if label is not None:
        clean_label = label.strip()
        if clean_label:
            snapshot["label"] = clean_label
    return snapshot


class MoleculeObjectService:
    """Create and version semantic interpretations of visual evidence."""

    check_expected_version = staticmethod(check_expected_version)

    @staticmethod
    def _editable_changeset(
        session: Session,
        *,
        changeset_id: UUID,
        expected_version: int,
        paper_id: UUID,
    ) -> Changeset:
        changeset = session.scalar(
            select(Changeset).where(Changeset.id == changeset_id).with_for_update()
        )
        if changeset is None or changeset.paper_id != paper_id:
            raise ObjectValidationError("Changeset does not belong to this Paper")
        check_expected_version(changeset.version, expected_version=expected_version)
        if changeset.workflow_state not in {WorkflowState.DRAFT, WorkflowState.REVISED_DRAFT}:
            raise ObjectValidationError("Only editable draft changesets can contain objects")
        return changeset

    @staticmethod
    def _ensure_item(
        session: Session,
        *,
        changeset: Changeset,
        object_identity: VisualObject,
        snapshot: Mapping[str, object],
        base_revision_id: UUID | None,
    ) -> ChangesetItem:
        item = session.scalar(
            select(ChangesetItem)
            .where(
                ChangesetItem.changeset_id == changeset.id,
                ChangesetItem.object_id == object_identity.id,
            )
            .with_for_update()
        )
        if item is None:
            sequence = session.scalar(
                select(func.max(ChangesetItem.sequence)).where(
                    ChangesetItem.changeset_id == changeset.id
                )
            )
            item = ChangesetItem(
                changeset_id=changeset.id,
                paper_id=changeset.paper_id,
                object_id=object_identity.id,
                object_kind="visual_object",
                base_revision_id=base_revision_id,
                proposed_snapshot=dict(snapshot),
                content_hash=canonical_snapshot_hash(dict(snapshot)),
                sequence=int(sequence or 0) + 1,
            )
            session.add(item)
            session.flush()
        else:
            item.proposed_snapshot = dict(snapshot)
            item.content_hash = canonical_snapshot_hash(dict(snapshot))
            item.base_revision_id = item.base_revision_id or base_revision_id
        return item

    def create_object(
        self,
        session: Session,
        *,
        paper_id: UUID,
        actor_id: UUID,
        object_key: str,
        object_type: str | MoleculeObjectType,
        label: str | None = None,
        changeset_id: UUID | None = None,
        expected_version: int | None = None,
        reason: str = "Create molecule object",
    ) -> VisualObject:
        normalized_type = normalize_object_type(object_type)
        snapshot = build_object_snapshot(
            object_key=object_key,
            object_type=normalized_type,
            label=label,
        )
        clean_key = str(snapshot["object_key"])
        if session.scalar(
            select(VisualObject.id).where(
                VisualObject.paper_id == paper_id,
                VisualObject.object_key == clean_key,
            )
        ) is not None:
            raise ObjectValidationError("object_key already exists for this Paper")
        object_identity = VisualObject(
            paper_id=paper_id,
            object_key=clean_key,
            object_type=normalized_type,
        )
        session.add(object_identity)
        session.flush()
        changeset = None
        item = None
        if changeset_id is not None:
            if expected_version is None:
                raise ObjectValidationError("expected_version is required with changeset_id")
            changeset = self._editable_changeset(
                session,
                changeset_id=changeset_id,
                expected_version=expected_version,
                paper_id=paper_id,
            )
            item = self._ensure_item(
                session,
                changeset=changeset,
                object_identity=object_identity,
                snapshot=snapshot,
                base_revision_id=None,
            )
        revision = RevisionService().create_revision(
            session,
            object_identity=object_identity,
            actor_id=actor_id,
            reason=reason,
            snapshot=snapshot,
            changeset_id=changeset.id if changeset is not None else None,
            workflow_state=changeset.workflow_state if changeset is not None else WorkflowState.DRAFT,
        )
        if item is not None:
            item.proposed_revision_id = revision.id
            changeset.version += 1
        session.flush()
        return object_identity

    def update_object(
        self,
        session: Session,
        *,
        object_id: UUID,
        actor_id: UUID,
        object_type: str | MoleculeObjectType,
        label: str | None = None,
        changeset_id: UUID,
        expected_version: int,
        reason: str = "Update molecule object",
    ) -> ObjectRevision:
        object_identity = session.scalar(
            select(VisualObject).where(VisualObject.id == object_id).with_for_update()
        )
        if object_identity is None:
            raise ObjectValidationError("Molecule object not found")
        latest = session.scalar(
            select(ObjectRevision)
            .where(ObjectRevision.object_id == object_id)
            .order_by(ObjectRevision.revision_number.desc())
            .limit(1)
            .with_for_update()
        )
        if latest is None:
            raise ObjectValidationError("Molecule object has no revision")
        changeset = self._editable_changeset(
            session,
            changeset_id=changeset_id,
            expected_version=expected_version,
            paper_id=object_identity.paper_id,
        )
        snapshot = build_object_snapshot(
            object_key=object_identity.object_key,
            object_type=normalize_object_type(object_type),
            label=label,
        )
        item = self._ensure_item(
            session,
            changeset=changeset,
            object_identity=object_identity,
            snapshot=latest.snapshot,
            base_revision_id=latest.id,
        )
        revision = RevisionService().create_revision(
            session,
            object_identity=object_identity,
            actor_id=actor_id,
            reason=reason,
            snapshot=snapshot,
            predecessor=latest,
            changeset_id=changeset.id,
            workflow_state=changeset.workflow_state,
        )
        object_identity.object_type = normalize_object_type(object_type)
        item.proposed_snapshot = snapshot
        item.proposed_revision_id = revision.id
        item.content_hash = canonical_snapshot_hash(snapshot)
        changeset.version += 1
        session.flush()
        return revision
