"""Small Preview-only database records used to prove transactional application."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class PreviewMarker(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "preview_markers"
    __table_args__ = (
        UniqueConstraint("instance_id", name="uq_preview_markers_instance"),
        CheckConstraint(
            "baseline_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_preview_markers_baseline_hash",
        ),
    )

    instance_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    baseline_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_revision: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ApplicationReceipt(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "preview_application_receipts"
    __table_args__ = (
        Index("ix_preview_receipts_paper_time", "paper_id", "committed_at"),
        CheckConstraint(
            "btrim(idempotency_key) <> ''",
            name="ck_preview_receipts_idempotency_required",
        ),
        UniqueConstraint(
            "instance_id",
            "idempotency_key",
            name="uq_preview_receipts_instance_idempotency",
        ),
        UniqueConstraint("application_id", name="uq_preview_receipts_application"),
        ForeignKeyConstraint(
            ["workspace_id", "paper_id"],
            ["paper_workspaces.id", "paper_workspaces.paper_id"],
            name="fk_preview_receipts_workspace_paper",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "request_digest ~ '^[0-9a-f]{64}$'",
            name="ck_preview_receipts_request_digest",
        ),
        CheckConstraint(
            "candidate_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_preview_receipts_candidate_hash",
        ),
        CheckConstraint(
            "payload_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_preview_receipts_payload_hash",
        ),
        CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_preview_receipts_source_hash",
        ),
    )

    instance_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("preview_markers.instance_id", ondelete="RESTRICT"),
        nullable=False,
    )
    application_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    paper_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("papers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    run_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ai_extraction_runs.id", ondelete="RESTRICT"),
        nullable=True,
    )
    actor_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    entity_map: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    initial_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    committed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["ApplicationReceipt", "PreviewMarker"]
