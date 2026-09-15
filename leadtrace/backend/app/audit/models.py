from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    event,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class AuditImmutableError(RuntimeError):
    """Raised when application code tries to rewrite audit history."""


class AuditChainHead(Base):
    __tablename__ = "audit_chain_head"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_audit_chain_head_singleton"),
        CheckConstraint(
            "char_length(last_event_hash) = 64",
            name="ck_audit_chain_head_hash_length",
        ),
        CheckConstraint(
            "last_sequence_number >= 0",
            name="ck_audit_chain_head_nonnegative_sequence",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_sequence_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint("sequence_number > 0", name="ck_audit_events_positive_sequence"),
        CheckConstraint(
            "char_length(before_hash) = 64 AND char_length(after_hash) = 64",
            name="ck_audit_events_content_hash_lengths",
        ),
        CheckConstraint(
            "char_length(previous_event_hash) = 64 AND char_length(event_hash) = 64",
            name="ck_audit_events_chain_hash_lengths",
        ),
        Index("uq_audit_events_sequence", "sequence_number", unique=True),
        Index("uq_audit_events_event_hash", "event_hash", unique=True),
        Index("ix_audit_events_actor_time", "actor_id", "occurred_at"),
        Index("ix_audit_events_paper_time", "paper_id", "occurred_at"),
        Index("ix_audit_events_changeset_time", "changeset_id", "occurred_at"),
    )

    sequence_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actor_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    paper_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("papers.id", ondelete="RESTRICT"),
        nullable=True,
    )
    changeset_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=True,
    )
    release_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(64), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    before_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    after_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    previous_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)


@event.listens_for(AuditEvent, "before_update")
@event.listens_for(AuditEvent, "before_delete")
def _reject_audit_mutation(*_: object) -> None:
    raise AuditImmutableError("Audit events are append-only")
