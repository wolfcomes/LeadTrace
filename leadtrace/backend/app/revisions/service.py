from __future__ import annotations

import hashlib
import json
from uuid import UUID

from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.revisions.models import (
    ActivityState,
    EvidenceState,
    ObjectRevision,
    RevisionedObject,
    StructureState,
)
from app.security.policies import WorkflowState


def canonical_snapshot_hash(snapshot: dict[str, object]) -> str:
    payload = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class RevisionService:
    def create_revision(
        self,
        session: Session,
        *,
        object_identity: RevisionedObject,
        actor_id: UUID,
        reason: str,
        snapshot: dict[str, object],
        predecessor: ObjectRevision | None = None,
        changeset_id: UUID | None = None,
        search_text: str | None = None,
        workflow_state: WorkflowState = WorkflowState.DRAFT,
        is_current_published: bool = False,
        is_tombstone: bool = False,
        structure_state: StructureState | None = None,
        evidence_state: EvidenceState | None = None,
        activity_state: ActivityState | None = None,
        canonical_smiles: str | None = None,
        evidence_text: str | None = None,
        activity_metric: str | None = None,
        activity_value: str | None = None,
        activity_unit: str | None = None,
        relation_type: str | None = None,
        relation_status: str | None = None,
        region_bounds: tuple[float, float, float, float] | None = None,
        region_rotation: int | None = None,
    ) -> ObjectRevision:
        clean_reason = reason.strip()
        if not clean_reason:
            raise ValueError("A revision reason is required")
        if is_current_published and workflow_state is not WorkflowState.PUBLISHED:
            raise ValueError("Only a published revision can be current")
        if predecessor is not None and predecessor.object_id != object_identity.id:
            raise ValueError("Revision predecessor belongs to another object")
        content_hash = canonical_snapshot_hash(snapshot)
        if changeset_id is not None:
            from app.reviews.models import Changeset, ChangesetItem
            from app.reviews.state_machine import content_mutable

            if workflow_state not in {
                WorkflowState.DRAFT,
                WorkflowState.REVISED_DRAFT,
            } or is_current_published:
                raise ValueError(
                    "A changeset-linked revision cannot be published before approval"
                )

            changeset = session.scalar(
                select(Changeset)
                .where(Changeset.id == changeset_id)
                .with_for_update()
            )
            if changeset is None or not content_mutable(changeset.workflow_state):
                raise ValueError("Revision must belong to an editable draft changeset")

            changeset_item = session.scalar(
                select(ChangesetItem.id)
                .where(
                    ChangesetItem.changeset_id == changeset_id,
                    ChangesetItem.object_id == object_identity.id,
                )
                .limit(1)
            )
            if changeset_item is None:
                raise ValueError(
                    "Revision changeset must contain the same revisioned object"
                )
            content_hash = str(
                session.scalar(
                    select(func.leadtrace_jsonb_sha256(cast(snapshot, JSONB)))
                )
            )

        session.execute(
            select(RevisionedObject.id)
            .where(RevisionedObject.id == object_identity.id)
            .with_for_update()
        )
        current_number = session.scalar(
            select(func.max(ObjectRevision.revision_number)).where(
                ObjectRevision.object_id == object_identity.id
            )
        )
        if is_current_published:
            prior_current = session.scalar(
                select(ObjectRevision)
                .where(
                    ObjectRevision.object_id == object_identity.id,
                    ObjectRevision.is_current_published.is_(True),
                )
                .with_for_update()
            )
            if prior_current is not None:
                prior_current.workflow_state = WorkflowState.SUPERSEDED
                prior_current.is_current_published = False
                session.flush()

        x0 = y0 = x1 = y1 = None
        if region_bounds is not None:
            x0, y0, x1, y1 = region_bounds
        revision = ObjectRevision(
            object_id=object_identity.id,
            revision_number=int(current_number or 0) + 1,
            predecessor_id=predecessor.id if predecessor is not None else None,
            changeset_id=changeset_id,
            actor_id=actor_id,
            reason=clean_reason,
            content_hash=content_hash,
            search_text=search_text,
            snapshot=snapshot,
            workflow_state=workflow_state,
            is_current_published=is_current_published,
            is_tombstone=is_tombstone,
            structure_state=structure_state,
            evidence_state=evidence_state,
            activity_state=activity_state,
            canonical_smiles=canonical_smiles,
            evidence_text=evidence_text,
            activity_metric=activity_metric,
            activity_value=activity_value,
            activity_unit=activity_unit,
            relation_type=relation_type,
            relation_status=relation_status,
            region_x0=x0,
            region_y0=y0,
            region_x1=x1,
            region_y1=y1,
            region_rotation=region_rotation,
        )
        session.add(revision)
        session.flush()
        return revision
