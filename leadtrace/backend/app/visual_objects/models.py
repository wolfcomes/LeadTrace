from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.revisions.models import ObjectKind, RevisionedObject


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

    __mapper_args__ = {"polymorphic_identity": ObjectKind.VISUAL_OBJECT}
