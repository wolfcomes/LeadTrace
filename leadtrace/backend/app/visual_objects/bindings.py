from __future__ import annotations

from enum import StrEnum
from typing import Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assets.models import Asset
from app.compounds.models import Compound
from app.reviews.models import Changeset
from app.security.policies import WorkflowState
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
        expected_version: int,
        paper_id: UUID,
    ) -> Changeset:
        changeset = session.scalar(
            select(Changeset).where(Changeset.id == changeset_id).with_for_update()
        )
        if changeset is None or changeset.paper_id != paper_id:
            raise BindingConflict("Binding requires the current editable draft changeset")
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
            expected_version=expected_version,
            paper_id=object_identity.paper_id,
        )
        existing = session.scalar(
            select(VisualObjectRegionBinding).where(
                VisualObjectRegionBinding.visual_object_id == object_id,
                VisualObjectRegionBinding.region_id == region_id,
            )
        )
        if existing is not None:
            raise BindingConflict("Region is already bound to this object")
        binding = VisualObjectRegionBinding(
            visual_object_id=object_id,
            region_id=region_id,
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
            expected_version=expected_version,
            paper_id=object_identity.paper_id,
        )
        existing = session.scalar(
            select(VisualObjectAssetBinding).where(
                VisualObjectAssetBinding.visual_object_id == object_id,
                VisualObjectAssetBinding.asset_id == asset_id,
            )
        )
        if existing is not None:
            raise BindingConflict("Asset is already bound to this object")
        if is_primary:
            session.query(VisualObjectAssetBinding).filter(
                VisualObjectAssetBinding.visual_object_id == object_id
            ).update({VisualObjectAssetBinding.is_primary: False})
        binding = VisualObjectAssetBinding(
            visual_object_id=object_id,
            asset_id=asset_id,
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
            expected_version=expected_version,
            paper_id=object_identity.paper_id,
        )
        existing = session.scalar(
            select(VisualObjectCompoundBinding).where(
                VisualObjectCompoundBinding.visual_object_id == object_id,
                VisualObjectCompoundBinding.compound_id == compound_id,
                VisualObjectCompoundBinding.label == clean_label,
            )
        )
        if existing is not None:
            raise BindingConflict("Compound label is already bound to this object")
        if is_primary:
            session.query(VisualObjectCompoundBinding).filter(
                VisualObjectCompoundBinding.visual_object_id == object_id
            ).update({VisualObjectCompoundBinding.is_primary: False})
        binding = VisualObjectCompoundBinding(
            visual_object_id=object_id,
            compound_id=compound_id,
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
