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


class CropStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class StructureSourceImage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "structure_source_images"
    __table_args__ = (
        ForeignKeyConstraint(
            ["compound_id", "paper_id", "workspace_id"],
            ["compounds.id", "compounds.paper_id", "compounds.workspace_id"],
            name="fk_structure_source_images_compound_aggregate",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_structure_source_images_source_sha256",
        ),
        CheckConstraint(
            "page_number > 0", name="ck_structure_source_images_positive_page"
        ),
        CheckConstraint(
            "x0 >= 0 AND x0 < x1 AND x1 <= 1 AND "
            "y0 >= 0 AND y0 < y1 AND y1 <= 1",
            name="ck_structure_source_images_normalized_bbox",
        ),
        CheckConstraint(
            "crop_status IN ('pending', 'ready', 'failed')",
            name="ck_structure_source_images_crop_status",
        ),
        Index(
            "ix_structure_source_images_compound_page",
            "compound_id",
            "page_number",
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
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    x0: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    y0: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    x1: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    y1: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    source_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    crop_status: Mapped[CropStatus] = mapped_column(
        Enum(
            CropStatus,
            name="structure_image_crop_status",
            native_enum=False,
            length=16,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
        default=CropStatus.PENDING,
    )
    crop_asset_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("assets.id", ondelete="RESTRICT"),
        nullable=True,
    )


__all__ = ["CropStatus", "StructureSourceImage"]
