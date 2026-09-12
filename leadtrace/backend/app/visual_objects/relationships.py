from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.visual_objects.bindings import BindingConflict, ObjectRelationType, validate_relation_type
from app.visual_objects.models import VisualObject, VisualObjectRelation
from app.visual_objects.objects import check_expected_version
from app.reviews.models import Changeset
from app.security.policies import WorkflowState


class RelationshipService:
    """Store visual semantics without ever creating a lineage edge."""

    def create_relation(
        self,
        session: Session,
        *,
        source_object_id: UUID,
        target_object_id: UUID,
        relation_type: str | ObjectRelationType,
        note: str | None = None,
        changeset_id: UUID | None = None,
        expected_version: int | None = None,
    ) -> VisualObjectRelation:
        source = session.get(VisualObject, source_object_id)
        target = session.get(VisualObject, target_object_id)
        if source is None or target is None or source.paper_id != target.paper_id:
            raise BindingConflict("Visual objects must belong to the same Paper")
        relation = validate_relation_type(relation_type)
        if source_object_id == target_object_id:
            raise BindingConflict("A visual object cannot relate to itself")
        changeset = None
        if changeset_id is not None:
            changeset = session.scalar(
                select(Changeset).where(Changeset.id == changeset_id).with_for_update()
            )
            if changeset is None or changeset.paper_id != source.paper_id or expected_version is None:
                raise BindingConflict("Relation requires the current editable draft changeset")
            check_expected_version(changeset.version, expected_version=expected_version)
            if changeset.workflow_state not in {WorkflowState.DRAFT, WorkflowState.REVISED_DRAFT}:
                raise BindingConflict("Relation requires the current editable draft changeset")
        existing = session.scalar(
            select(VisualObjectRelation).where(
                VisualObjectRelation.source_object_id == source_object_id,
                VisualObjectRelation.target_object_id == target_object_id,
                VisualObjectRelation.relation_type == relation.value,
            )
        )
        if existing is not None:
            raise BindingConflict("Visual object relation already exists")
        record = VisualObjectRelation(
            source_object_id=source_object_id,
            target_object_id=target_object_id,
            relation_type=relation.value,
            note=note,
        )
        session.add(record)
        if changeset is not None:
            changeset.version += 1
        session.flush()
        return record
