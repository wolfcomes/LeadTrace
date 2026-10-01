from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.workspaces.models import ChangeActorKind


class ActivityOperator(StrEnum):
    EQUAL = "="
    LESS_THAN = "<"
    LESS_THAN_OR_EQUAL = "<="
    GREATER_THAN = ">"
    GREATER_THAN_OR_EQUAL = ">="
    APPROXIMATELY = "~"


class Activity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "activities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["compound_id", "paper_id", "workspace_id"],
            ["compounds.id", "compounds.paper_id", "compounds.workspace_id"],
            name="fk_activities_compound_aggregate",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["evidence_id", "paper_id", "workspace_id"],
            ["evidence.id", "evidence.paper_id", "evidence.workspace_id"],
            name="fk_activities_evidence_aggregate",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "btrim(assay_name) <> ''", name="ck_activities_assay_name_required"
        ),
        CheckConstraint(
            "btrim(metric) <> ''", name="ck_activities_metric_required"
        ),
        CheckConstraint(
            "operator IN ('=', '<', '<=', '>', '>=', '~')",
            name="ck_activities_operator",
        ),
        CheckConstraint("sort_order >= 0", name="ck_activities_nonnegative_order"),
        CheckConstraint(
            "created_by_kind IN ('reviewer', 'admin', 'ai', 'system')",
            name="ck_activities_creator_kind",
        ),
        Index(
            "ix_activities_compound_order", "compound_id", "sort_order", "id"
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
    evidence_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    assay_name: Mapped[str] = mapped_column(String(512), nullable=False)
    metric: Mapped[str] = mapped_column(String(128), nullable=False)
    operator: Mapped[ActivityOperator] = mapped_column(
        Enum(
            ActivityOperator,
            name="activity_operator",
            native_enum=False,
            length=2,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
    )
    value: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(128), nullable=True)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
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
        default=ChangeActorKind.REVIEWER,
    )


__all__ = ["Activity", "ActivityOperator"]
