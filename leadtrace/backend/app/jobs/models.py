from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CropJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class CropJobAttemptStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STALE = "stale"


CropJobState = CropJobStatus


class CropJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "crop_jobs"
    __table_args__ = (
        UniqueConstraint("input_hash", name="uq_crop_jobs_input_hash"),
        Index("ix_crop_jobs_status_created", "status", "created_at"),
        Index("ix_crop_jobs_status_dispatch", "status", "dispatched_at"),
        Index("ix_crop_jobs_status_heartbeat", "status", "heartbeat_at"),
        CheckConstraint("page_number > 0", name="ck_crop_jobs_positive_page"),
        CheckConstraint("x0 >= 0 AND y0 >= 0 AND x1 <= 1 AND y1 <= 1 AND x0 < x1 AND y0 < y1", name="ck_crop_jobs_normalized_bounds"),
        CheckConstraint("rotation IN (0, 90, 180, 270)", name="ck_crop_jobs_rotation"),
        CheckConstraint("padding >= 0", name="ck_crop_jobs_nonnegative_padding"),
        CheckConstraint("dpi > 0", name="ck_crop_jobs_positive_dpi"),
        CheckConstraint("attempt_count >= 0", name="ck_crop_jobs_nonnegative_attempts"),
        CheckConstraint("max_attempts > 0", name="ck_crop_jobs_positive_max_attempts"),
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
    dispatch_token: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_by_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("crop_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class CropJobAttempt(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "crop_job_attempts"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "attempt_number",
            name="uq_crop_job_attempts_number",
        ),
        UniqueConstraint(
            "delivery_token",
            name="uq_crop_job_attempts_delivery_token",
        ),
        CheckConstraint(
            "attempt_number > 0",
            name="ck_crop_job_attempts_positive_number",
        ),
        Index("ix_crop_job_attempts_job_status", "job_id", "status"),
    )

    job_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("crop_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    delivery_token: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    status: Mapped[CropJobAttemptStatus] = mapped_column(
        Enum(
            CropJobAttemptStatus,
            name="crop_job_attempt_status",
            native_enum=False,
            length=16,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class CropJobRetryOperation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "crop_job_retry_operations"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "actor_id",
            "idempotency_key",
            name="uq_crop_job_retry_operations_key",
        ),
        CheckConstraint(
            "attempt_count_before >= 0",
            name="ck_crop_job_retry_operations_attempt_count",
        ),
        CheckConstraint(
            "max_attempts_after > attempt_count_before",
            name="ck_crop_job_retry_operations_budget",
        ),
        Index("ix_crop_job_retry_operations_job", "job_id", "created_at"),
    )

    job_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("crop_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    attempt_count_before: Mapped[int] = mapped_column(Integer, nullable=False)
    max_attempts_after: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
