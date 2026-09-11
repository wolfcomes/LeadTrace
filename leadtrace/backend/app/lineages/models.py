from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.revisions.models import ObjectKind, RevisionedObject


class Lineage(RevisionedObject):
    __tablename__ = "lineages"
    __table_args__ = (
        UniqueConstraint(
            "paper_id",
            "lineage_key",
            name="uq_lineages_paper_key",
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
    lineage_key: Mapped[str] = mapped_column(String(255), nullable=False)

    __mapper_args__ = {"polymorphic_identity": ObjectKind.LINEAGE}


class LineageEdge(RevisionedObject):
    __tablename__ = "lineage_edges"
    __table_args__ = (
        UniqueConstraint(
            "paper_id",
            "edge_key",
            name="uq_lineage_edges_paper_key",
        ),
        CheckConstraint(
            "parent_compound_id IS NULL OR parent_compound_id <> derived_compound_id",
            name="ck_lineage_edges_no_self_loop",
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
    lineage_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("lineages.id", ondelete="RESTRICT"),
        nullable=False,
    )
    edge_key: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_compound_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("compounds.id", ondelete="RESTRICT"),
        nullable=True,
    )
    derived_compound_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("compounds.id", ondelete="RESTRICT"),
        nullable=False,
    )

    __mapper_args__ = {"polymorphic_identity": ObjectKind.LINEAGE_EDGE}
