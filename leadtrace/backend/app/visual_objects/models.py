from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin
from app.revisions.models import ObjectKind, RevisionedObject


class MoleculeObjectType(StrEnum):
    COMPLETE_MOLECULE = "complete_molecule"
    SHARED_SCAFFOLD = "shared_scaffold"
    R_GROUP = "r_group"
    LINKER = "linker"
    VARIABLE_SITE = "variable_site"
    REPLACEMENT_FRAGMENT = "replacement_fragment"
    MULTI_STRUCTURE_REGION = "multi_structure_region"
    REACTION_OR_SCHEME_CONTEXT = "reaction_or_scheme_context"
    MIXED_CHEMICAL_REGION = "mixed_chemical_region"
    NON_STRUCTURE = "non_structure"
    UNCERTAIN = "uncertain"


class VisualRegion(RevisionedObject):
    __tablename__ = "visual_regions"
    __table_args__ = (
        UniqueConstraint(
            "paper_id",
            "region_key",
            name="uq_visual_regions_paper_key",
        ),
        CheckConstraint("page_number > 0", name="ck_visual_regions_positive_page"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("revisioned_objects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    paper_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("papers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    region_key: Mapped[str] = mapped_column(String(255), nullable=False)
    asset_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("assets.id", ondelete="RESTRICT"),
        nullable=True,
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)

    __mapper_args__ = {"polymorphic_identity": ObjectKind.VISUAL_REGION}


class VisualObject(RevisionedObject):
    __tablename__ = "visual_objects"
    __table_args__ = (
        UniqueConstraint(
            "paper_id",
            "object_key",
            name="uq_visual_objects_paper_key",
        ),
        CheckConstraint(
            "object_type IN ("
            "'complete_molecule', 'shared_scaffold', 'r_group', 'linker', "
            "'variable_site', 'replacement_fragment', 'multi_structure_region', "
            "'reaction_or_scheme_context', 'mixed_chemical_region', 'non_structure', "
            "'uncertain'"
            ")",
            name="ck_visual_objects_object_type",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("revisioned_objects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    paper_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("papers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    object_key: Mapped[str] = mapped_column(String(255), nullable=False)
    object_type: Mapped[MoleculeObjectType] = mapped_column(
        String(48), nullable=False, default=MoleculeObjectType.UNCERTAIN
    )

    __mapper_args__ = {"polymorphic_identity": ObjectKind.VISUAL_OBJECT}


class VisualObjectRegionBinding(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "visual_object_region_bindings"
    __table_args__ = (
        UniqueConstraint(
            "visual_object_id",
            "region_id",
            name="uq_visual_object_region_binding",
        ),
        Index("ix_visual_object_region_object", "visual_object_id"),
        Index("ix_visual_object_region_region", "region_id"),
    )

    visual_object_id: Mapped[UUID] = mapped_column(
        ForeignKey("visual_objects.id", ondelete="CASCADE"), nullable=False
    )
    region_id: Mapped[UUID] = mapped_column(
        ForeignKey("visual_regions.id", ondelete="RESTRICT"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(64), nullable=False, default="source")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class VisualObjectAssetBinding(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "visual_object_asset_bindings"
    __table_args__ = (
        UniqueConstraint(
            "visual_object_id",
            "asset_id",
            name="uq_visual_object_asset_binding",
        ),
        Index("ix_visual_object_asset_object", "visual_object_id"),
        Index("ix_visual_object_asset_asset", "asset_id"),
    )

    visual_object_id: Mapped[UUID] = mapped_column(
        ForeignKey("visual_objects.id", ondelete="CASCADE"), nullable=False
    )
    asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(64), nullable=False, default="image")
    is_primary: Mapped[bool] = mapped_column(nullable=False, default=False)


class VisualObjectCompoundBinding(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "visual_object_compound_bindings"
    __table_args__ = (
        UniqueConstraint(
            "visual_object_id",
            "compound_id",
            "label",
            name="uq_visual_object_compound_label",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_visual_object_compound_confidence",
        ),
        Index("ix_visual_object_compound_object", "visual_object_id"),
        Index("ix_visual_object_compound_compound", "compound_id"),
    )

    visual_object_id: Mapped[UUID] = mapped_column(
        ForeignKey("visual_objects.id", ondelete="CASCADE"), nullable=False
    )
    compound_id: Mapped[UUID] = mapped_column(
        ForeignKey("compounds.id", ondelete="RESTRICT"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    label_bbox: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    role: Mapped[str] = mapped_column(String(64), nullable=False, default="label")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_primary: Mapped[bool] = mapped_column(nullable=False, default=False)


class VisualObjectRelation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "visual_object_relations"
    __table_args__ = (
        UniqueConstraint(
            "source_object_id",
            "target_object_id",
            "relation_type",
            name="uq_visual_object_relation",
        ),
        CheckConstraint(
            "source_object_id <> target_object_id",
            name="ck_visual_object_relation_no_self_loop",
        ),
        Index("ix_visual_object_relations_source", "source_object_id"),
        Index("ix_visual_object_relations_target", "target_object_id"),
    )

    source_object_id: Mapped[UUID] = mapped_column(
        ForeignKey("visual_objects.id", ondelete="CASCADE"), nullable=False
    )
    target_object_id: Mapped[UUID] = mapped_column(
        ForeignKey("visual_objects.id", ondelete="CASCADE"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
