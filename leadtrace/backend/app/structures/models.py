from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.workspaces.models import ChangeActorKind


class StructureStatus(StrEnum):
    DRAFT = "draft"
    REVIEWER_CONFIRMED = "reviewer_confirmed"
    UNRESOLVED = "unresolved"
    NOT_REPORTED = "not_reported"


class StructureInputMethod(StrEnum):
    AI_PREFILL = "ai_prefill"
    MANUAL_SMILES = "manual_smiles"
    STRUCTURE_EDITOR = "structure_editor"


class Structure(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "structures"
    __table_args__ = (
        ForeignKeyConstraint(
            ["compound_id", "paper_id", "workspace_id"],
            ["compounds.id", "compounds.paper_id", "compounds.workspace_id"],
            name="fk_structures_compound_aggregate",
            ondelete="CASCADE",
        ),
        UniqueConstraint("compound_id", name="uq_structures_compound"),
        CheckConstraint(
            "status IN ('draft', 'reviewer_confirmed', 'unresolved', 'not_reported')",
            name="ck_structures_status",
        ),
        CheckConstraint(
            "input_method IN ('ai_prefill', 'manual_smiles', 'structure_editor')",
            name="ck_structures_input_method",
        ),
        CheckConstraint(
            "created_by_kind IN ('reviewer', 'admin', 'ai', 'system')",
            name="ck_structures_creator_kind",
        ),
    )

    paper_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("papers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    compound_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    smiles: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_smiles: Mapped[str | None] = mapped_column(Text, nullable=True)
    molfile: Mapped[str | None] = mapped_column(Text, nullable=True)
    inchi: Mapped[str | None] = mapped_column(Text, nullable=True)
    inchikey: Mapped[str | None] = mapped_column(String(64), nullable=True)
    depiction_asset_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("assets.id", ondelete="RESTRICT"),
        nullable=True,
    )
    status: Mapped[StructureStatus] = mapped_column(
        Enum(
            StructureStatus,
            name="structure_status",
            native_enum=False,
            length=24,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
    )
    input_method: Mapped[StructureInputMethod] = mapped_column(
        Enum(
            StructureInputMethod,
            name="structure_input_method",
            native_enum=False,
            length=24,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
    )
    created_by_kind: Mapped[ChangeActorKind] = mapped_column(
        Enum(
            ChangeActorKind,
            name="science_creator_kind",
            native_enum=False,
            length=16,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
        default=ChangeActorKind.REVIEWER,
    )


__all__ = ["Structure", "StructureInputMethod", "StructureStatus"]
