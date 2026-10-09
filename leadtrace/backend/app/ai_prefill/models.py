from __future__ import annotations
from sqlalchemy.dialects.postgresql import JSONB

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class AiExtractionRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class AiExtractionRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ai_extraction_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "paper_id"],
            ["paper_workspaces.id", "paper_workspaces.paper_id"],
            name="fk_ai_extraction_runs_workspace_paper",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "starting_workspace_version > 0",
            name="ck_ai_extraction_runs_positive_version",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'superseded')",
            name="ck_ai_extraction_runs_status",
        ),
        CheckConstraint(
            "btrim(engine) <> ''",
            name="ck_ai_extraction_runs_engine_required",
        ),
        CheckConstraint(
            "btrim(engine_version) <> ''",
            name="ck_ai_extraction_runs_engine_version_required",
        ),
        Index(
            "ix_ai_extraction_runs_workspace_time",
            "workspace_id",
            "queued_at",
        ),
        Index(
            "uq_ai_extraction_runs_active_workspace",
            "workspace_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
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
    requested_by_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    starting_workspace_version: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    status: Mapped[AiExtractionRunStatus] = mapped_column(
        Enum(
            AiExtractionRunStatus,
            name="ai_extraction_run_status",
            native_enum=False,
            length=16,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
        default=AiExtractionRunStatus.QUEUED,
    )
    engine: Mapped[str] = mapped_column(String(128), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(128), nullable=False)
    error_summary: Mapped[str | None] = mapped_column(String(512), nullable=True)
    dispatch_token: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


__all__ = ["AiExtractionRun", "AiExtractionRunStatus"]


class AiProvenance(UUIDPrimaryKeyMixin, Base):
    """Append-only operator attestations; never written by scientific producers."""
    __tablename__ = 'ai_provenance'
    __table_args__ = (
        ForeignKeyConstraint(['workspace_id', 'paper_id'], ['paper_workspaces.id', 'paper_workspaces.paper_id'], ondelete='RESTRICT'),
        Index('uq_ai_provenance_workspace_run', 'workspace_id', 'run_key', unique=True),
    )
    paper_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    run_key: Mapped[str] = mapped_column(String(128), nullable=False)
    recorded_by_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    record: Mapped[dict] = mapped_column(JSONB, nullable=False)
