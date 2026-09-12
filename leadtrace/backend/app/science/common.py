from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.revisions.models import ObjectRevision
from app.revisions.service import RevisionService
from app.reviews.models import Changeset, ChangesetItem
from app.security.policies import WorkflowState


class ScientificVersionConflict(RuntimeError):
    def __init__(self, expected_version: int, current_version: int) -> None:
        self.expected_version = expected_version
        self.current_version = current_version
        super().__init__(
            f"Scientific draft changed concurrently: expected {expected_version}, "
            f"current {current_version}"
        )


def editable_changeset(
    session: Session,
    *,
    changeset_id: UUID,
    expected_version: int,
    paper_id: UUID,
    conflict_type: type[ScientificVersionConflict] = ScientificVersionConflict,
) -> Changeset:
    changeset = session.scalar(
        select(Changeset).where(Changeset.id == changeset_id).with_for_update()
    )
    if changeset is None or changeset.paper_id != paper_id:
        raise ValueError("Changeset does not belong to this Paper")
    if changeset.version != expected_version:
        raise conflict_type(expected_version, changeset.version)
    if changeset.workflow_state not in {WorkflowState.DRAFT, WorkflowState.REVISED_DRAFT}:
        raise ValueError("Only editable draft changesets can be modified")
    return changeset


def snapshot_hash(session: Session, snapshot: Mapping[str, object]) -> str:
    return str(session.scalar(select(func.leadtrace_jsonb_sha256(cast(dict(snapshot), JSONB)))))


def ensure_changeset_item(
    session: Session,
    *,
    changeset: Changeset,
    object_id: UUID,
    object_kind: str,
    snapshot: Mapping[str, object],
    base_revision_id: UUID | None,
) -> ChangesetItem:
    item = session.scalar(
        select(ChangesetItem)
        .where(
            ChangesetItem.changeset_id == changeset.id,
            ChangesetItem.object_id == object_id,
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
            object_id=object_id,
            object_kind=object_kind,
            base_revision_id=base_revision_id,
            proposed_snapshot=dict(snapshot),
            content_hash=snapshot_hash(session, snapshot),
            sequence=int(sequence or 0) + 1,
        )
        session.add(item)
        session.flush()
    else:
        item.proposed_snapshot = dict(snapshot)
        item.content_hash = snapshot_hash(session, snapshot)
        item.base_revision_id = item.base_revision_id or base_revision_id
    return item


def latest_revision(session: Session, object_id: UUID, *, for_update: bool = False) -> ObjectRevision | None:
    statement = (
        select(ObjectRevision)
        .where(ObjectRevision.object_id == object_id)
        .order_by(ObjectRevision.revision_number.desc())
        .limit(1)
    )
    if for_update:
        statement = statement.with_for_update()
    return session.scalar(statement)


def create_draft_revision(
    session: Session,
    *,
    object_identity: object,
    actor_id: UUID,
    reason: str,
    snapshot: dict[str, object],
    changeset: Changeset,
    predecessor: ObjectRevision | None,
    **columns: object,
) -> ObjectRevision:
    revision = RevisionService().create_revision(
        session,
        object_identity=object_identity,
        actor_id=actor_id,
        reason=reason,
        snapshot=snapshot,
        predecessor=predecessor,
        changeset_id=changeset.id,
        workflow_state=changeset.workflow_state,
        **columns,
    )
    changeset.version += 1
    session.flush()
    return revision
