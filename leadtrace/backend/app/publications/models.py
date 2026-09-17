from __future__ import annotations

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
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class AdminDecisionAction(StrEnum):
    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"


class AdminDecision(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "admin_decisions"
    __table_args__ = (
        UniqueConstraint("submission_id", name="uq_admin_decisions_submission"),
        UniqueConstraint(
            "decided_by_id",
            "idempotency_key",
            name="uq_admin_decisions_actor_idempotency",
        ),
        UniqueConstraint(
            "id",
            "paper_id",
            "submission_id",
            "content_hash",
            "action",
            name="uq_admin_decisions_id_submission_identity",
        ),
        ForeignKeyConstraint(
            ["submission_id", "paper_id", "content_hash"],
            ["paper_submissions.id", "paper_submissions.paper_id", "paper_submissions.content_hash"],
            name="fk_admin_decisions_submission_identity",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "action IN ('approve', 'request_changes')",
            name="ck_admin_decisions_action",
        ),
        CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_admin_decisions_content_hash",
        ),
        CheckConstraint("btrim(reason) <> ''", name="ck_admin_decisions_reason"),
        CheckConstraint(
            "btrim(idempotency_key) <> ''",
            name="ck_admin_decisions_idempotency",
        ),
        Index("ix_admin_decisions_time", "decided_at", "id"),
    )

    submission_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    paper_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[AdminDecisionAction] = mapped_column(
        Enum(
            AdminDecisionAction,
            name="admin_decision_action",
            native_enum=False,
            length=24,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    decided_by_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PublishedPaperVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "published_paper_versions"
    __table_args__ = (
        UniqueConstraint("submission_id", name="uq_published_versions_submission"),
        UniqueConstraint(
            "admin_decision_id", name="uq_published_versions_admin_decision"
        ),
        UniqueConstraint(
            "paper_id",
            "version_number",
            name="uq_published_versions_paper_number",
        ),
        UniqueConstraint("id", "paper_id", name="uq_published_versions_id_paper"),
        ForeignKeyConstraint(
            ["submission_id", "paper_id", "content_hash"],
            ["paper_submissions.id", "paper_submissions.paper_id", "paper_submissions.content_hash"],
            name="fk_published_versions_submission_identity",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "admin_decision_id",
                "paper_id",
                "submission_id",
                "content_hash",
                "decision_action",
            ],
            [
                "admin_decisions.id",
                "admin_decisions.paper_id",
                "admin_decisions.submission_id",
                "admin_decisions.content_hash",
                "admin_decisions.action",
            ],
            name="fk_published_versions_decision_identity",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "version_number > 0", name="ck_published_versions_positive_number"
        ),
        CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_published_versions_content_hash",
        ),
        CheckConstraint(
            "decision_action = 'approve'",
            name="ck_published_versions_approved_decision",
        ),
        Index("ix_published_versions_paper_time", "paper_id", "published_at"),
    )

    paper_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    submission_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    admin_decision_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_action: Mapped[AdminDecisionAction] = mapped_column(
        Enum(
            AdminDecisionAction,
            name="published_decision_action",
            native_enum=False,
            length=24,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
    )
    published_by_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["AdminDecision", "AdminDecisionAction", "PublishedPaperVersion"]
