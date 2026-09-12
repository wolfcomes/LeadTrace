from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class ApprovalDecision(UUIDPrimaryKeyMixin, Base):
    """Append-only administrative decision tied to one submitted snapshot."""

    __tablename__ = "approval_decisions"
    __table_args__ = (
        UniqueConstraint(
            "changeset_id",
            "submission_version",
            "decision",
            name="uq_approval_decisions_submission_decision",
        ),
        CheckConstraint(
            "decision IN ('approve', 'request_changes', 'reject')",
            name="ck_approval_decisions_decision",
        ),
        CheckConstraint(
            "char_length(snapshot_hash) = 64",
            name="ck_approval_decisions_snapshot_hash",
        ),
        Index("ix_approval_decisions_changeset", "changeset_id", "created_at"),
    )

    changeset_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("changesets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    submission_version: Mapped[int] = mapped_column(nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


@event.listens_for(ApprovalDecision, "before_update")
@event.listens_for(ApprovalDecision, "before_delete")
def _reject_approval_mutation(*_: object) -> None:
    raise RuntimeError("Approval decisions are append-only")
