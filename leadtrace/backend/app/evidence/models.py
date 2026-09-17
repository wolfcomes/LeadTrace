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
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.workspaces.models import ChangeActorKind


class EvidenceKind(StrEnum):
    TEXT = "text"
    TABLE = "table"
    SCHEME = "scheme"
    IMAGE = "image"


class EvidenceRole(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    CONTEXTUAL = "contextual"


class Evidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "paper_id"],
            ["paper_workspaces.id", "paper_workspaces.paper_id"],
            name="fk_evidence_workspace_paper",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "id", "paper_id", "workspace_id", name="uq_evidence_id_paper_workspace"
        ),
        CheckConstraint(
            "kind IN ('text', 'table', 'scheme', 'image')",
            name="ck_evidence_kind",
        ),
        CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_evidence_source_sha256",
        ),
        CheckConstraint("page_number > 0", name="ck_evidence_positive_page"),
        CheckConstraint(
            "((x0 IS NULL AND y0 IS NULL AND x1 IS NULL AND y1 IS NULL) OR "
            "(x0 IS NOT NULL AND y0 IS NOT NULL AND "
            "x1 IS NOT NULL AND y1 IS NOT NULL AND "
            "x0 >= 0 AND x0 < x1 AND x1 <= 1 AND "
            "y0 >= 0 AND y0 < y1 AND y1 <= 1))",
            name="ck_evidence_normalized_bbox",
        ),
        CheckConstraint(
            "created_by_kind IN ('reviewer', 'admin', 'ai', 'system')",
            name="ck_evidence_creator_kind",
        ),
        Index("ix_evidence_workspace_page", "workspace_id", "page_number"),
    )

    paper_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("papers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    kind: Mapped[EvidenceKind] = mapped_column(
        Enum(
            EvidenceKind,
            name="evidence_kind",
            native_enum=False,
            length=16,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
    )
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    x0: Mapped[Decimal | None] = mapped_column(Numeric(12, 10), nullable=True)
    y0: Mapped[Decimal | None] = mapped_column(Numeric(12, 10), nullable=True)
    x1: Mapped[Decimal | None] = mapped_column(Numeric(12, 10), nullable=True)
    y1: Mapped[Decimal | None] = mapped_column(Numeric(12, 10), nullable=True)
    quoted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    crop_asset_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("assets.id", ondelete="RESTRICT"),
        nullable=True,
    )
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class EdgeEvidenceLink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "edge_evidence_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["edge_id", "paper_id", "workspace_id"],
            ["lineage_edges.id", "lineage_edges.paper_id", "lineage_edges.workspace_id"],
            name="fk_edge_evidence_links_edge_aggregate",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["evidence_id", "paper_id", "workspace_id"],
            ["evidence.id", "evidence.paper_id", "evidence.workspace_id"],
            name="fk_edge_evidence_links_evidence_aggregate",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "edge_id",
            "evidence_id",
            name="uq_edge_evidence_links_edge_evidence",
        ),
        CheckConstraint(
            "role IN ('supports', 'contradicts', 'contextual')",
            name="ck_edge_evidence_links_role",
        ),
        CheckConstraint(
            "created_by_kind IN ('reviewer', 'admin', 'ai', 'system')",
            name="ck_edge_evidence_links_creator_kind",
        ),
        Index("ix_edge_evidence_links_evidence", "evidence_id", "edge_id"),
    )

    paper_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("papers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    edge_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    evidence_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    role: Mapped[EvidenceRole] = mapped_column(
        Enum(
            EvidenceRole,
            name="edge_evidence_role",
            native_enum=False,
            length=16,
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


__all__ = ["EdgeEvidenceLink", "Evidence", "EvidenceKind", "EvidenceRole"]
