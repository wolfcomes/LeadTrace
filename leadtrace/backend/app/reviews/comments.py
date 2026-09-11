from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.audit.service import AuditService, canonical_content_hash
from app.db.base import Base, UUIDPrimaryKeyMixin
from app.reviews.models import Changeset, ChangesetItem
from app.revisions.models import ObjectKind
from app.users.models import User, UserRole


class CommentTargetType(StrEnum):
    CHANGESET = "changeset"
    CHANGE_ITEM = "change_item"
    FIELD = "field"
    REGION = "region"
    COMPOUND = "compound"
    STRUCTURE = "structure"
    EDGE = "edge"


class CommentAction(StrEnum):
    CREATED = "created"
    RESOLVED = "resolved"
    REOPENED = "reopened"


class CommentState(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class CommentImmutableError(RuntimeError):
    """Raised when application code attempts to rewrite comment history."""


class CommentNotFound(LookupError):
    pass


class CommentForbidden(PermissionError):
    pass


class InvalidComment(ValueError):
    pass


class CommentStateConflict(InvalidComment):
    pass


class ReviewComment(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "review_comments"
    __table_args__ = (
        Index("ix_review_comments_changeset_time", "changeset_id", "created_at"),
    )

    changeset_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("changesets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    changeset_item_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("changeset_items.id", ondelete="RESTRICT"),
        nullable=True,
    )
    target_type: Mapped[str] = mapped_column(String(24), nullable=False)
    target_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    field_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    author_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReviewCommentEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "review_comment_events"
    __table_args__ = (
        UniqueConstraint(
            "comment_id", "sequence", name="uq_review_comment_events_sequence"
        ),
        CheckConstraint(
            "sequence > 0", name="ck_review_comment_events_positive_sequence"
        ),
        Index("ix_review_comment_events_comment", "comment_id", "sequence"),
    )

    comment_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("review_comments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


@event.listens_for(ReviewComment, "before_update")
@event.listens_for(ReviewComment, "before_delete")
@event.listens_for(ReviewCommentEvent, "before_update")
@event.listens_for(ReviewCommentEvent, "before_delete")
def _reject_comment_history_mutation(*_: object) -> None:
    raise CommentImmutableError("Review comment history is append-only")


class CommentCreateRequest(BaseModel):
    target_type: CommentTargetType
    target_id: UUID | None = None
    changeset_item_id: UUID | None = None
    field_path: str | None = Field(default=None, max_length=500)
    body: str = Field(min_length=1, max_length=20000)


class CommentTransitionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=4000)


class CommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    changeset_id: UUID
    changeset_item_id: UUID | None
    target_type: CommentTargetType
    target_id: UUID | None
    field_path: str | None
    body: str
    author_id: UUID
    created_at: datetime
    state: CommentState

    @classmethod
    def from_model(
        cls, comment: ReviewComment, state: CommentState
    ) -> "CommentResponse":
        return cls(
            id=comment.id,
            changeset_id=comment.changeset_id,
            changeset_item_id=comment.changeset_item_id,
            target_type=CommentTargetType(comment.target_type),
            target_id=comment.target_id,
            field_path=comment.field_path,
            body=comment.body,
            author_id=comment.author_id,
            created_at=comment.created_at,
            state=state,
        )


class CommentEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    comment_id: UUID
    action: CommentAction
    actor_id: UUID
    reason: str
    sequence: int
    created_at: datetime


def _clean(value: str, field: str) -> str:
    clean = value.strip()
    if not clean:
        raise InvalidComment(f"{field} is required")
    return clean


class CommentService:
    def create_comment(
        self,
        session: Session,
        *,
        changeset_id: UUID,
        actor_id: UUID,
        target_type: CommentTargetType,
        target_id: UUID | None,
        changeset_item_id: UUID | None,
        field_path: str | None,
        body: str,
        ip_address: str,
        request_id: str,
    ) -> tuple[ReviewComment, CommentState]:
        changeset = self._get_scoped_changeset(
            session, changeset_id, actor_id, for_update=True
        )
        normalized_target_id = self._validate_target(
            session,
            changeset,
            target_type,
            target_id,
            changeset_item_id,
            field_path,
        )
        comment = ReviewComment(
            changeset_id=changeset.id,
            changeset_item_id=changeset_item_id,
            target_type=target_type.value,
            target_id=normalized_target_id,
            field_path=field_path.strip() if field_path else None,
            body=_clean(body, "body"),
            author_id=actor_id,
        )
        session.add(comment)
        session.flush()
        history = ReviewCommentEvent(
            comment_id=comment.id,
            action=CommentAction.CREATED.value,
            actor_id=actor_id,
            reason="Comment created",
            sequence=1,
        )
        session.add(history)
        session.flush()
        state = CommentState.OPEN
        self._append_audit(
            session,
            changeset=changeset,
            comment=comment,
            actor_id=actor_id,
            action=CommentAction.CREATED,
            reason="Created review comment",
            before_state=None,
            after_state=state,
            ip_address=ip_address,
            request_id=request_id,
        )
        return comment, state

    def list_comments(
        self,
        session: Session,
        *,
        changeset_id: UUID,
        actor_id: UUID,
    ) -> list[tuple[ReviewComment, CommentState]]:
        self._get_scoped_changeset(session, changeset_id, actor_id)
        comments = list(
            session.scalars(
                select(ReviewComment)
                .where(ReviewComment.changeset_id == changeset_id)
                .order_by(ReviewComment.created_at, ReviewComment.id)
            )
        )
        return [(comment, self._state(session, comment.id)) for comment in comments]

    def list_history(
        self,
        session: Session,
        *,
        comment_id: UUID,
        actor_id: UUID,
    ) -> list[ReviewCommentEvent]:
        comment, _ = self.get_comment(session, comment_id=comment_id, actor_id=actor_id)
        return list(
            session.scalars(
                select(ReviewCommentEvent)
                .where(ReviewCommentEvent.comment_id == comment.id)
                .order_by(ReviewCommentEvent.sequence)
            )
        )

    def get_comment(
        self,
        session: Session,
        *,
        comment_id: UUID,
        actor_id: UUID,
        for_update: bool = False,
    ) -> tuple[ReviewComment, CommentState]:
        comment = session.scalar(
            select(ReviewComment).where(ReviewComment.id == comment_id)
        )
        if comment is None:
            raise CommentNotFound("Comment not found")
        self._get_scoped_changeset(
            session,
            comment.changeset_id,
            actor_id,
            for_update=for_update,
        )
        if for_update:
            comment = session.scalar(
                select(ReviewComment)
                .where(ReviewComment.id == comment_id)
                .with_for_update()
            )
            if comment is None:
                raise CommentNotFound("Comment not found")
        return comment, self._state(session, comment.id)

    def transition(
        self,
        session: Session,
        *,
        comment_id: UUID,
        actor_id: UUID,
        action: CommentAction,
        reason: str,
        ip_address: str,
        request_id: str,
    ) -> tuple[ReviewComment, CommentState]:
        if action not in {CommentAction.RESOLVED, CommentAction.REOPENED}:
            raise InvalidComment("Unsupported comment transition")
        comment, before_state = self.get_comment(
            session, comment_id=comment_id, actor_id=actor_id, for_update=True
        )
        expected = (
            CommentState.OPEN
            if action is CommentAction.RESOLVED
            else CommentState.RESOLVED
        )
        if before_state is not expected:
            raise CommentStateConflict(
                f"Comment is already {before_state.value}"
            )
        changeset = session.get(Changeset, comment.changeset_id)
        if changeset is None:
            raise CommentNotFound("Changeset not found")
        latest_sequence = session.scalar(
            select(func.max(ReviewCommentEvent.sequence)).where(
                ReviewCommentEvent.comment_id == comment.id
            )
        )
        history = ReviewCommentEvent(
            comment_id=comment.id,
            action=action.value,
            actor_id=actor_id,
            reason=_clean(reason, "reason"),
            sequence=int(latest_sequence or 0) + 1,
        )
        session.add(history)
        session.flush()
        after_state = (
            CommentState.RESOLVED
            if action is CommentAction.RESOLVED
            else CommentState.OPEN
        )
        self._append_audit(
            session,
            changeset=changeset,
            comment=comment,
            actor_id=actor_id,
            action=action,
            reason=history.reason,
            before_state=before_state,
            after_state=after_state,
            ip_address=ip_address,
            request_id=request_id,
        )
        return comment, after_state

    @staticmethod
    def _get_scoped_changeset(
        session: Session,
        changeset_id: UUID,
        actor_id: UUID,
        *,
        for_update: bool = False,
    ) -> Changeset:
        actor = session.get(User, actor_id)
        statement = select(Changeset).where(Changeset.id == changeset_id)
        if for_update:
            statement = statement.with_for_update()
        changeset = session.scalar(statement)
        if actor is None or changeset is None:
            raise CommentNotFound("Changeset not found")
        if not actor.is_enabled or actor.role is UserRole.VISITOR:
            raise CommentForbidden("Comments require Reviewer or Admin")
        if actor.role is UserRole.REVIEWER and changeset.owner_id != actor.id:
            raise CommentNotFound("Changeset not found")
        return changeset

    @staticmethod
    def _validate_target(
        session: Session,
        changeset: Changeset,
        target_type: CommentTargetType,
        target_id: UUID | None,
        changeset_item_id: UUID | None,
        field_path: str | None,
    ) -> UUID | None:
        scoped_item = None
        if changeset_item_id is not None:
            item = session.get(ChangesetItem, changeset_item_id)
            if item is None or item.changeset_id != changeset.id:
                raise InvalidComment("Comment item is outside the Changeset")
            scoped_item = item
        if target_type is CommentTargetType.CHANGESET:
            if target_id not in {None, changeset.id}:
                raise InvalidComment("Changeset comment target does not match scope")
            return changeset.id
        if target_type is CommentTargetType.CHANGE_ITEM and changeset_item_id is None:
            raise InvalidComment("change_item comments require changeset_item_id")
        if target_type is CommentTargetType.FIELD:
            if not (field_path or "").strip():
                raise InvalidComment("field comments require field_path")
            if target_id is None and scoped_item is None:
                raise InvalidComment("field comments require a target or change item")
        changeset_items = list(
            session.scalars(
                select(ChangesetItem).where(
                    ChangesetItem.changeset_id == changeset.id
                )
            )
        )
        if target_type is CommentTargetType.FIELD and target_id is not None:
            allowed_field_targets = (
                {scoped_item.id, scoped_item.object_id}
                if scoped_item is not None
                else {
                    changeset.id,
                    changeset.paper_id,
                    *(item.id for item in changeset_items),
                    *(item.object_id for item in changeset_items),
                }
            )
            if target_id not in allowed_field_targets:
                raise InvalidComment("Field comment target is outside the Changeset")
        target_kinds = {
            CommentTargetType.REGION: ObjectKind.VISUAL_REGION,
            CommentTargetType.COMPOUND: ObjectKind.COMPOUND,
            CommentTargetType.STRUCTURE: ObjectKind.STRUCTURE,
            CommentTargetType.EDGE: ObjectKind.LINEAGE_EDGE,
        }
        expected_kind = target_kinds.get(target_type)
        if expected_kind is not None:
            if target_id is None:
                raise InvalidComment(f"{target_type.value} comments require target_id")
            candidate_items = [scoped_item] if scoped_item is not None else changeset_items
            if not any(
                item is not None
                and item.object_id == target_id
                and item.object_kind == expected_kind.value
                for item in candidate_items
            ):
                raise InvalidComment(
                    f"{target_type.value} comment target is outside the Changeset"
                )
        if (
            target_type is CommentTargetType.CHANGE_ITEM
            and target_id is not None
            and scoped_item is not None
            and target_id not in {scoped_item.id, scoped_item.object_id}
        ):
            raise InvalidComment("Change item comment target does not match item")
        return target_id or changeset_item_id

    @staticmethod
    def _state(session: Session, comment_id: UUID) -> CommentState:
        action = session.scalar(
            select(ReviewCommentEvent.action)
            .where(ReviewCommentEvent.comment_id == comment_id)
            .order_by(ReviewCommentEvent.sequence.desc())
            .limit(1)
        )
        if action is None:
            raise CommentNotFound("Comment history not found")
        return (
            CommentState.RESOLVED
            if action == CommentAction.RESOLVED.value
            else CommentState.OPEN
        )

    @staticmethod
    def _append_audit(
        session: Session,
        *,
        changeset: Changeset,
        comment: ReviewComment,
        actor_id: UUID,
        action: CommentAction,
        reason: str,
        before_state: CommentState | None,
        after_state: CommentState,
        ip_address: str,
        request_id: str,
    ) -> None:
        body_hash = canonical_content_hash(comment.body)
        before = {
            "comment_id": str(comment.id),
            "state": before_state.value if before_state else None,
            "body_hash": body_hash,
        }
        after = {
            "comment_id": str(comment.id),
            "state": after_state.value,
            "body_hash": body_hash,
        }
        AuditService().append_event(
            session,
            actor_id=actor_id,
            action=f"review.comment.{action.value}",
            target_type="review_comment",
            target_id=comment.id,
            paper_id=changeset.paper_id,
            changeset_id=changeset.id,
            release_id=changeset.base_release_id,
            ip_address=ip_address,
            request_id=request_id,
            result="success",
            reason=reason,
            before_hash=canonical_content_hash(before),
            after_hash=canonical_content_hash(after),
            details={
                "target_type": comment.target_type,
                "target_id": comment.target_id,
                "field_path": comment.field_path,
            },
        )
