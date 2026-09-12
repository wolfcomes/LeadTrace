from __future__ import annotations

from enum import StrEnum
from typing import Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assets.models import Asset
from app.compounds.models import Compound
from app.releases.manifest import (
    binding_base_hash,
    binding_logical_key,
    frozen_base_binding,
    frozen_base_binding_by_key,
)
from app.reviews.models import Changeset
from app.security.policies import WorkflowState
from app.users.models import User, UserRole
from app.visual_objects.models import (
    VisualObject,
    VisualObjectAssetBinding,
    VisualObjectCompoundBinding,
    VisualObjectRegionBinding,
)
from app.visual_objects.objects import check_expected_version
from app.visual_objects.models import VisualRegion


class BindingConflict(ValueError):
    """Raised when a binding is invalid or already exists."""


def _logical_key(*parts: object) -> str:
    return ":".join(str(part) for part in parts)


def _frozen_binding_source(
    session: Session,
    changeset: Changeset,
    collection: str,
    binding_id: UUID,
) -> tuple[dict[str, object], str, str]:
    try:
        frozen = frozen_base_binding(session, changeset, collection, binding_id)
    except ValueError as error:
        raise BindingConflict(
            "Binding source is not present in the changeset frozen base release"
        ) from error
    return (
        frozen,
        binding_logical_key(collection, frozen),
        binding_base_hash(frozen),
    )


def _uuid_value(row: Mapping[str, object], field: str) -> UUID:
    try:
        return UUID(str(row[field]))
    except (KeyError, TypeError, ValueError) as error:
        raise BindingConflict(f"Frozen binding has an invalid {field}") from error


def _optional_text(value: object) -> str | None:
    return str(value) if value is not None else None


class ObjectRelationType(StrEnum):
    CONTAINS = "contains"
    ADJACENT_TO = "adjacent_to"
    SHARES_SCAFFOLD_WITH = "shares_scaffold_with"
    SUBSTITUENT_OF = "substituent_of"
    LINKER_OF = "linker_of"
    VARIABLE_SITE_OF = "variable_site_of"
    ALTERNATE_VIEW_OF = "alternate_view_of"
    CONFLICTS_WITH = "conflicts_with"


def validate_relation_type(value: str | ObjectRelationType) -> ObjectRelationType:
    try:
        relation = value if isinstance(value, ObjectRelationType) else ObjectRelationType(value.strip())
    except (AttributeError, ValueError) as error:
        raise BindingConflict("Lineage edges are not visual object relations") from error
    return relation


def _clean_label(label: str) -> str:
    value = label.strip()
    if not value:
        raise BindingConflict("Compound label is required")
    return value


def _validate_bbox(bbox: Mapping[str, object] | None) -> dict[str, object] | None:
    if bbox is None:
        return None
    required = ("x0", "y0", "x1", "y1")
    if any(key not in bbox for key in required):
        raise BindingConflict("Label bbox requires x0, y0, x1, and y1")
    values = tuple(float(bbox[key]) for key in required)
    if any(value < 0 or value > 1 for value in values) or values[0] >= values[2] or values[1] >= values[3]:
        raise BindingConflict("Label bbox must be a positive normalized rectangle")
    return {key: float(bbox[key]) for key in required}


class BindingService:
    """Maintain explicit many-to-many image, region, and compound bindings."""

    @staticmethod
    def _editable_changeset(
        session: Session,
        *,
        changeset_id: UUID,
        actor_id: UUID,
        expected_version: int,
        paper_id: UUID,
    ) -> Changeset:
        changeset = session.scalar(
            select(Changeset).where(Changeset.id == changeset_id).with_for_update()
        )
        if changeset is None or changeset.paper_id != paper_id:
            raise BindingConflict("Binding requires the current editable draft changeset")
        actor = session.get(User, actor_id)
        if (
            actor is None
            or not actor.is_enabled
            or (actor.role is not UserRole.ADMIN and changeset.owner_id != actor_id)
        ):
            raise BindingConflict("Changeset not found")
        check_expected_version(changeset.version, expected_version=expected_version)
        if changeset.workflow_state not in {WorkflowState.DRAFT, WorkflowState.REVISED_DRAFT}:
            raise BindingConflict("Binding requires the current editable draft changeset")
        return changeset

    @staticmethod
    def _object(session: Session, object_id: UUID) -> VisualObject:
        object_identity = session.scalar(select(VisualObject).where(VisualObject.id == object_id))
        if object_identity is None:
            raise BindingConflict("Molecule object not found")
        return object_identity

    def bind_region(
        self,
        session: Session,
        *,
        object_id: UUID,
        region_id: UUID,
        changeset_id: UUID,
        actor_id: UUID,
        expected_version: int,
        role: str = "source",
        note: str | None = None,
    ) -> VisualObjectRegionBinding:
        object_identity = self._object(session, object_id)
        region = session.get(VisualRegion, region_id)
        if region is None or region.paper_id != object_identity.paper_id:
            raise BindingConflict("Region does not belong to this Paper")
        changeset = self._editable_changeset(
            session,
            changeset_id=changeset_id,
            actor_id=actor_id,
            expected_version=expected_version,
            paper_id=object_identity.paper_id,
        )
        existing = session.scalar(
            select(VisualObjectRegionBinding).where(
                VisualObjectRegionBinding.visual_object_id == object_id,
                VisualObjectRegionBinding.region_id == region_id,
                VisualObjectRegionBinding.changeset_id == changeset.id,
            )
        )
        if existing is not None:
            raise BindingConflict("Region is already bound to this object")
        logical_key = _logical_key("region", object_id, region_id)
        if frozen_base_binding_by_key(
            session,
            changeset,
            "visual_object_regions",
            logical_key,
        ) is not None:
            raise BindingConflict("Region binding already exists in the frozen base release")
        binding = VisualObjectRegionBinding(
            visual_object_id=object_id,
            region_id=region_id,
            changeset_id=changeset.id,
            operation="add",
            logical_key=logical_key,
            role=role.strip() or "source",
            note=note,
        )
        session.add(binding)
        changeset.version += 1
        session.flush()
        return binding

    def bind_asset(
        self,
        session: Session,
        *,
        object_id: UUID,
        asset_id: UUID,
        changeset_id: UUID,
        actor_id: UUID,
        expected_version: int,
        role: str = "image",
        is_primary: bool = False,
    ) -> VisualObjectAssetBinding:
        object_identity = self._object(session, object_id)
        if session.get(Asset, asset_id) is None:
            raise BindingConflict("Asset not found")
        changeset = self._editable_changeset(
            session,
            changeset_id=changeset_id,
            actor_id=actor_id,
            expected_version=expected_version,
            paper_id=object_identity.paper_id,
        )
        existing = session.scalar(
            select(VisualObjectAssetBinding).where(
                VisualObjectAssetBinding.visual_object_id == object_id,
                VisualObjectAssetBinding.asset_id == asset_id,
                VisualObjectAssetBinding.changeset_id == changeset.id,
            )
        )
        if existing is not None:
            raise BindingConflict("Asset is already bound to this object")
        logical_key = _logical_key("asset", object_id, asset_id)
        if frozen_base_binding_by_key(
            session,
            changeset,
            "visual_object_assets",
            logical_key,
        ) is not None:
            raise BindingConflict("Asset binding already exists in the frozen base release")
        if is_primary:
            session.query(VisualObjectAssetBinding).filter(
                VisualObjectAssetBinding.visual_object_id == object_id,
                VisualObjectAssetBinding.changeset_id == changeset.id,
            ).update({VisualObjectAssetBinding.is_primary: False})
        binding = VisualObjectAssetBinding(
            visual_object_id=object_id,
            asset_id=asset_id,
            changeset_id=changeset.id,
            operation="add",
            logical_key=logical_key,
            role=role.strip() or "image",
            is_primary=is_primary,
        )
        session.add(binding)
        changeset.version += 1
        session.flush()
        return binding

    def bind_compound(
        self,
        session: Session,
        *,
        object_id: UUID,
        compound_id: UUID,
        label: str,
        changeset_id: UUID,
        actor_id: UUID,
        expected_version: int,
        label_bbox: Mapping[str, object] | None = None,
        role: str = "label",
        confidence: float | None = None,
        note: str | None = None,
        is_primary: bool = False,
    ) -> VisualObjectCompoundBinding:
        object_identity = self._object(session, object_id)
        compound = session.get(Compound, compound_id)
        if compound is None or compound.paper_id != object_identity.paper_id:
            raise BindingConflict("Compound does not belong to this Paper")
        if confidence is not None and not 0 <= confidence <= 1:
            raise BindingConflict("confidence must be between 0 and 1")
        clean_label = _clean_label(label)
        changeset = self._editable_changeset(
            session,
            changeset_id=changeset_id,
            actor_id=actor_id,
            expected_version=expected_version,
            paper_id=object_identity.paper_id,
        )
        existing = session.scalar(
            select(VisualObjectCompoundBinding).where(
                VisualObjectCompoundBinding.visual_object_id == object_id,
                VisualObjectCompoundBinding.compound_id == compound_id,
                VisualObjectCompoundBinding.label == clean_label,
                VisualObjectCompoundBinding.changeset_id == changeset.id,
            )
        )
        if existing is not None:
            raise BindingConflict("Compound label is already bound to this object")
        logical_key = _logical_key("compound", object_id, compound_id, clean_label)
        if frozen_base_binding_by_key(
            session,
            changeset,
            "visual_object_compounds",
            logical_key,
        ) is not None:
            raise BindingConflict("Compound binding already exists in the frozen base release")
        if is_primary:
            session.query(VisualObjectCompoundBinding).filter(
                VisualObjectCompoundBinding.visual_object_id == object_id,
                VisualObjectCompoundBinding.changeset_id == changeset.id,
            ).update({VisualObjectCompoundBinding.is_primary: False})
        binding = VisualObjectCompoundBinding(
            visual_object_id=object_id,
            compound_id=compound_id,
            changeset_id=changeset.id,
            operation="add",
            logical_key=logical_key,
            label=clean_label,
            label_bbox=_validate_bbox(label_bbox),
            role=role.strip() or "label",
            confidence=confidence,
            note=note,
            is_primary=is_primary,
        )
        session.add(binding)
        changeset.version += 1
        session.flush()
        return binding

    def update_region(
        self,
        session: Session,
        *,
        binding_id: UUID,
        changeset_id: UUID,
        actor_id: UUID,
        expected_version: int,
        role: str,
        note: str | None,
    ) -> VisualObjectRegionBinding:
        source = session.get(VisualObjectRegionBinding, binding_id)
        if source is None:
            raise BindingConflict("Region binding not found")
        object_identity = self._object(session, source.visual_object_id)
        changeset = self._editable_changeset(
            session,
            changeset_id=changeset_id,
            actor_id=actor_id,
            expected_version=expected_version,
            paper_id=object_identity.paper_id,
        )
        if source.changeset_id == changeset.id:
            if source.operation == "remove":
                raise BindingConflict("Region binding is already removed")
            source.role = role.strip() or "source"
            source.note = note
            changeset.version += 1
            session.flush()
            return source
        frozen, logical_key, base_hash = _frozen_binding_source(
            session,
            changeset,
            "visual_object_regions",
            source.id,
        )
        proposal = VisualObjectRegionBinding(
            visual_object_id=_uuid_value(frozen, "visual_object_id"),
            region_id=_uuid_value(frozen, "region_id"),
            changeset_id=changeset.id,
            operation="update",
            logical_key=logical_key,
            base_hash=base_hash,
            role=role.strip() or "source",
            note=note,
        )
        session.add(proposal)
        changeset.version += 1
        session.flush()
        return proposal

    def remove_region(
        self,
        session: Session,
        *,
        binding_id: UUID,
        changeset_id: UUID,
        actor_id: UUID,
        expected_version: int,
    ) -> VisualObjectRegionBinding:
        source = session.get(VisualObjectRegionBinding, binding_id)
        if source is None:
            raise BindingConflict("Region binding not found")
        object_identity = self._object(session, source.visual_object_id)
        changeset = self._editable_changeset(
            session,
            changeset_id=changeset_id,
            actor_id=actor_id,
            expected_version=expected_version,
            paper_id=object_identity.paper_id,
        )
        if source.changeset_id == changeset.id:
            if source.operation == "add":
                source.operation = "cancelled"
                session.delete(source)
            elif source.operation == "update":
                source.operation = "remove"
            else:
                raise BindingConflict("Region binding is already removed")
            changeset.version += 1
            session.flush()
            return source
        frozen, logical_key, base_hash = _frozen_binding_source(
            session,
            changeset,
            "visual_object_regions",
            source.id,
        )
        proposal = VisualObjectRegionBinding(
            visual_object_id=_uuid_value(frozen, "visual_object_id"),
            region_id=_uuid_value(frozen, "region_id"),
            changeset_id=changeset.id,
            operation="remove",
            logical_key=logical_key,
            base_hash=base_hash,
            role=str(frozen.get("role") or "source"),
            note=_optional_text(frozen.get("note")),
        )
        session.add(proposal)
        changeset.version += 1
        session.flush()
        return proposal

    def update_asset(
        self,
        session: Session,
        *,
        binding_id: UUID,
        changeset_id: UUID,
        actor_id: UUID,
        expected_version: int,
        role: str,
        is_primary: bool,
    ) -> VisualObjectAssetBinding:
        source = session.get(VisualObjectAssetBinding, binding_id)
        if source is None:
            raise BindingConflict("Asset binding not found")
        object_identity = self._object(session, source.visual_object_id)
        changeset = self._editable_changeset(
            session,
            changeset_id=changeset_id,
            actor_id=actor_id,
            expected_version=expected_version,
            paper_id=object_identity.paper_id,
        )
        if source.changeset_id == changeset.id:
            proposal = source
            if proposal.operation == "remove":
                raise BindingConflict("Asset binding is already removed")
            proposal.role = role.strip() or "image"
            proposal.is_primary = is_primary
        else:
            frozen, logical_key, base_hash = _frozen_binding_source(
                session,
                changeset,
                "visual_object_assets",
                source.id,
            )
            proposal = VisualObjectAssetBinding(
                visual_object_id=_uuid_value(frozen, "visual_object_id"),
                asset_id=_uuid_value(frozen, "asset_id"),
                changeset_id=changeset.id,
                operation="update",
                logical_key=logical_key,
                base_hash=base_hash,
                role=role.strip() or "image",
                is_primary=is_primary,
            )
            session.add(proposal)
        if is_primary:
            session.query(VisualObjectAssetBinding).filter(
                VisualObjectAssetBinding.visual_object_id == source.visual_object_id,
                VisualObjectAssetBinding.changeset_id == changeset.id,
                VisualObjectAssetBinding.id != proposal.id,
            ).update({VisualObjectAssetBinding.is_primary: False})
        changeset.version += 1
        session.flush()
        return proposal

    def remove_asset(
        self,
        session: Session,
        *,
        binding_id: UUID,
        changeset_id: UUID,
        actor_id: UUID,
        expected_version: int,
    ) -> VisualObjectAssetBinding:
        source = session.get(VisualObjectAssetBinding, binding_id)
        if source is None:
            raise BindingConflict("Asset binding not found")
        object_identity = self._object(session, source.visual_object_id)
        changeset = self._editable_changeset(
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
                raise BindingConflict("Asset binding is already removed")
        else:
            frozen, logical_key, base_hash = _frozen_binding_source(
                session,
                changeset,
                "visual_object_assets",
                source.id,
            )
            proposal = VisualObjectAssetBinding(
                visual_object_id=_uuid_value(frozen, "visual_object_id"),
                asset_id=_uuid_value(frozen, "asset_id"),
                changeset_id=changeset.id,
                operation="remove",
                logical_key=logical_key,
                base_hash=base_hash,
                role=str(frozen.get("role") or "image"),
                is_primary=bool(frozen.get("is_primary")),
            )
            session.add(proposal)
        changeset.version += 1
        session.flush()
        return proposal

    def update_compound(
        self,
        session: Session,
        *,
        binding_id: UUID,
        changeset_id: UUID,
        actor_id: UUID,
        expected_version: int,
        label: str,
        role: str,
        confidence: float | None,
        note: str | None,
        is_primary: bool,
        label_bbox: Mapping[str, object] | None,
    ) -> VisualObjectCompoundBinding:
        source = session.get(VisualObjectCompoundBinding, binding_id)
        if source is None:
            raise BindingConflict("Compound binding not found")
        clean_label = _clean_label(label)
        if confidence is not None and not 0 <= confidence <= 1:
            raise BindingConflict("confidence must be between 0 and 1")
        object_identity = self._object(session, source.visual_object_id)
        changeset = self._editable_changeset(
            session,
            changeset_id=changeset_id,
            actor_id=actor_id,
            expected_version=expected_version,
            paper_id=object_identity.paper_id,
        )
        if source.changeset_id == changeset.id:
            proposal = source
            if proposal.operation == "remove":
                raise BindingConflict("Compound binding is already removed")
            proposal.label = clean_label
            if proposal.operation == "add":
                proposal.logical_key = _logical_key(
                    "compound",
                    proposal.visual_object_id,
                    proposal.compound_id,
                    clean_label,
                )
            proposal.role = role.strip() or "label"
            proposal.confidence = confidence
            proposal.note = note
            proposal.label_bbox = _validate_bbox(label_bbox)
            proposal.is_primary = is_primary
        else:
            frozen, logical_key, base_hash = _frozen_binding_source(
                session,
                changeset,
                "visual_object_compounds",
                source.id,
            )
            if clean_label != str(frozen.get("label") or ""):
                raise BindingConflict(
                    "Compound binding label is part of its identity; "
                    "remove and add the binding to change it"
                )
            proposal = VisualObjectCompoundBinding(
                visual_object_id=_uuid_value(frozen, "visual_object_id"),
                compound_id=_uuid_value(frozen, "compound_id"),
                changeset_id=changeset.id,
                operation="update",
                logical_key=logical_key,
                base_hash=base_hash,
                label=clean_label,
                label_bbox=_validate_bbox(label_bbox),
                role=role.strip() or "label",
                confidence=confidence,
                note=note,
                is_primary=is_primary,
            )
            session.add(proposal)
        if is_primary:
            session.query(VisualObjectCompoundBinding).filter(
                VisualObjectCompoundBinding.visual_object_id == source.visual_object_id,
                VisualObjectCompoundBinding.changeset_id == changeset.id,
                VisualObjectCompoundBinding.id != proposal.id,
            ).update({VisualObjectCompoundBinding.is_primary: False})
        changeset.version += 1
        session.flush()
        return proposal

    def remove_compound(
        self,
        session: Session,
        *,
        binding_id: UUID,
        changeset_id: UUID,
        actor_id: UUID,
        expected_version: int,
    ) -> VisualObjectCompoundBinding:
        source = session.get(VisualObjectCompoundBinding, binding_id)
        if source is None:
            raise BindingConflict("Compound binding not found")
        object_identity = self._object(session, source.visual_object_id)
        changeset = self._editable_changeset(
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
                raise BindingConflict("Compound binding is already removed")
        else:
            frozen, logical_key, base_hash = _frozen_binding_source(
                session,
                changeset,
                "visual_object_compounds",
                source.id,
            )
            proposal = VisualObjectCompoundBinding(
                visual_object_id=_uuid_value(frozen, "visual_object_id"),
                compound_id=_uuid_value(frozen, "compound_id"),
                changeset_id=changeset.id,
                operation="remove",
                logical_key=logical_key,
                base_hash=base_hash,
                label=str(frozen.get("label") or ""),
                label_bbox=frozen.get("label_bbox"),
                role=str(frozen.get("role") or "label"),
                confidence=frozen.get("confidence"),
                note=_optional_text(frozen.get("note")),
                is_primary=bool(frozen.get("is_primary")),
            )
            session.add(proposal)
        changeset.version += 1
        session.flush()
        return proposal
