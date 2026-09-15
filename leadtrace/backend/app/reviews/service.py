from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import cast, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.papers.models import Paper
from app.releases.manifest import validate_changeset_binding_delta
from app.releases.models import Release, ReleaseItem
from app.revisions.models import ObjectKind, ObjectRevision, RevisionedObject
from app.reviews.models import (
    Changeset,
    ChangesetItem,
    ChangesetSubmission,
    PaperReviewAttestation,
    PaperReviewScope,
    ReviewTask,
    ReviewTaskStatus,
)
from app.reviews.state_machine import (
    InvalidTransition,
    content_mutable,
    transition_state,
)
from app.security.policies import WorkflowState
from app.users.models import User, UserRole


class ReviewNotFound(LookupError):
    """A requested review resource does not exist."""


class ReviewForbidden(PermissionError):
    """The actor is not allowed to operate on a review resource."""


class RevisionConflict(RuntimeError):
    """An optimistic concurrency check detected a stale version."""

    def __init__(self, expected_version: int, current_version: int) -> None:
        self.expected_version = expected_version
        self.current_version = current_version
        super().__init__(
            "Review resource changed concurrently: "
            f"expected version {expected_version}, current version {current_version}"
        )


class BaseReleaseConflict(RuntimeError):
    """A changeset no longer targets the finalized current release."""

    def __init__(
        self,
        base_release_id: UUID,
        current_release_id: UUID | None,
    ) -> None:
        self.base_release_id = base_release_id
        self.current_release_id = current_release_id
        super().__init__("Changeset base release is not the finalized current release")


class InvalidReview(ValueError):
    """Review input or scope is invalid."""


class ReviewStateConflict(InvalidReview):
    """The requested operation is invalid for the resource's current state."""

    def __init__(self, current_state: str, message: str) -> None:
        self.current_state = current_state
        super().__init__(message)


class ChangesetItemHasRevisions(RuntimeError):
    """A changeset item with immutable linked revisions cannot be deleted."""

    def __init__(self, item_id: UUID) -> None:
        self.item_id = item_id
        super().__init__("Changeset item has linked revisions")


class ChangesetItemHasComments(RuntimeError):
    """A changeset item still has comments anchored to its identity."""

    def __init__(self, item_id: UUID) -> None:
        self.item_id = item_id
        super().__init__("Changeset item has linked comments")


def _clean_required(value: str, field: str) -> str:
    clean = value.strip()
    if not clean:
        raise InvalidReview(f"{field} is required")
    return clean


def _snapshot_hash(session: Session, snapshot: dict[str, object]) -> str:
    return str(
        session.scalar(select(func.leadtrace_jsonb_sha256(cast(snapshot, JSONB))))
    )


def _revision_reason(reason: str) -> str:
    return reason[:500]


_MISSING = object()
_EDITABLE_DEDICATED_FIELDS = (
    "canonical_smiles",
    "evidence_text",
    "activity_metric",
    "activity_value",
    "activity_unit",
    "relation_type",
    "relation_status",
)
_DEDICATED_FIELDS_BY_KIND = {
    ObjectKind.STRUCTURE: frozenset({"canonical_smiles"}),
    ObjectKind.EVIDENCE: frozenset({"evidence_text"}),
    ObjectKind.ACTIVITY: frozenset(
        {"activity_metric", "activity_value", "activity_unit"}
    ),
    ObjectKind.LINEAGE_EDGE: frozenset({"relation_type", "relation_status"}),
}


def _snapshot_field(snapshot: Mapping[str, object], field: str) -> object:
    if field in snapshot:
        return snapshot[field]
    normalized = snapshot.get("normalized_values")
    if isinstance(normalized, Mapping) and field in normalized:
        return normalized[field]
    return _MISSING


def _reject_scoped_paper_status_edit(
    session: Session,
    *,
    changeset: Changeset,
    object_kind: ObjectKind,
    proposed_snapshot: Mapping[str, object],
    base_snapshot: Mapping[str, object] | None,
) -> None:
    """Keep Paper review status server-owned once a scope is frozen."""

    if object_kind is not ObjectKind.PAPER:
        return
    scoped = session.scalar(
        select(PaperReviewScope.id).where(
            PaperReviewScope.changeset_id == changeset.id
        )
    )
    if scoped is None:
        return
    candidate = _snapshot_field(proposed_snapshot, "review_status")
    baseline = (
        _snapshot_field(base_snapshot, "review_status")
        if base_snapshot is not None
        else _MISSING
    )
    if candidate is not _MISSING and candidate != baseline:
        raise InvalidReview(
            "Paper review_status is controlled by the Paper attestation endpoint"
        )


def _evidence_search_text(
    snapshot: Mapping[str, object],
    evidence_text: object,
) -> str | None:
    normalized = snapshot.get("normalized_values")
    if not isinstance(normalized, Mapping):
        return evidence_text if isinstance(evidence_text, str) else None
    values: list[str] = []
    evidence_in_normalized = False
    for field, value in normalized.items():
        if field == "evidence_text":
            evidence_in_normalized = True
            value = evidence_text
        if isinstance(value, str) and value:
            values.append(value)
    if (
        not evidence_in_normalized
        and isinstance(evidence_text, str)
        and evidence_text
    ):
        values.insert(0, evidence_text)
    return " ".join(values) or None


def _revision_column_values(
    predecessor: ObjectRevision | None,
    snapshot: Mapping[str, object],
    *,
    object_kind: ObjectKind,
) -> dict[str, object]:
    """Carry immutable revision columns while applying supported text edits."""

    allowed_fields = _DEDICATED_FIELDS_BY_KIND.get(object_kind, frozenset())
    values: dict[str, object] = {}
    if predecessor is not None:
        values["search_text"] = predecessor.search_text
        if object_kind is ObjectKind.MOLECULE_PROPOSAL:
            values["proposal_disposition"] = predecessor.proposal_disposition
            values["canonical_smiles"] = predecessor.canonical_smiles
        if object_kind is ObjectKind.STRUCTURE:
            values.update(
                structure_state=predecessor.structure_state,
                canonical_smiles=predecessor.canonical_smiles,
            )
        elif object_kind is ObjectKind.EVIDENCE:
            values.update(
                evidence_state=predecessor.evidence_state,
                evidence_text=predecessor.evidence_text,
            )
        elif object_kind is ObjectKind.ACTIVITY:
            values.update(
                activity_state=predecessor.activity_state,
                activity_metric=predecessor.activity_metric,
                activity_value=predecessor.activity_value,
                activity_unit=predecessor.activity_unit,
            )
        elif object_kind is ObjectKind.LINEAGE_EDGE:
            values.update(
                relation_type=predecessor.relation_type,
                relation_status=predecessor.relation_status,
            )
        elif object_kind is ObjectKind.VISUAL_REGION:
            values["region_rotation"] = predecessor.region_rotation

    # Proposal machine fields are immutable through the generic changeset API.
    # The typed proposal service has already validated and materialized the
    # dedicated revision columns, so submission only carries those columns.
    if object_kind is ObjectKind.MOLECULE_PROPOSAL:
        return values

    for field in _EDITABLE_DEDICATED_FIELDS:
        candidate = _snapshot_field(snapshot, field)
        if candidate is _MISSING:
            continue
        if field not in allowed_fields:
            raise InvalidReview(f"{field} is not valid for {object_kind.value}")
        if candidate is not None and not isinstance(candidate, str):
            raise InvalidReview(f"{field} must be text or null")
        values[field] = candidate
    if predecessor is not None and object_kind is ObjectKind.VISUAL_REGION:
        region_coordinates = (
            predecessor.region_x0,
            predecessor.region_y0,
            predecessor.region_x1,
            predecessor.region_y1,
        )
        if all(coordinate is not None for coordinate in region_coordinates):
            values["region_bounds"] = region_coordinates

    if object_kind is ObjectKind.EVIDENCE:
        old_evidence = predecessor.evidence_text if predecessor is not None else None
        new_evidence = values.get("evidence_text")
        if "evidence_text" in values and old_evidence != new_evidence:
            values["search_text"] = _evidence_search_text(snapshot, new_evidence)
    return values


class ReviewService:
    """Transactional review-task and changeset operations.

    The service deliberately accepts a SQLAlchemy session rather than managing
    transactions itself. Callers can therefore compose a submission with audit
    records in one transaction. Mutating operations lock the target row before
    comparing its version, which prevents last-writer-wins updates.
    """

    def create_task(
        self,
        session: Session,
        *,
        paper_id: UUID,
        assignee_id: UUID,
        created_by_id: UUID,
        priority: int = 0,
    ) -> ReviewTask:
        paper = session.scalar(
            select(Paper).where(Paper.id == paper_id).with_for_update()
        )
        if paper is None:
            raise ReviewNotFound("Paper not found")
        assignee = session.get(User, assignee_id)
        creator = session.get(User, created_by_id)
        if assignee is None or creator is None:
            raise ReviewNotFound("User not found")
        if not assignee.is_enabled or not creator.is_enabled:
            raise ReviewForbidden("Review task users must be enabled")
        if creator.role is not UserRole.ADMIN:
            raise ReviewForbidden("Only Admin can create review tasks")
        if assignee.role is not UserRole.REVIEWER:
            raise InvalidReview("Review tasks must be assigned to a Reviewer")
        if priority < 0:
            raise InvalidReview("priority cannot be negative")
        existing_assignment = session.scalar(
            select(ReviewTask.id)
            .where(
                ReviewTask.paper_id == paper_id,
                ReviewTask.status != ReviewTaskStatus.COMPLETED,
            )
            .limit(1)
        )
        if existing_assignment is not None:
            raise InvalidReview("Paper already has an active review task")
        task = ReviewTask(
            paper_id=paper_id,
            assigned_reviewer_id=assignee_id,
            created_by_id=created_by_id,
            priority=priority,
            status=ReviewTaskStatus.OPEN,
            version=1,
        )
        session.add(task)
        session.flush()
        return task

    def list_tasks(
        self,
        session: Session,
        reviewer_id: UUID | None = None,
    ) -> list[ReviewTask]:
        statement = select(ReviewTask).order_by(
            ReviewTask.priority.desc(), ReviewTask.created_at, ReviewTask.id
        )
        if reviewer_id is not None:
            statement = statement.where(ReviewTask.assigned_reviewer_id == reviewer_id)
        return list(session.scalars(statement))

    def create_changeset(
        self,
        session: Session,
        *,
        paper_id: UUID,
        actor_id: UUID,
        review_task_id: UUID,
        base_release_id: UUID,
        title: str,
        reason: str,
        validation_results: dict[str, object] | None = None,
    ) -> Changeset:
        if session.get(Paper, paper_id) is None:
            raise ReviewNotFound("Paper not found")
        actor = self._get_actor(session, actor_id)
        if actor.role not in {UserRole.REVIEWER, UserRole.ADMIN}:
            raise ReviewForbidden("Only Reviewer or Admin can create changesets")
        task = session.scalar(
            select(ReviewTask)
            .where(ReviewTask.id == review_task_id)
            .with_for_update()
        )
        if task is None:
            raise ReviewNotFound("Review task not found")
        if task.paper_id != paper_id:
            raise ReviewForbidden("Changeset task scope does not match Paper")
        if (
            actor.role is UserRole.REVIEWER
            and task.assigned_reviewer_id != actor_id
        ):
            raise ReviewForbidden("Reviewer is not assigned to the review task")
        owner = session.get(User, task.assigned_reviewer_id)
        if (
            owner is None
            or not owner.is_enabled
            or owner.role is not UserRole.REVIEWER
        ):
            raise ReviewForbidden("Changeset owner must be an enabled Reviewer")
        self._validate_base_release(
            session,
            base_release_id=base_release_id,
            paper_id=paper_id,
            lock=True,
        )
        if task.status not in {
            ReviewTaskStatus.OPEN,
            ReviewTaskStatus.IN_PROGRESS,
            ReviewTaskStatus.CHANGES_REQUESTED,
        }:
            raise ReviewStateConflict(
                task.status.value,
                "Review task is not accepting a changeset",
            )
        existing_changeset = session.scalar(
            select(Changeset.id)
            .where(Changeset.review_task_id == review_task_id)
            .limit(1)
        )
        if existing_changeset is not None:
            raise ReviewStateConflict(
                task.status.value,
                "Review task already has a changeset",
            )
        if task.status is ReviewTaskStatus.OPEN:
            task.status = ReviewTaskStatus.IN_PROGRESS
            task.version += 1
        changeset = Changeset(
            paper_id=paper_id,
            owner_id=owner.id,
            review_task_id=review_task_id,
            base_release_id=base_release_id,
            title=_clean_required(title, "title"),
            reason=_clean_required(reason, "reason"),
            workflow_state=WorkflowState.DRAFT,
            version=1,
            validation_results=validation_results or {},
        )
        session.add(changeset)
        session.flush()
        return changeset

    def get_changeset(
        self,
        session: Session,
        changeset_id: UUID,
        *,
        for_update: bool = False,
    ) -> Changeset:
        statement = select(Changeset).where(Changeset.id == changeset_id)
        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        changeset = session.scalar(statement)
        if changeset is None:
            raise ReviewNotFound("Changeset not found")
        return changeset

    def list_changesets(
        self,
        session: Session,
        *,
        owner_id: UUID | None = None,
    ) -> list[Changeset]:
        statement = select(Changeset).order_by(
            Changeset.updated_at.desc(), Changeset.id
        )
        if owner_id is not None:
            statement = statement.where(Changeset.owner_id == owner_id)
        return list(session.scalars(statement))

    def update_changeset(
        self,
        session: Session,
        *,
        changeset_id: UUID,
        actor_id: UUID,
        expected_version: int,
        title: str | None = None,
        reason: str | None = None,
        validation_results: dict[str, object] | None = None,
    ) -> Changeset:
        changeset = self.get_changeset(session, changeset_id, for_update=True)
        self._authorize_owner_or_admin(session, changeset, actor_id)
        self._check_version(changeset, expected_version)
        if not content_mutable(changeset.workflow_state):
            raise ReviewStateConflict(
                changeset.workflow_state.value,
                "Only draft changesets can be edited",
            )
        if title is not None:
            changeset.title = _clean_required(title, "title")
        if reason is not None:
            changeset.reason = _clean_required(reason, "reason")
        if validation_results is not None:
            changeset.validation_results = validation_results
        changeset.version += 1
        session.flush()
        return changeset

    def add_changeset_item(
        self,
        session: Session,
        *,
        changeset_id: UUID,
        actor_id: UUID,
        expected_version: int,
        object_id: UUID,
        object_kind: str,
        proposed_snapshot: dict[str, object],
        base_revision_id: UUID | None = None,
        sequence: int | None = None,
    ) -> ChangesetItem:
        changeset = self.get_changeset(session, changeset_id, for_update=True)
        self._authorize_owner_or_admin(session, changeset, actor_id)
        self._check_version(changeset, expected_version)
        if not content_mutable(changeset.workflow_state):
            raise ReviewStateConflict(
                changeset.workflow_state.value,
                "Submitted changeset items are immutable",
            )
        if not object_kind.strip():
            raise InvalidReview("object_kind is required")
        try:
            parsed_kind = ObjectKind(object_kind.strip())
        except ValueError as error:
            raise InvalidReview("object_kind is not supported") from error
        if parsed_kind is ObjectKind.MOLECULE_PROPOSAL:
            raise InvalidReview(
                "Molecule proposals must be edited through the typed proposal endpoint"
            )
        object_identity = session.get(RevisionedObject, object_id)
        if object_identity is None:
            raise ReviewNotFound("Revisioned object not found")
        if object_identity.object_kind is not parsed_kind:
            raise InvalidReview("object_kind does not match the object")
        object_paper_id = self._paper_id_for_object(
            session,
            object_id=object_id,
            object_kind=parsed_kind,
        )
        if object_paper_id != changeset.paper_id:
            raise InvalidReview("Changeset items must belong to one Paper")
        self._validate_base_item(
            session,
            changeset=changeset,
            object_id=object_id,
            base_revision_id=base_revision_id,
        )
        base_revision = (
            session.get(ObjectRevision, base_revision_id)
            if base_revision_id is not None
            else None
        )
        _reject_scoped_paper_status_edit(
            session,
            changeset=changeset,
            object_kind=parsed_kind,
            proposed_snapshot=proposed_snapshot,
            base_snapshot=base_revision.snapshot if base_revision is not None else None,
        )
        _revision_column_values(
            base_revision,
            proposed_snapshot,
            object_kind=parsed_kind,
        )
        if sequence is None:
            latest = session.scalar(
                select(ChangesetItem.sequence)
                .where(ChangesetItem.changeset_id == changeset.id)
                .order_by(ChangesetItem.sequence.desc())
                .limit(1)
            )
            sequence = int(latest or 0) + 1
        if sequence < 1:
            raise InvalidReview("sequence must be positive")
        item = ChangesetItem(
            changeset_id=changeset.id,
            paper_id=changeset.paper_id,
            object_id=object_id,
            object_kind=parsed_kind.value,
            base_revision_id=base_revision_id,
            proposed_snapshot=proposed_snapshot,
            content_hash=_snapshot_hash(session, proposed_snapshot),
            sequence=sequence,
        )
        session.add(item)
        changeset.version += 1
        session.flush()
        return item

    def list_changeset_items(
        self,
        session: Session,
        *,
        changeset_id: UUID,
        actor_id: UUID,
    ) -> tuple[Changeset, list[ChangesetItem]]:
        changeset = self.get_changeset(session, changeset_id)
        self._authorize_owner_or_admin(session, changeset, actor_id)
        items = list(
            session.scalars(
                select(ChangesetItem)
                .where(ChangesetItem.changeset_id == changeset_id)
                .order_by(ChangesetItem.sequence)
            )
        )
        return changeset, items

    def update_changeset_item(
        self,
        session: Session,
        *,
        changeset_id: UUID,
        item_id: UUID,
        actor_id: UUID,
        expected_version: int,
        proposed_snapshot: dict[str, object],
    ) -> tuple[Changeset, ChangesetItem]:
        changeset = self.get_changeset(session, changeset_id, for_update=True)
        self._authorize_owner_or_admin(session, changeset, actor_id)
        self._check_version(changeset, expected_version)
        if not content_mutable(changeset.workflow_state):
            raise ReviewStateConflict(
                changeset.workflow_state.value,
                "Only draft changeset items can be edited",
            )
        item = session.scalar(
            select(ChangesetItem).where(
                ChangesetItem.id == item_id,
                ChangesetItem.changeset_id == changeset_id,
            ).execution_options(populate_existing=True)
        )
        if item is None:
            raise ReviewNotFound("Changeset item not found")
        validation_predecessor = (
            session.get(
                ObjectRevision,
                item.proposed_revision_id or item.base_revision_id,
            )
            if item.proposed_revision_id is not None
            or item.base_revision_id is not None
            else None
        )
        _reject_scoped_paper_status_edit(
            session,
            changeset=changeset,
            object_kind=ObjectKind(item.object_kind),
            proposed_snapshot=proposed_snapshot,
            base_snapshot=(
                validation_predecessor.snapshot
                if validation_predecessor is not None
                else None
            ),
        )
        _revision_column_values(
            validation_predecessor,
            proposed_snapshot,
            object_kind=ObjectKind(item.object_kind),
        )
        if ObjectKind(item.object_kind) is ObjectKind.MOLECULE_PROPOSAL:
            raise InvalidReview(
                "Molecule proposals must be edited through the typed proposal endpoint"
            )
        proposed_content_hash = _snapshot_hash(session, proposed_snapshot)
        content_changed = (
            item.proposed_snapshot != proposed_snapshot
            or item.content_hash != proposed_content_hash
        )
        if not content_changed:
            changeset.version += 1
            session.flush([changeset])
            return changeset, item

        previous_revision = None
        if item.proposed_revision_id is not None:
            previous_revision = session.scalar(
                select(ObjectRevision)
                .where(
                    ObjectRevision.id == item.proposed_revision_id,
                    ObjectRevision.changeset_id == changeset_id,
                    ObjectRevision.object_id == item.object_id,
                )
                .with_for_update()
            )
            if previous_revision is None:
                raise InvalidReview("Changeset proposal revision is invalid")
        item.proposed_revision_id = None
        item.proposed_snapshot = proposed_snapshot
        item.content_hash = proposed_content_hash
        changeset.version += 1
        session.flush([changeset, item])
        latest_revision = None
        if previous_revision is None:
            latest_revision = session.scalar(
                select(ObjectRevision)
                .where(
                    ObjectRevision.changeset_id == changeset_id,
                    ObjectRevision.object_id == item.object_id,
                )
                .order_by(ObjectRevision.revision_number.desc())
                .limit(1)
            )
            if (
                latest_revision is not None
                and latest_revision.snapshot == item.proposed_snapshot
                and latest_revision.content_hash == item.content_hash
            ):
                item.proposed_revision_id = latest_revision.id
                session.flush([item])
                return changeset, item

        predecessor = previous_revision or latest_revision
        if predecessor is not None:
            from app.revisions.service import RevisionService

            object_identity = session.get(RevisionedObject, item.object_id)
            if object_identity is None:
                raise ReviewNotFound("Revisioned object not found")
            revision = RevisionService().create_revision(
                session,
                object_identity=object_identity,
                actor_id=actor_id,
                reason=_revision_reason(changeset.reason),
                snapshot=item.proposed_snapshot,
                predecessor=predecessor,
                changeset_id=changeset.id,
                workflow_state=changeset.workflow_state,
                **_revision_column_values(
                    predecessor,
                    item.proposed_snapshot,
                    object_kind=ObjectKind(item.object_kind),
                ),
            )
            item.proposed_revision_id = revision.id
            session.flush([item])
        return changeset, item

    def delete_changeset_item(
        self,
        session: Session,
        *,
        changeset_id: UUID,
        item_id: UUID,
        actor_id: UUID,
        expected_version: int,
    ) -> Changeset:
        changeset = self.get_changeset(session, changeset_id, for_update=True)
        self._authorize_owner_or_admin(session, changeset, actor_id)
        self._check_version(changeset, expected_version)
        if not content_mutable(changeset.workflow_state):
            raise ReviewStateConflict(
                changeset.workflow_state.value,
                "Only draft changeset items can be deleted",
            )
        item = session.scalar(
            select(ChangesetItem).where(
                ChangesetItem.id == item_id,
                ChangesetItem.changeset_id == changeset_id,
            ).execution_options(populate_existing=True)
        )
        if item is None:
            raise ReviewNotFound("Changeset item not found")
        linked_revision = session.scalar(
            select(ObjectRevision.id)
            .where(
                ObjectRevision.changeset_id == changeset_id,
                ObjectRevision.object_id == item.object_id,
            )
            .limit(1)
        )
        if linked_revision is not None:
            raise ChangesetItemHasRevisions(item.id)
        from app.reviews.comments import CommentTargetType, ReviewComment

        comment_anchors = [
            ReviewComment.changeset_item_id == item.id,
            ReviewComment.target_id == item.id,
        ]
        # A Paper field comment may intentionally predate its changeset item.
        # Keep that compatibility anchor, while preserving traceability for
        # all object-level anchors (and field anchors on non-Paper objects).
        if item.object_kind == ObjectKind.PAPER.value:
            comment_anchors.append(
                (ReviewComment.target_id == item.object_id)
                & (ReviewComment.target_type != CommentTargetType.FIELD.value)
            )
        else:
            comment_anchors.append(ReviewComment.target_id == item.object_id)
        linked_comment = session.scalar(
            select(ReviewComment.id)
            .where(
                ReviewComment.changeset_id == changeset.id,
                or_(*comment_anchors),
            )
            .limit(1)
        )
        if linked_comment is not None:
            raise ChangesetItemHasComments(item.id)
        session.delete(item)
        changeset.version += 1
        session.flush()
        return changeset

    def submit_changeset(
        self,
        session: Session,
        *,
        changeset_id: UUID,
        actor_id: UUID,
        expected_version: int,
    ) -> Changeset:
        changeset = self.get_changeset(session, changeset_id, for_update=True)
        self._authorize_owner_or_admin(session, changeset, actor_id)
        self._check_version(changeset, expected_version)
        if changeset.workflow_state not in {
            WorkflowState.DRAFT,
            WorkflowState.REVISED_DRAFT,
        }:
            raise ReviewStateConflict(
                changeset.workflow_state.value,
                "Only a draft changeset can be submitted",
            )
        actor = session.get(User, actor_id)
        if actor is None:
            raise ReviewNotFound("User not found")
        task = session.scalar(
            select(ReviewTask)
            .where(ReviewTask.id == changeset.review_task_id)
            .with_for_update()
        )
        if (
            task is None
            or task.paper_id != changeset.paper_id
            or task.assigned_reviewer_id != changeset.owner_id
            or task.status
            not in {
                ReviewTaskStatus.IN_PROGRESS,
                ReviewTaskStatus.CHANGES_REQUESTED,
            }
        ):
            raise ReviewForbidden("Changeset is outside its active review task")
        # Keep the lock order consistent with create_changeset: ReviewTask
        # before the base Release. This prevents create/submit deadlocks when
        # both transactions concurrently inspect the same review scope.
        self._validate_base_release(
            session,
            base_release_id=changeset.base_release_id,
            paper_id=changeset.paper_id,
            lock=True,
        )
        scope = session.scalar(
            select(PaperReviewScope)
            .where(PaperReviewScope.changeset_id == changeset.id)
            .with_for_update()
        )
        attestation = None
        if scope is not None:
            attestation = session.scalar(
                select(PaperReviewAttestation)
                .where(
                    PaperReviewAttestation.changeset_id == changeset.id,
                    PaperReviewAttestation.scope_id == scope.id,
                    PaperReviewAttestation.changeset_version == changeset.version,
                    PaperReviewAttestation.scope_hash == scope.scope_hash,
                    PaperReviewAttestation.blocker_count == 0,
                    PaperReviewAttestation.resolved_count
                    == PaperReviewAttestation.item_count,
                )
                .order_by(PaperReviewAttestation.created_at.desc())
                .limit(1)
            )
            if attestation is None:
                raise InvalidReview(
                    "A current Paper review attestation is required before submission"
                )
        transition_state(changeset.workflow_state, WorkflowState.SUBMITTED)
        items = list(
            session.scalars(
                select(ChangesetItem)
                .where(ChangesetItem.changeset_id == changeset.id)
                .order_by(ChangesetItem.sequence)
            )
        )
        if not items:
            raise InvalidReview("A changeset must contain at least one item")
        try:
            validate_changeset_binding_delta(session, changeset)
        except ValueError as error:
            raise InvalidReview(f"Binding delta is invalid: {error}") from error
        for item in items:
            self._validate_base_item(
                session,
                changeset=changeset,
                object_id=item.object_id,
                base_revision_id=item.base_revision_id,
            )
            validation_predecessor = (
                session.get(
                    ObjectRevision,
                    item.proposed_revision_id or item.base_revision_id,
                )
                if item.proposed_revision_id is not None
                or item.base_revision_id is not None
                else None
            )
            _revision_column_values(
                validation_predecessor,
                item.proposed_snapshot,
                object_kind=ObjectKind(item.object_kind),
            )
            matching_revision = session.scalar(
                select(ObjectRevision)
                .where(
                    ObjectRevision.changeset_id == changeset.id,
                    ObjectRevision.object_id == item.object_id,
                    ObjectRevision.snapshot == item.proposed_snapshot,
                    ObjectRevision.content_hash == item.content_hash,
                    ObjectRevision.workflow_state.in_(
                        {WorkflowState.DRAFT, WorkflowState.REVISED_DRAFT}
                    ),
                    ObjectRevision.is_current_published.is_(False),
                )
                .order_by(ObjectRevision.revision_number.desc())
                .limit(1)
            )
            if matching_revision is None:
                any_linked_revision = session.scalar(
                    select(ObjectRevision.id)
                    .where(
                        ObjectRevision.changeset_id == changeset.id,
                        ObjectRevision.object_id == item.object_id,
                    )
                    .limit(1)
                )
                if any_linked_revision is not None:
                    raise InvalidReview(
                        "Changeset item has no matching immutable revision"
                    )
                from app.revisions.service import RevisionService

                object_identity = session.get(RevisionedObject, item.object_id)
                if object_identity is None:
                    raise ReviewNotFound("Revisioned object not found")
                predecessor = (
                    session.get(ObjectRevision, item.base_revision_id)
                    if item.base_revision_id is not None
                    else None
                )
                matching_revision = RevisionService().create_revision(
                    session,
                    object_identity=object_identity,
                    actor_id=actor_id,
                    reason=_revision_reason(changeset.reason),
                    snapshot=item.proposed_snapshot,
                    predecessor=predecessor,
                    changeset_id=changeset.id,
                    workflow_state=changeset.workflow_state,
                    **_revision_column_values(
                        predecessor,
                        item.proposed_snapshot,
                        object_kind=ObjectKind(item.object_kind),
                    ),
                )
            item.proposed_revision_id = matching_revision.id
        session.flush(items)
        submitted_snapshot = session.scalar(
            select(
                cast(
                    func.leadtrace_changeset_snapshot(changeset.id),
                    JSONB,
                )
            )
        )
        submitted_content_hash = session.scalar(
            select(func.leadtrace_changeset_snapshot_hash(changeset.id))
        )
        if submitted_snapshot is None or submitted_content_hash is None:
            raise InvalidReview("Changeset snapshot could not be generated")
        changeset.submitted_snapshot = submitted_snapshot
        changeset.submitted_content_hash = submitted_content_hash
        changeset.workflow_state = WorkflowState.SUBMITTED
        if changeset.submitted_at is None:
            changeset.submitted_at = datetime.now(UTC)
        changeset.version += 1
        session.flush([changeset])
        latest_submission = session.scalar(
            select(func.max(ChangesetSubmission.submission_number)).where(
                ChangesetSubmission.changeset_id == changeset.id
            )
        )
        session.add(
            ChangesetSubmission(
                changeset_id=changeset.id,
                submission_number=int(latest_submission or 0) + 1,
                changeset_version=changeset.version,
                submitted_by_id=actor_id,
                snapshot=submitted_snapshot,
                content_hash=submitted_content_hash,
            )
        )
        task.status = ReviewTaskStatus.SUBMITTED
        task.version += 1
        session.flush()
        return changeset

    def transition_changeset(
        self,
        session: Session,
        *,
        changeset_id: UUID,
        actor_id: UUID,
        expected_version: int,
        next_state: WorkflowState,
    ) -> Changeset:
        changeset = self.get_changeset(session, changeset_id, for_update=True)
        actor = self._get_actor(session, actor_id)
        self._check_version(changeset, expected_version)
        if actor.role is not UserRole.ADMIN:
            raise ReviewForbidden("Only Admin can approve or publish a changeset")
        try:
            transition_state(changeset.workflow_state, next_state)
        except InvalidTransition as error:
            raise ReviewStateConflict(
                changeset.workflow_state.value,
                str(error),
            ) from error
        changeset.workflow_state = next_state
        changeset.version += 1
        next_task_status = {
            WorkflowState.CHANGES_REQUESTED: ReviewTaskStatus.CHANGES_REQUESTED,
            WorkflowState.REJECTED: ReviewTaskStatus.COMPLETED,
            WorkflowState.APPROVED: ReviewTaskStatus.COMPLETED,
        }.get(next_state)
        if next_task_status is not None:
            task = session.scalar(
                select(ReviewTask)
                .where(ReviewTask.id == changeset.review_task_id)
                .with_for_update()
            )
            if task is None:
                raise ReviewNotFound("Review task not found")
            task.status = next_task_status
            task.version += 1
        session.flush()
        return changeset

    def revise_changeset(
        self,
        session: Session,
        *,
        changeset_id: UUID,
        actor_id: UUID,
        expected_version: int,
    ) -> Changeset:
        changeset = self.get_changeset(session, changeset_id, for_update=True)
        self._authorize_owner_or_admin(session, changeset, actor_id)
        self._check_version(changeset, expected_version)
        try:
            transition_state(changeset.workflow_state, WorkflowState.REVISED_DRAFT)
        except InvalidTransition as error:
            raise ReviewStateConflict(
                changeset.workflow_state.value,
                str(error),
            ) from error
        changeset.workflow_state = WorkflowState.REVISED_DRAFT
        changeset.version += 1
        task = session.scalar(
            select(ReviewTask)
            .where(ReviewTask.id == changeset.review_task_id)
            .with_for_update()
        )
        if task is None:
            raise ReviewNotFound("Review task not found")
        task.status = ReviewTaskStatus.IN_PROGRESS
        task.version += 1
        session.flush()
        return changeset

    def reassign_task(
        self,
        session: Session,
        *,
        task_id: UUID,
        actor_id: UUID,
        assignee_id: UUID,
        expected_version: int,
    ) -> ReviewTask:
        actor = self._get_actor(session, actor_id)
        if actor.role is not UserRole.ADMIN:
            raise ReviewForbidden("Only Admin can reassign review tasks")
        task = session.scalar(
            select(ReviewTask)
            .where(ReviewTask.id == task_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if task is None:
            raise ReviewNotFound("Review task not found")
        if task.version != expected_version:
            raise RevisionConflict(expected_version, task.version)
        assignee = session.get(User, assignee_id)
        if assignee is None or not assignee.is_enabled:
            raise ReviewNotFound("Reviewer not found")
        if assignee.role is not UserRole.REVIEWER:
            raise InvalidReview("Review tasks must be assigned to a Reviewer")
        if task.status is not ReviewTaskStatus.OPEN:
            raise ReviewStateConflict(
                task.status.value,
                "Only open tasks can be reassigned",
            )
        existing_assignment = session.scalar(
            select(ReviewTask.id)
            .where(
                ReviewTask.paper_id == task.paper_id,
                ReviewTask.assigned_reviewer_id == assignee_id,
                ReviewTask.id != task.id,
                ReviewTask.status != ReviewTaskStatus.COMPLETED,
            )
            .limit(1)
        )
        if existing_assignment is not None:
            raise InvalidReview("Reviewer already has an active task for this Paper")
        task.assigned_reviewer_id = assignee_id
        task.version += 1
        session.flush()
        return task

    def _authorize_owner_or_admin(
        self,
        session: Session,
        changeset: Changeset,
        actor_id: UUID,
    ) -> User:
        actor = self._get_actor(session, actor_id)
        if actor.role is not UserRole.ADMIN and changeset.owner_id != actor_id:
            raise ReviewNotFound("Changeset not found")
        return actor

    @staticmethod
    def _check_version(changeset: Changeset, expected_version: int) -> None:
        if expected_version != changeset.version:
            raise RevisionConflict(expected_version, changeset.version)

    @staticmethod
    def _get_actor(session: Session, actor_id: UUID) -> User:
        actor = session.get(User, actor_id)
        if actor is None or not actor.is_enabled:
            raise ReviewForbidden("Actor is not an enabled user")
        return actor

    @staticmethod
    def _paper_id_for_object(
        session: Session,
        *,
        object_id: UUID,
        object_kind: ObjectKind,
    ) -> UUID | None:
        if object_kind is ObjectKind.PAPER:
            return object_id if session.get(Paper, object_id) is not None else None

        from app.activities.models import Activity
        from app.compounds.models import Compound
        from app.evidence.models import Evidence
        from app.lineages.models import Lineage, LineageEdge
        from app.structures.models import Structure
        from app.molecule_proposals.models import MoleculeProposal
        from app.visual_objects.models import VisualObject, VisualRegion

        model_by_kind = {
            ObjectKind.ACTIVITY: Activity,
            ObjectKind.COMPOUND: Compound,
            ObjectKind.EVIDENCE: Evidence,
            ObjectKind.LINEAGE: Lineage,
            ObjectKind.LINEAGE_EDGE: LineageEdge,
            ObjectKind.STRUCTURE: Structure,
            ObjectKind.VISUAL_OBJECT: VisualObject,
            ObjectKind.VISUAL_REGION: VisualRegion,
            ObjectKind.MOLECULE_PROPOSAL: MoleculeProposal,
        }
        model = model_by_kind.get(object_kind)
        record = session.get(model, object_id) if model is not None else None
        return record.paper_id if record is not None else None

    @staticmethod
    def _validate_base_release(
        session: Session,
        *,
        base_release_id: UUID,
        paper_id: UUID,
        lock: bool,
    ) -> Release:
        statement = select(Release).where(Release.id == base_release_id)
        if lock:
            statement = statement.with_for_update()
        release = session.scalar(statement)
        if release is None:
            raise ReviewNotFound("Base release not found")
        current_release_id = session.scalar(
            select(Release.id).where(
                Release.is_current.is_(True),
                Release.manifest_finalized.is_(True),
            )
        )
        if (
            not release.manifest_finalized
            or not release.is_current
            or current_release_id != release.id
        ):
            raise BaseReleaseConflict(base_release_id, current_release_id)
        paper_item = session.scalar(
            select(ReleaseItem.id)
            .where(
                ReleaseItem.release_id == release.id,
                ReleaseItem.paper_id == paper_id,
                ReleaseItem.object_id == paper_id,
                ReleaseItem.object_kind == ObjectKind.PAPER,
            )
            .limit(1)
        )
        if paper_item is None:
            raise InvalidReview("Base release does not contain the review Paper")
        return release

    @staticmethod
    def _validate_base_item(
        session: Session,
        *,
        changeset: Changeset,
        object_id: UUID,
        base_revision_id: UUID | None,
    ) -> None:
        release_item = session.scalar(
            select(ReleaseItem)
            .where(
                ReleaseItem.release_id == changeset.base_release_id,
                ReleaseItem.paper_id == changeset.paper_id,
                ReleaseItem.object_id == object_id,
            )
            .limit(1)
        )
        if base_revision_id is not None:
            if release_item is None or release_item.revision_id != base_revision_id:
                raise InvalidReview(
                    "base_revision_id is not the object's base-release revision"
                )
            return
        if release_item is not None:
            raise InvalidReview("Existing base-release objects require base_revision_id")
        prior_revision = session.scalar(
            select(ObjectRevision.id)
            .where(
                ObjectRevision.object_id == object_id,
                ObjectRevision.changeset_id.is_distinct_from(changeset.id),
            )
            .limit(1)
        )
        if prior_revision is not None:
            raise InvalidReview(
                "Objects outside the base release cannot reuse an existing revision"
            )
