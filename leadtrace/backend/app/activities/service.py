from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activities.models import Activity
from app.compounds.models import Compound
from app.evidence.models import Evidence
from app.revisions.models import ActivityState, ObjectRevision
from app.science.common import (
    ScientificVersionConflict,
    create_draft_revision,
    editable_changeset,
    ensure_changeset_item,
    latest_revision,
)


class ActivityValidationError(ValueError):
    """Raised when assay data is incomplete or ambiguous."""


@dataclass(frozen=True, slots=True)
class ActivityDraft:
    activity_key: str
    compound_id: UUID
    assay: str
    metric: str
    value: str
    unit: str
    qualifier: str = ""
    evidence_text: str = ""
    evidence_ids: tuple[UUID, ...] = ()


def validate_activity_draft(draft: ActivityDraft) -> ActivityDraft:
    fields = {
        "activity_key": draft.activity_key,
        "assay": draft.assay,
        "metric": draft.metric,
        "value": draft.value,
        "unit": draft.unit,
        "evidence_text": draft.evidence_text,
    }
    if any(not str(value).strip() for value in fields.values()):
        raise ActivityValidationError(
            "activity_key, assay, metric, value, unit, and evidence_text are required"
        )
    if len(set(draft.evidence_ids)) != len(draft.evidence_ids):
        raise ActivityValidationError("Activity evidence references must be unique")
    return ActivityDraft(
        activity_key=draft.activity_key.strip(),
        compound_id=draft.compound_id,
        assay=draft.assay.strip(),
        metric=draft.metric.strip(),
        value=draft.value.strip(),
        unit=draft.unit.strip(),
        qualifier=draft.qualifier.strip(),
        evidence_text=draft.evidence_text.strip(),
        evidence_ids=tuple(draft.evidence_ids),
    )


class ActivityVersionConflict(ScientificVersionConflict):
    pass


class ActivityReviewService:
    def create_activity(
        self,
        session: Session,
        *,
        paper_id: UUID,
        actor_id: UUID,
        changeset_id: UUID,
        expected_version: int,
        draft: ActivityDraft,
        reason: str,
    ) -> tuple[Activity, ObjectRevision]:
        clean = validate_activity_draft(draft)
        reason = reason.strip()
        if not reason:
            raise ActivityValidationError("reason is required")
        compound = session.get(Compound, clean.compound_id)
        if compound is None or compound.paper_id != paper_id:
            raise ActivityValidationError("Activity compound must belong to this Paper")
        evidence = session.scalars(select(Evidence).where(Evidence.id.in_(clean.evidence_ids))).all()
        if len(evidence) != len(clean.evidence_ids) or any(item.paper_id != paper_id for item in evidence):
            raise ActivityValidationError("Activity evidence must belong to this Paper")
        changeset = editable_changeset(session, changeset_id=changeset_id, expected_version=expected_version, paper_id=paper_id, conflict_type=ActivityVersionConflict)
        if session.scalar(select(Activity.id).where(Activity.paper_id == paper_id, Activity.activity_key == clean.activity_key)) is not None:
            raise ActivityValidationError("activity_key already exists for this Paper")
        activity = Activity(paper_id=paper_id, compound_id=clean.compound_id, activity_key=clean.activity_key)
        session.add(activity)
        session.flush()
        snapshot = {
            "activity_key": clean.activity_key,
            "compound_id": str(clean.compound_id),
            "assay": clean.assay,
            "metric": clean.metric,
            "value": clean.value,
            "unit": clean.unit,
            "qualifier": clean.qualifier,
            "evidence_text": clean.evidence_text,
            "evidence_ids": [str(item) for item in clean.evidence_ids],
        }
        item = ensure_changeset_item(session, changeset=changeset, object_id=activity.id, object_kind="activity", snapshot=snapshot, base_revision_id=None)
        revision = create_draft_revision(
            session,
            object_identity=activity,
            actor_id=actor_id,
            reason=reason,
            snapshot=snapshot,
            changeset=changeset,
            predecessor=None,
            activity_state=ActivityState.SOURCE_BOUND,
            activity_metric=clean.metric,
            activity_value=clean.value,
            activity_unit=clean.unit,
            evidence_text=clean.evidence_text,
        )
        item.proposed_revision_id = revision.id
        session.flush()
        return activity, revision

    def update_activity(
        self,
        session: Session,
        *,
        activity_id: UUID,
        actor_id: UUID,
        changeset_id: UUID,
        expected_version: int,
        draft: ActivityDraft,
        reason: str,
    ) -> ObjectRevision:
        activity = session.scalar(select(Activity).where(Activity.id == activity_id).with_for_update())
        if activity is None:
            raise ActivityValidationError("Activity not found")
        clean = validate_activity_draft(draft)
        reason = reason.strip()
        if not reason:
            raise ActivityValidationError("reason is required")
        if clean.activity_key != activity.activity_key:
            raise ActivityValidationError("activity_key is immutable")
        compound = session.get(Compound, clean.compound_id)
        if compound is None or compound.paper_id != activity.paper_id:
            raise ActivityValidationError("Activity compound must belong to this Paper")
        evidence = session.scalars(select(Evidence).where(Evidence.id.in_(clean.evidence_ids))).all()
        if len(evidence) != len(clean.evidence_ids) or any(item.paper_id != activity.paper_id for item in evidence):
            raise ActivityValidationError("Activity evidence must belong to this Paper")
        changeset = editable_changeset(session, changeset_id=changeset_id, expected_version=expected_version, paper_id=activity.paper_id, conflict_type=ActivityVersionConflict)
        previous = latest_revision(session, activity.id, for_update=True)
        if previous is None:
            raise ActivityValidationError("Activity has no revision")
        if previous.is_tombstone:
            raise ActivityValidationError("Activity is deleted")
        snapshot = {
            "activity_key": activity.activity_key,
            "compound_id": str(clean.compound_id),
            "assay": clean.assay,
            "metric": clean.metric,
            "value": clean.value,
            "unit": clean.unit,
            "qualifier": clean.qualifier,
            "evidence_text": clean.evidence_text,
            "evidence_ids": [str(item) for item in clean.evidence_ids],
        }
        item = ensure_changeset_item(session, changeset=changeset, object_id=activity.id, object_kind="activity", snapshot=previous.snapshot, base_revision_id=previous.id)
        revision = create_draft_revision(
            session,
            object_identity=activity,
            actor_id=actor_id,
            reason=reason,
            snapshot=snapshot,
            changeset=changeset,
            predecessor=previous,
            activity_state=ActivityState.SOURCE_BOUND,
            activity_metric=clean.metric,
            activity_value=clean.value,
            activity_unit=clean.unit,
            evidence_text=clean.evidence_text,
        )
        item.proposed_snapshot = snapshot
        item.proposed_revision_id = revision.id
        item.content_hash = revision.content_hash
        session.flush()
        return revision

    def delete_activity(
        self,
        session: Session,
        *,
        activity_id: UUID,
        actor_id: UUID,
        changeset_id: UUID,
        expected_version: int,
        reason: str,
    ) -> ObjectRevision:
        activity = session.scalar(
            select(Activity).where(Activity.id == activity_id).with_for_update()
        )
        if activity is None:
            raise ActivityValidationError("Activity not found")
        clean_reason = reason.strip()
        if not clean_reason:
            raise ActivityValidationError("reason is required")
        changeset = editable_changeset(
            session,
            changeset_id=changeset_id,
            expected_version=expected_version,
            paper_id=activity.paper_id,
            conflict_type=ActivityVersionConflict,
        )
        previous = latest_revision(session, activity.id, for_update=True)
        if previous is None:
            raise ActivityValidationError("Activity has no revision")
        if previous.is_tombstone:
            raise ActivityValidationError("Activity is already deleted")
        snapshot = dict(previous.snapshot)
        snapshot["deleted"] = True
        item = ensure_changeset_item(
            session,
            changeset=changeset,
            object_id=activity.id,
            object_kind="activity",
            snapshot=previous.snapshot,
            base_revision_id=previous.id,
        )
        revision = create_draft_revision(
            session,
            object_identity=activity,
            actor_id=actor_id,
            reason=clean_reason,
            snapshot=snapshot,
            changeset=changeset,
            predecessor=previous,
            activity_state=ActivityState.REJECTED,
            activity_metric=previous.activity_metric,
            activity_value=previous.activity_value,
            activity_unit=previous.activity_unit,
            evidence_text=previous.evidence_text,
            is_tombstone=True,
        )
        item.proposed_snapshot = snapshot
        item.proposed_revision_id = revision.id
        item.content_hash = revision.content_hash
        session.flush()
        return revision
