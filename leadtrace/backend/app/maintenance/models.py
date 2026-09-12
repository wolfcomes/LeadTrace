from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class MaintenanceWindow(UUIDPrimaryKeyMixin, Base):
    """One durable maintenance interval; completed rows form the history."""

    __tablename__ = "maintenance_windows"
    __table_args__ = (
        UniqueConstraint("active_slot", name="uq_maintenance_windows_active_slot"),
        CheckConstraint(
            "active_slot IS NULL OR active_slot = 1",
            name="ck_maintenance_windows_active_slot",
        ),
        CheckConstraint(
            "expected_end_at > started_at",
            name="ck_maintenance_windows_expected_end",
        ),
        CheckConstraint(
            "(ended_at IS NULL AND ended_by_id IS NULL AND ended_reason IS NULL "
            "AND active_slot = 1) OR "
            "(ended_at IS NOT NULL AND ended_by_id IS NOT NULL "
            "AND ended_reason IS NOT NULL AND active_slot IS NULL)",
            name="ck_maintenance_windows_lifecycle",
        ),
    )

    active_slot: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=1
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expected_end_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    started_by_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_by_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    ended_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
