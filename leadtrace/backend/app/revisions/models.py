from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin
from app.security.policies import WorkflowState


class ObjectKind(StrEnum):
    PAPER = "paper"
    COMPOUND = "compound"
    STRUCTURE = "structure"
    EVIDENCE = "evidence"
    ACTIVITY = "activity"
    LINEAGE = "lineage"
    LINEAGE_EDGE = "lineage_edge"
    VISUAL_REGION = "visual_region"
    VISUAL_OBJECT = "visual_object"


class StructureState(StrEnum):
    PROPOSAL = "proposal"
    PARSEABLE_CANDIDATE = "parseable_candidate"
    SOURCE_BOUND_CANDIDATE = "source_bound_candidate"
    STRUCTURE_CONFIRMED = "structure_confirmed"
    CONSTITUTION_CONFIRMED = "constitution_confirmed"
    NON_UNIQUE_STEREOCHEMISTRY = "non_unique_stereochemistry"
    MULTICOMPONENT_UNRESOLVED = "multicomponent_unresolved"
    SOURCE_STRUCTURE_MISMATCH = "source_structure_mismatch"
    REJECTED = "rejected"


class EvidenceState(StrEnum):
    PROPOSAL = "proposal"
    SOURCE_BOUND = "source_bound"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class ActivityState(StrEnum):
    PROPOSAL = "proposal"
    SOURCE_BOUND = "source_bound"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class RevisionedObject(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "revisioned_objects"

    object_kind: Mapped[ObjectKind] = mapped_column(
        Enum(
            ObjectKind,
            name="revisioned_object_kind",
            native_enum=False,
            length=24,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __mapper_args__ = {
        "polymorphic_on": object_kind,
        "polymorphic_identity": "revisioned_object",
    }


class ObjectRevision(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "object_revisions"
    __table_args__ = (
        UniqueConstraint(
            "object_id",
            "revision_number",
            name="uq_object_revision_number",
        ),
        CheckConstraint(
            "revision_number > 0",
            name="ck_object_revisions_positive_number",
        ),
        CheckConstraint(
            "char_length(content_hash) = 64",
            name="ck_object_revisions_content_hash_length",
        ),
        CheckConstraint(
            "NOT is_current_published OR workflow_state = 'published'",
            name="ck_object_revisions_current_is_published",
        ),
        CheckConstraint(
            """
            (region_x0 IS NULL AND region_y0 IS NULL AND region_x1 IS NULL
             AND region_y1 IS NULL)
            OR
            (region_x0 >= 0 AND region_y0 >= 0
             AND region_x1 <= 1 AND region_y1 <= 1
             AND region_x0 < region_x1 AND region_y0 < region_y1)
            """,
            name="ck_object_revisions_normalized_region",
        ),
        CheckConstraint(
            "region_rotation IS NULL OR region_rotation IN (0, 90, 180, 270)",
            name="ck_object_revisions_region_rotation",
        ),
        Index("ix_object_revisions_object", "object_id", "revision_number"),
        Index(
            "uq_object_revisions_current_published",
            "object_id",
            unique=True,
            postgresql_where=text("is_current_published"),
        ),
    )

    object_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("revisioned_objects.id", ondelete="RESTRICT"),
        nullable=False,
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    predecessor_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("object_revisions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    changeset_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=True,
    )
    actor_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    search_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    workflow_state: Mapped[WorkflowState] = mapped_column(
        Enum(
            WorkflowState,
            name="object_revision_workflow_state",
            native_enum=False,
            length=24,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
    )
    is_current_published: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    is_tombstone: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    structure_state: Mapped[StructureState | None] = mapped_column(
        Enum(
            StructureState,
            name="structure_state",
            native_enum=False,
            length=32,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=True,
    )
    evidence_state: Mapped[EvidenceState | None] = mapped_column(
        Enum(
            EvidenceState,
            name="evidence_state",
            native_enum=False,
            length=24,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=True,
    )
    activity_state: Mapped[ActivityState | None] = mapped_column(
        Enum(
            ActivityState,
            name="activity_state",
            native_enum=False,
            length=24,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=True,
    )
    canonical_smiles: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    activity_metric: Mapped[str | None] = mapped_column(String(120), nullable=True)
    activity_value: Mapped[str | None] = mapped_column(String(160), nullable=True)
    activity_unit: Mapped[str | None] = mapped_column(String(80), nullable=True)
    relation_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    relation_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    region_x0: Mapped[float | None] = mapped_column(Float, nullable=True)
    region_y0: Mapped[float | None] = mapped_column(Float, nullable=True)
    region_x1: Mapped[float | None] = mapped_column(Float, nullable=True)
    region_y1: Mapped[float | None] = mapped_column(Float, nullable=True)
    region_rotation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
