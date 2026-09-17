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
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ReviewTaskState(StrEnum):
    ASSIGNED = "assigned"
    SUBMITTED = "submitted"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"


class WorkspaceState(StrEnum):
    EDITING = "editing"
    SUBMITTED = "submitted"
    APPROVED = "approved"


class PaperSection(StrEnum):
    BIBLIOGRAPHY = "bibliography"
    COMPOUNDS = "compounds"
    STRUCTURES = "structures"
    LINEAGES = "lineages"
    EDGE_EVIDENCE = "edge_evidence"
    ACTIVITIES = "activities"


class PaperSectionState(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    NOT_REPORTED = "not_reported"


class ChangeActorKind(StrEnum):
    REVIEWER = "reviewer"
    ADMIN = "admin"
    AI = "ai"
    SYSTEM = "system"


class ReviewTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "review_tasks"
    __table_args__ = (
        UniqueConstraint("id", "paper_id", name="uq_review_tasks_id_paper"),
        Index("ix_review_tasks_assignee_status", "assigned_reviewer_id", "status"),
        Index("ix_review_tasks_paper_status", "paper_id", "status"),
        Index(
            "uq_review_tasks_active_paper",
            "paper_id",
            unique=True,
            postgresql_where=text("status <> 'approved'"),
        ),
        CheckConstraint("version > 0", name="ck_review_tasks_positive_version"),
        CheckConstraint(
            "status IN ('assigned', 'submitted', 'changes_requested', 'approved')",
            name="ck_review_tasks_status",
        ),
    )

    paper_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("papers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    assigned_reviewer_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_by_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[ReviewTaskState] = mapped_column(
        Enum(
            ReviewTaskState,
            name="review_task_state",
            native_enum=False,
            length=24,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
        default=ReviewTaskState.ASSIGNED,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class PaperWorkspace(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "paper_workspaces"
    __table_args__ = (
        UniqueConstraint("review_task_id", name="uq_paper_workspaces_review_task"),
        UniqueConstraint("id", "paper_id", name="uq_paper_workspaces_id_paper"),
        ForeignKeyConstraint(
            ["review_task_id", "paper_id"],
            ["review_tasks.id", "review_tasks.paper_id"],
            name="fk_paper_workspaces_task_paper",
            ondelete="RESTRICT",
        ),
        CheckConstraint("version > 0", name="ck_paper_workspaces_positive_version"),
        CheckConstraint(
            "state IN ('editing', 'submitted', 'approved')",
            name="ck_paper_workspaces_state",
        ),
        Index("ix_paper_workspaces_paper_state", "paper_id", "state"),
    )

    paper_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("papers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    review_task_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    state: Mapped[WorkspaceState] = mapped_column(
        Enum(
            WorkspaceState,
            name="paper_workspace_state",
            native_enum=False,
            length=16,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
        default=WorkspaceState.EDITING,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class PaperSubmission(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "paper_submissions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "paper_id"],
            ["paper_workspaces.id", "paper_workspaces.paper_id"],
            name="fk_paper_submissions_workspace_paper",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["review_task_id", "paper_id"],
            ["review_tasks.id", "review_tasks.paper_id"],
            name="fk_paper_submissions_task_paper",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["submitted_by_id"],
            ["users.id"],
            name="fk_paper_submissions_submitter",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "workspace_id",
            "submission_number",
            name="uq_paper_submissions_workspace_number",
        ),
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_paper_submissions_workspace_idempotency",
        ),
        UniqueConstraint(
            "id",
            "paper_id",
            "content_hash",
            name="uq_paper_submissions_id_paper_hash",
        ),
        CheckConstraint(
            "submission_number > 0",
            name="ck_paper_submissions_positive_number",
        ),
        CheckConstraint(
            "workspace_version > 0",
            name="ck_paper_submissions_positive_workspace_version",
        ),
        CheckConstraint(
            "btrim(idempotency_key) <> ''",
            name="ck_paper_submissions_idempotency_required",
        ),
        CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_paper_submissions_content_hash",
        ),
        Index(
            "ix_paper_submissions_workspace_time",
            "workspace_id",
            "submitted_at",
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
    review_task_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    submission_number: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    workspace_version: Mapped[int] = mapped_column(Integer, nullable=False)
    submitted_by_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PaperSectionReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "paper_section_reviews"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "paper_id"],
            ["paper_workspaces.id", "paper_workspaces.paper_id"],
            name="fk_paper_section_reviews_workspace_paper",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workspace_id",
            "section_key",
            name="uq_paper_section_reviews_workspace_section",
        ),
        CheckConstraint(
            "section_key IN ('bibliography', 'compounds', 'structures', "
            "'lineages', 'edge_evidence', 'activities')",
            name="ck_paper_section_reviews_key",
        ),
        CheckConstraint(
            "state IN ('pending', 'completed', 'not_reported')",
            name="ck_paper_section_reviews_state",
        ),
        Index("ix_paper_section_reviews_paper", "paper_id", "workspace_id"),
    )

    paper_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("papers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    section_key: Mapped[PaperSection] = mapped_column(
        Enum(
            PaperSection,
            name="paper_section_key",
            native_enum=False,
            length=24,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
    )
    state: Mapped[PaperSectionState] = mapped_column(
        Enum(
            PaperSectionState,
            name="paper_section_state",
            native_enum=False,
            length=16,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
        default=PaperSectionState.PENDING,
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class ChangeEventImmutableError(RuntimeError):
    """Raised when application code tries to rewrite Workspace history."""


class ChangeEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "change_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "paper_id"],
            ["paper_workspaces.id", "paper_workspaces.paper_id"],
            name="fk_change_events_workspace_paper",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "btrim(entity_type) <> ''",
            name="ck_change_events_entity_type_required",
        ),
        CheckConstraint(
            "btrim(action) <> ''",
            name="ck_change_events_action_required",
        ),
        CheckConstraint(
            "before_value IS NOT NULL OR after_value IS NOT NULL",
            name="ck_change_events_has_value",
        ),
        CheckConstraint(
            "actor_kind IN ('reviewer', 'admin', 'ai', 'system')",
            name="ck_change_events_actor_kind",
        ),
        CheckConstraint(
            "((actor_kind IN ('reviewer', 'admin') AND actor_id IS NOT NULL) "
            "OR (actor_kind IN ('ai', 'system') AND actor_id IS NULL))",
            name="ck_change_events_actor_identity",
        ),
        Index("ix_change_events_workspace_time", "workspace_id", "occurred_at"),
        Index("ix_change_events_entity", "entity_type", "entity_id"),
        Index("ix_change_events_paper_time", "paper_id", "occurred_at"),
    )

    paper_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("papers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    before_value: Mapped[dict[str, object] | None] = mapped_column(
        JSONB, nullable=True
    )
    after_value: Mapped[dict[str, object] | None] = mapped_column(
        JSONB, nullable=True
    )
    actor_kind: Mapped[ChangeActorKind] = mapped_column(
        Enum(
            ChangeActorKind,
            name="change_actor_kind",
            native_enum=False,
            length=16,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
    )
    actor_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    ai_run_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


@event.listens_for(ChangeEvent, "before_update")
@event.listens_for(ChangeEvent, "before_delete")
def _reject_change_event_mutation(*_: object) -> None:
    raise ChangeEventImmutableError("Change events are append-only")


__all__ = [
    "ChangeActorKind",
    "ChangeEvent",
    "ChangeEventImmutableError",
    "PaperSection",
    "PaperSectionReview",
    "PaperSectionState",
    "PaperSubmission",
    "PaperWorkspace",
    "ReviewTask",
    "ReviewTaskState",
    "WorkspaceState",
]
