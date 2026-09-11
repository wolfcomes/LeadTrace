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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.security.policies import WorkflowState


class ReviewTaskStatus(StrEnum):
    """Lifecycle of a Reviewer assignment."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    CHANGES_REQUESTED = "changes_requested"
    COMPLETED = "completed"


class ReviewTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "review_tasks"
    __table_args__ = (
        Index("ix_review_tasks_assignee_status", "assigned_reviewer_id", "status"),
        Index("ix_review_tasks_paper_status", "paper_id", "status"),
        Index(
            "uq_review_tasks_active_assignment",
            "paper_id",
            "assigned_reviewer_id",
            unique=True,
            postgresql_where=text("status <> 'completed'"),
        ),
        CheckConstraint("version > 0", name="ck_review_tasks_positive_version"),
        UniqueConstraint(
            "id",
            "paper_id",
            "assigned_reviewer_id",
            name="uq_review_tasks_id_paper_assignee",
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
    status: Mapped[ReviewTaskStatus] = mapped_column(
        Enum(
            ReviewTaskStatus,
            name="review_task_status",
            native_enum=False,
            length=24,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
        default=ReviewTaskStatus.OPEN,
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class Changeset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "changesets"
    __table_args__ = (
        Index("ix_changesets_paper_state", "paper_id", "workflow_state"),
        Index("ix_changesets_owner_state", "owner_id", "workflow_state"),
        CheckConstraint("version > 0", name="ck_changesets_positive_version"),
        CheckConstraint(
            "submitted_content_hash IS NULL OR "
            "char_length(submitted_content_hash) = 64",
            name="ck_changesets_submitted_content_hash_length",
        ),
        ForeignKeyConstraint(
            ["review_task_id", "paper_id", "owner_id"],
            [
                "review_tasks.id",
                "review_tasks.paper_id",
                "review_tasks.assigned_reviewer_id",
            ],
            name="fk_changesets_task_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "paper_id", name="uq_changesets_id_paper"),
        UniqueConstraint("review_task_id", name="uq_changesets_review_task"),
    )

    review_task_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    paper_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("papers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    base_release_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("releases.id", ondelete="RESTRICT"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    workflow_state: Mapped[WorkflowState] = mapped_column(
        Enum(
            WorkflowState,
            name="changeset_workflow_state",
            native_enum=False,
            length=24,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
        default=WorkflowState.DRAFT,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    validation_results: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    submitted_snapshot: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    submitted_content_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ChangesetItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "changeset_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["changeset_id", "paper_id"],
            ["changesets.id", "changesets.paper_id"],
            name="fk_changeset_items_changeset_paper",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["object_id", "base_revision_id"],
            ["object_revisions.object_id", "object_revisions.id"],
            name="fk_changeset_items_object_revision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["changeset_id", "object_id", "proposed_revision_id"],
            [
                "object_revisions.changeset_id",
                "object_revisions.object_id",
                "object_revisions.id",
            ],
            name="fk_changeset_items_proposed_revision",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "changeset_id", "sequence", name="uq_changeset_items_sequence"
        ),
        UniqueConstraint(
            "changeset_id",
            "object_id",
            name="uq_changeset_items_object",
        ),
        Index("ix_changeset_items_changeset", "changeset_id", "sequence"),
        CheckConstraint("sequence > 0", name="ck_changeset_items_positive_sequence"),
        CheckConstraint(
            "char_length(content_hash) = 64",
            name="ck_changeset_items_content_hash_length",
        ),
    )

    changeset_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    paper_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    object_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("revisioned_objects.id", ondelete="RESTRICT"),
        nullable=False,
    )
    object_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    base_revision_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    proposed_revision_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    proposed_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ChangesetSubmission(UUIDPrimaryKeyMixin, Base):
    """Append-only copy of every submitted changeset version."""

    __tablename__ = "changeset_submissions"
    __table_args__ = (
        UniqueConstraint(
            "changeset_id",
            "submission_number",
            name="uq_changeset_submissions_number",
        ),
        UniqueConstraint(
            "changeset_id",
            "changeset_version",
            name="uq_changeset_submissions_version",
        ),
        CheckConstraint(
            "submission_number > 0",
            name="ck_changeset_submissions_positive_number",
        ),
        CheckConstraint(
            "changeset_version > 0",
            name="ck_changeset_submissions_positive_version",
        ),
        CheckConstraint(
            "char_length(content_hash) = 64",
            name="ck_changeset_submissions_content_hash_length",
        ),
        Index(
            "ix_changeset_submissions_changeset", "changeset_id", "submission_number"
        ),
    )

    changeset_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("changesets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    submission_number: Mapped[int] = mapped_column(Integer, nullable=False)
    changeset_version: Mapped[int] = mapped_column(Integer, nullable=False)
    submitted_by_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
