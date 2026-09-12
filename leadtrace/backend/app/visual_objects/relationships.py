from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.visual_objects.bindings import (
    BindingConflict,
    BindingService,
    ObjectRelationType,
    _frozen_binding_source,
    _optional_text,
    _uuid_value,
    validate_relation_type,
)
from app.visual_objects.models import VisualObject, VisualObjectRelation
from app.releases.manifest import frozen_base_binding_by_key


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
        actor_id: UUID | None = None,
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
            if expected_version is None or actor_id is None:
                raise BindingConflict("Relation requires the current editable draft changeset")
            changeset = BindingService._editable_changeset(
                session,
                changeset_id=changeset_id,
                actor_id=actor_id,
                expected_version=expected_version,
                paper_id=source.paper_id,
            )
        existing = session.scalar(
            select(VisualObjectRelation).where(
                VisualObjectRelation.source_object_id == source_object_id,
                VisualObjectRelation.target_object_id == target_object_id,
                VisualObjectRelation.relation_type == relation.value,
                VisualObjectRelation.changeset_id == (
                    changeset.id if changeset is not None else None
                ),
            )
        )
        if existing is not None:
            raise BindingConflict("Visual object relation already exists")
        logical_key = ":".join(
            ("relation", str(source_object_id), str(target_object_id), relation.value)
        )
        if (
            changeset is not None
            and frozen_base_binding_by_key(
                session,
                changeset,
                "visual_object_relations",
                logical_key,
            )
            is not None
        ):
            raise BindingConflict(
                "Visual object relation already exists in the frozen base release"
            )
        record = VisualObjectRelation(
            source_object_id=source_object_id,
            target_object_id=target_object_id,
            changeset_id=changeset.id if changeset is not None else None,
            operation="add",
            logical_key=logical_key,
            relation_type=relation.value,
            note=note,
        )
        session.add(record)
        if changeset is not None:
            changeset.version += 1
        session.flush()
        return record

    def update_relation(
        self,
        session: Session,
        *,
        relation_id: UUID,
        changeset_id: UUID,
        actor_id: UUID,
        expected_version: int,
        note: str | None,
    ) -> VisualObjectRelation:
        source = session.get(VisualObjectRelation, relation_id)
        if source is None:
            raise BindingConflict("Visual object relation not found")
        object_identity = session.get(VisualObject, source.source_object_id)
        if object_identity is None:
            raise BindingConflict("Molecule object not found")
        changeset = BindingService._editable_changeset(
            session,
            changeset_id=changeset_id,
            actor_id=actor_id,
            expected_version=expected_version,
            paper_id=object_identity.paper_id,
        )
        if source.changeset_id == changeset.id:
            proposal = source
            if proposal.operation == "remove":
                raise BindingConflict("Visual object relation is already removed")
            proposal.note = note
        else:
            frozen, logical_key, base_hash = _frozen_binding_source(
                session,
                changeset,
                "visual_object_relations",
                source.id,
            )
            proposal = VisualObjectRelation(
                source_object_id=_uuid_value(frozen, "source_object_id"),
                target_object_id=_uuid_value(frozen, "target_object_id"),
                changeset_id=changeset.id,
                operation="update",
                logical_key=logical_key,
                base_hash=base_hash,
                relation_type=str(frozen.get("relation_type") or ""),
                note=note,
            )
            session.add(proposal)
        changeset.version += 1
        session.flush()
        return proposal

    def remove_relation(
        self,
        session: Session,
        *,
        relation_id: UUID,
        changeset_id: UUID,
        actor_id: UUID,
        expected_version: int,
    ) -> VisualObjectRelation:
        source = session.get(VisualObjectRelation, relation_id)
        if source is None:
            raise BindingConflict("Visual object relation not found")
        object_identity = session.get(VisualObject, source.source_object_id)
        if object_identity is None:
            raise BindingConflict("Molecule object not found")
        changeset = BindingService._editable_changeset(
            session,
            changeset_id=changeset_id,
            actor_id=actor_id,
            expected_version=expected_version,
            paper_id=object_identity.paper_id,
        )
        if source.changeset_id == changeset.id:
            proposal = source
            if proposal.operation == "add":
                proposal.operation = "cancelled"
                session.delete(proposal)
            elif proposal.operation == "update":
                proposal.operation = "remove"
            else:
                raise BindingConflict("Visual object relation is already removed")
        else:
            frozen, logical_key, base_hash = _frozen_binding_source(
                session,
                changeset,
                "visual_object_relations",
                source.id,
            )
            proposal = VisualObjectRelation(
                source_object_id=_uuid_value(frozen, "source_object_id"),
                target_object_id=_uuid_value(frozen, "target_object_id"),
                changeset_id=changeset.id,
                operation="remove",
                logical_key=logical_key,
                base_hash=base_hash,
                relation_type=str(frozen.get("relation_type") or ""),
                note=_optional_text(frozen.get("note")),
            )
            session.add(proposal)
        changeset.version += 1
        session.flush()
        return proposal
