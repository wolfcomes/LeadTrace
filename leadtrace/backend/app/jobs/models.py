from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CropJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


CropJobState = CropJobStatus


class CropJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "crop_jobs"
    __table_args__ = (
        UniqueConstraint("input_hash", name="uq_crop_jobs_input_hash"),
        Index("ix_crop_jobs_status_created", "status", "created_at"),
        CheckConstraint("page_number > 0", name="ck_crop_jobs_positive_page"),
        CheckConstraint("x0 >= 0 AND y0 >= 0 AND x1 <= 1 AND y1 <= 1 AND x0 < x1 AND y0 < y1", name="ck_crop_jobs_normalized_bounds"),
        CheckConstraint("rotation IN (0, 90, 180, 270)", name="ck_crop_jobs_rotation"),
        CheckConstraint("padding >= 0", name="ck_crop_jobs_nonnegative_padding"),
        CheckConstraint("dpi > 0", name="ck_crop_jobs_positive_dpi"),
    )

    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_pdf_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_asset_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("assets.id", ondelete="RESTRICT"), nullable=True
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    x0: Mapped[float] = mapped_column(Float, nullable=False)
    y0: Mapped[float] = mapped_column(Float, nullable=False)
    x1: Mapped[float] = mapped_column(Float, nullable=False)
    y1: Mapped[float] = mapped_column(Float, nullable=False)
    rotation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    padding: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dpi: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    renderer_version: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[CropJobStatus] = mapped_column(
        Enum(CropJobStatus, name="crop_job_status", native_enum=False, length=16,
             values_callable=lambda values: [value.value for value in values]),
        nullable=False,
        default=CropJobStatus.PENDING,
    )
    asset_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("assets.id", ondelete="RESTRICT"), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
