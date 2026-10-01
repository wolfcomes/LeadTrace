from __future__ import annotations

from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.workspaces.models import ChangeActorKind


class Compound(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "compounds"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "paper_id"],
            ["paper_workspaces.id", "paper_workspaces.paper_id"],
            name="fk_compounds_workspace_paper",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "id",
            "paper_id",
            "workspace_id",
            name="uq_compounds_id_paper_workspace",
        ),
        UniqueConstraint(
            "workspace_id",
            "compound_label",
            name="uq_compounds_workspace_label",
        ),
        CheckConstraint(
            "btrim(compound_label) <> ''",
            name="ck_compounds_label_required",
        ),
        CheckConstraint("sort_order >= 0", name="ck_compounds_nonnegative_order"),
        CheckConstraint(
            "created_by_kind IN ('reviewer', 'admin', 'ai', 'system')",
            name="ck_compounds_creator_kind",
        ),
        Index("ix_compounds_workspace_order", "workspace_id", "sort_order", "id"),
    )

    paper_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("papers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    compound_label: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by_kind: Mapped[ChangeActorKind] = mapped_column(
        Enum(
            ChangeActorKind,
            name="science_creator_kind",
            native_enum=False,
            length=16,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
    )


__all__ = ["Compound", "CompoundHighlight"]


class CompoundHighlight(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "compound_highlights"
    __table_args__ = (
        ForeignKeyConstraint(["compound_id", "paper_id", "workspace_id"],
            ["compounds.id", "compounds.paper_id", "compounds.workspace_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["evidence_id", "paper_id", "workspace_id"],
            ["evidence.id", "evidence.paper_id", "evidence.workspace_id"], ondelete="RESTRICT"),
        UniqueConstraint("workspace_id", "compound_id", "role", "scope", name="uq_compound_highlights_identity"),
        CheckConstraint("role IN ('study_start', 'paper_selected')", name="ck_highlight_role"),
        CheckConstraint("review_status IN ('draft', 'reviewer_confirmed', 'unresolved')", name="ck_highlight_review"),
        CheckConstraint("btrim(scope) <> '' AND btrim(rationale) <> ''", name="ck_highlight_required"),
        CheckConstraint("created_by_kind IN ('reviewer','admin','ai','system')", name="ck_highlight_creator"),
        Index("ix_compound_highlights_workspace", "workspace_id"),
    )
    paper_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    compound_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    evidence_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    scope: Mapped[str] = mapped_column(String(512), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    review_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    created_by_kind: Mapped[str] = mapped_column(String(16), nullable=False)
