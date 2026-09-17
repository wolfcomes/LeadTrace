from __future__ import annotations

from enum import StrEnum
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


class LineageMemberRole(StrEnum):
    ROOT = "root"
    INTERMEDIATE = "intermediate"
    TERMINAL = "terminal"
    UNSPECIFIED = "unspecified"


class LineageEdgeReviewStatus(StrEnum):
    DRAFT = "draft"
    REVIEWER_CONFIRMED = "reviewer_confirmed"
    UNRESOLVED = "unresolved"


class Lineage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "lineages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "paper_id"],
            ["paper_workspaces.id", "paper_workspaces.paper_id"],
            name="fk_lineages_workspace_paper",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "id", "paper_id", "workspace_id", name="uq_lineages_id_paper_workspace"
        ),
        CheckConstraint(
            "btrim(lineage_label) <> ''", name="ck_lineages_label_required"
        ),
        CheckConstraint("sort_order >= 0", name="ck_lineages_nonnegative_order"),
        CheckConstraint(
            "created_by_kind IN ('reviewer', 'admin', 'ai', 'system')",
            name="ck_lineages_creator_kind",
        ),
        Index("ix_lineages_workspace_order", "workspace_id", "sort_order", "id"),
    )

    paper_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("papers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    lineage_label: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class LineageMember(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "lineage_members"
    __table_args__ = (
        ForeignKeyConstraint(
            ["lineage_id", "paper_id", "workspace_id"],
            ["lineages.id", "lineages.paper_id", "lineages.workspace_id"],
            name="fk_lineage_members_lineage_aggregate",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["compound_id", "paper_id", "workspace_id"],
            ["compounds.id", "compounds.paper_id", "compounds.workspace_id"],
            name="fk_lineage_members_compound_aggregate",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "lineage_id", "compound_id", name="uq_lineage_members_lineage_compound"
        ),
        UniqueConstraint(
            "lineage_id",
            "compound_id",
            "paper_id",
            "workspace_id",
            name="uq_lineage_members_edge_endpoint",
        ),
        CheckConstraint(
            "role IN ('root', 'intermediate', 'terminal', 'unspecified')",
            name="ck_lineage_members_role",
        ),
        CheckConstraint(
            "sort_order >= 0", name="ck_lineage_members_nonnegative_order"
        ),
        CheckConstraint(
            "created_by_kind IN ('reviewer', 'admin', 'ai', 'system')",
            name="ck_lineage_members_creator_kind",
        ),
        Index("ix_lineage_members_lineage_order", "lineage_id", "sort_order"),
    )

    paper_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("papers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    lineage_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    compound_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    role: Mapped[LineageMemberRole] = mapped_column(
        Enum(
            LineageMemberRole,
            name="lineage_member_role",
            native_enum=False,
            length=16,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
    )
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


class LineageEdge(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "lineage_edges"
    __table_args__ = (
        ForeignKeyConstraint(
            ["lineage_id", "paper_id", "workspace_id"],
            ["lineages.id", "lineages.paper_id", "lineages.workspace_id"],
            name="fk_lineage_edges_lineage_aggregate",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["lineage_id", "parent_compound_id", "paper_id", "workspace_id"],
            [
                "lineage_members.lineage_id",
                "lineage_members.compound_id",
                "lineage_members.paper_id",
                "lineage_members.workspace_id",
            ],
            name="fk_lineage_edges_parent_membership",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["lineage_id", "child_compound_id", "paper_id", "workspace_id"],
            [
                "lineage_members.lineage_id",
                "lineage_members.compound_id",
                "lineage_members.paper_id",
                "lineage_members.workspace_id",
            ],
            name="fk_lineage_edges_child_membership",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id",
            "paper_id",
            "workspace_id",
            name="uq_lineage_edges_id_paper_workspace",
        ),
        UniqueConstraint(
            "lineage_id",
            "parent_compound_id",
            "child_compound_id",
            name="uq_lineage_edges_directed_pair",
        ),
        CheckConstraint(
            "parent_compound_id <> child_compound_id",
            name="ck_lineage_edges_no_self_loop",
        ),
        CheckConstraint(
            "btrim(relation_type) <> ''",
            name="ck_lineage_edges_relation_required",
        ),
        CheckConstraint(
            "review_status IN ('draft', 'reviewer_confirmed', 'unresolved')",
            name="ck_lineage_edges_review_status",
        ),
        CheckConstraint(
            "sort_order >= 0", name="ck_lineage_edges_nonnegative_order"
        ),
        CheckConstraint(
            "created_by_kind IN ('reviewer', 'admin', 'ai', 'system')",
            name="ck_lineage_edges_creator_kind",
        ),
        Index(
            "ix_lineage_edges_endpoints",
            "lineage_id",
            "parent_compound_id",
            "child_compound_id",
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
    lineage_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    parent_compound_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    child_compound_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String(128), nullable=False)
    modification_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status: Mapped[LineageEdgeReviewStatus] = mapped_column(
        Enum(
            LineageEdgeReviewStatus,
            name="lineage_edge_review_status",
            native_enum=False,
            length=24,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
    )
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


__all__ = [
    "Lineage",
    "LineageEdge",
    "LineageEdgeReviewStatus",
    "LineageMember",
    "LineageMemberRole",
]
