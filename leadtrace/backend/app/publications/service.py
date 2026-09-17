from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.assets.models import (
    Asset,
    AssetAccessLevel,
    AssetCategory,
    AssetIntegrityState,
)
from app.catalog.models import PaperSource, PaperSourceIntegrityState
from app.papers.models import Paper, PaperCatalogState
from app.publications.models import (
    AdminDecision,
    AdminDecisionAction,
    PublishedPaperVersion,
)
from app.security.policies import Principal
from app.users.models import User, UserRole
from app.workspaces.models import (
    ChangeActorKind,
    ChangeEvent,
    PaperSubmission,
    PaperWorkspace,
    ReviewTask,
    ReviewTaskState,
    WorkspaceState,
)


class DecisionNotFoundError(LookupError):
    pass


class DecisionForbiddenError(PermissionError):
    pass


class DecisionReasonRequiredError(ValueError):
    pass


class DecisionHashMismatchError(RuntimeError):
    pass


class DecisionStateConflictError(RuntimeError):
    pass


class DecisionIdempotencyConflictError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DecisionResult:
    decision: AdminDecision
    published_version: PublishedPaperVersion | None


@dataclass(frozen=True, slots=True)
class PendingSubmission:
    submission: PaperSubmission
    paper: Paper


@dataclass(frozen=True, slots=True)
class SubmissionReview:
    submission: PaperSubmission
    paper: Paper
    change_events: tuple[ChangeEvent, ...]
    reviewer_diff: tuple[ChangeEvent, ...]


@dataclass(frozen=True, slots=True)
class PublishedPaper:
    paper: Paper
    version: PublishedPaperVersion


DecisionActor = User | Principal


def _actor(actor: DecisionActor) -> tuple[UUID, UserRole]:
    if isinstance(actor, User):
        return actor.id, actor.role
    return actor.user_id, actor.role


class PublicationService:
    @staticmethod
    def _require_admin(actor: DecisionActor) -> None:
        _, role = _actor(actor)
        if role is not UserRole.ADMIN:
            raise DecisionForbiddenError("Permission denied")

    def list_pending_submissions(
        self,
        session: Session,
        *,
        actor: DecisionActor,
    ) -> list[PendingSubmission]:
        self._require_admin(actor)
        rows = session.execute(
            select(PaperSubmission, Paper)
            .join(Paper, Paper.id == PaperSubmission.paper_id)
            .outerjoin(
                AdminDecision,
                AdminDecision.submission_id == PaperSubmission.id,
            )
            .where(AdminDecision.id.is_(None))
            .order_by(PaperSubmission.submitted_at, PaperSubmission.id)
        )
        return [PendingSubmission(submission, paper) for submission, paper in rows]

    def get_submission_review(
        self,
        session: Session,
        *,
        submission_id: UUID,
        actor: DecisionActor,
    ) -> SubmissionReview:
        self._require_admin(actor)
        submission = session.get(PaperSubmission, submission_id)
        if submission is None:
            raise DecisionNotFoundError("Resource not found")
        paper = session.get(Paper, submission.paper_id)
        if paper is None:
            raise DecisionNotFoundError("Resource not found")
        boundary = session.scalar(
            select(ChangeEvent).where(
                ChangeEvent.workspace_id == submission.workspace_id,
                ChangeEvent.entity_type == "paper_submission",
                ChangeEvent.entity_id == submission.id,
                ChangeEvent.action == "workspace.submit",
            )
        )
        if boundary is None:
            raise DecisionStateConflictError("Submission history boundary is missing")
        events = tuple(
            session.scalars(
                select(ChangeEvent)
                .where(
                    ChangeEvent.workspace_id == submission.workspace_id,
                    or_(
                        ChangeEvent.occurred_at < boundary.occurred_at,
                        and_(
                            ChangeEvent.occurred_at == boundary.occurred_at,
                            ChangeEvent.id <= boundary.id,
                        ),
                    ),
                )
                .order_by(ChangeEvent.occurred_at, ChangeEvent.id)
            )
        )
        previous_submission = session.scalar(
            select(PaperSubmission)
            .where(
                PaperSubmission.workspace_id == submission.workspace_id,
                PaperSubmission.submission_number < submission.submission_number,
            )
            .order_by(PaperSubmission.submission_number.desc())
            .limit(1)
        )
        current_submission_events = events
        if previous_submission is not None:
            previous_boundary_index = next(
                (
                    index
                    for index, event in enumerate(events)
                    if event.entity_type == "paper_submission"
                    and event.entity_id == previous_submission.id
                    and event.action == "workspace.submit"
                ),
                None,
            )
            if previous_boundary_index is None:
                raise DecisionStateConflictError(
                    "Previous submission history boundary is missing"
                )
            current_submission_events = events[previous_boundary_index + 1 :]
        reviewer_diff = tuple(
            event
            for event in current_submission_events
            if event.actor_kind is ChangeActorKind.REVIEWER
            and event.action != "workspace.submit"
        )
        return SubmissionReview(submission, paper, events, reviewer_diff)

    def list_published_papers(self, session: Session) -> list[PublishedPaper]:
        rows = session.execute(
            select(Paper, PublishedPaperVersion)
            .join(
                PublishedPaperVersion,
                PublishedPaperVersion.id == Paper.current_published_version_id,
            )
            .order_by(PublishedPaperVersion.published_at, Paper.id)
        )
        return [PublishedPaper(paper, version) for paper, version in rows]

    def get_published_paper(
        self,
        session: Session,
        *,
        paper_id: UUID,
    ) -> PublishedPaper:
        row = session.execute(
            select(Paper, PublishedPaperVersion)
            .join(
                PublishedPaperVersion,
                PublishedPaperVersion.id == Paper.current_published_version_id,
            )
            .where(Paper.id == paper_id)
        ).one_or_none()
        if row is None:
            raise DecisionNotFoundError("Resource not found")
        return PublishedPaper(row[0], row[1])

    @staticmethod
    def _require_verified_source(session: Session, paper: Paper) -> None:
        source = session.scalar(
            select(PaperSource)
            .where(PaperSource.id == paper.source_id)
            .with_for_update()
        )
        if source is None:
            raise DecisionStateConflictError("Paper source is not verified")
        asset = session.scalar(
            select(Asset).where(Asset.id == source.asset_id).with_for_update()
        )
        expected_storage_key = f"source/{source.source_root_key}/{source.source_key}"
        if (
            paper.catalog_state is PaperCatalogState.SOURCE_ERROR
            or source.integrity_state is not PaperSourceIntegrityState.VERIFIED
            or asset is None
            or asset.integrity_state is not AssetIntegrityState.VERIFIED
            or asset.category is not AssetCategory.ARTICLE_PDF
            or asset.access_level is not AssetAccessLevel.REVIEWER
            or asset.mime_type != "application/pdf"
            or asset.storage_key != expected_storage_key
            or asset.sha256 != source.sha256
            or asset.byte_size != source.byte_size
            or asset.page_count != source.page_count
        ):
            raise DecisionStateConflictError("Paper source is not verified")

    def decide(
        self,
        session: Session,
        *,
        submission_id: UUID,
        content_hash: str,
        action: AdminDecisionAction,
        reason: str,
        idempotency_key: str,
        actor: DecisionActor,
    ) -> DecisionResult:
        actor_id, _ = _actor(actor)
        self._require_admin(actor)
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise DecisionReasonRequiredError("A decision reason is required")
        key = idempotency_key.strip()
        if not key:
            raise ValueError("idempotency_key is required")
        if len(key) > 255:
            raise ValueError("idempotency_key must not exceed 255 characters")

        submission = session.scalar(
            select(PaperSubmission)
            .where(PaperSubmission.id == submission_id)
            .with_for_update()
        )
        if submission is None:
            raise DecisionNotFoundError("Resource not found")

        replay = session.scalar(
            select(AdminDecision).where(
                AdminDecision.decided_by_id == actor_id,
                AdminDecision.idempotency_key == key,
            )
        )
        if replay is not None:
            if (
                replay.submission_id != submission.id
                or replay.content_hash != content_hash
                or replay.action is not action
                or replay.reason != normalized_reason
            ):
                raise DecisionIdempotencyConflictError(
                    "Idempotency key was already used for a different decision"
                )
            published = session.scalar(
                select(PublishedPaperVersion).where(
                    PublishedPaperVersion.admin_decision_id == replay.id
                )
            )
            return DecisionResult(replay, published)

        existing = session.scalar(
            select(AdminDecision).where(AdminDecision.submission_id == submission.id)
        )
        if existing is not None:
            raise DecisionStateConflictError("Submission already has an Admin decision")
        if submission.content_hash != content_hash:
            raise DecisionHashMismatchError("Submission content hash changed")

        workspace = session.scalar(
            select(PaperWorkspace)
            .where(PaperWorkspace.id == submission.workspace_id)
            .with_for_update()
        )
        task = session.scalar(
            select(ReviewTask)
            .where(ReviewTask.id == submission.review_task_id)
            .with_for_update()
        )
        paper = session.scalar(
            select(Paper).where(Paper.id == submission.paper_id).with_for_update()
        )
        if workspace is None or task is None or paper is None:
            raise DecisionNotFoundError("Resource not found")
        latest_submission_id = session.scalar(
            select(PaperSubmission.id)
            .where(PaperSubmission.workspace_id == workspace.id)
            .order_by(PaperSubmission.submission_number.desc())
            .limit(1)
        )
        if (
            workspace.paper_id != submission.paper_id
            or task.paper_id != submission.paper_id
            or latest_submission_id != submission.id
            or workspace.state is not WorkspaceState.SUBMITTED
            or task.status is not ReviewTaskState.SUBMITTED
        ):
            raise DecisionStateConflictError("Submission is not awaiting Admin review")
        if action is AdminDecisionAction.APPROVE:
            self._require_verified_source(session, paper)

        decision = AdminDecision(
            submission_id=submission.id,
            paper_id=submission.paper_id,
            content_hash=submission.content_hash,
            action=action,
            reason=normalized_reason,
            decided_by_id=actor_id,
            idempotency_key=key,
        )
        session.add(decision)
        session.flush()

        before = {
            "workspace_state": workspace.state.value,
            "workspace_version": workspace.version,
            "task_status": task.status.value,
            "task_version": task.version,
            "current_published_version_id": (
                str(paper.current_published_version_id)
                if paper.current_published_version_id
                else None
            ),
        }
        published: PublishedPaperVersion | None = None
        if action is AdminDecisionAction.REQUEST_CHANGES:
            workspace.state = WorkspaceState.EDITING
            task.status = ReviewTaskState.CHANGES_REQUESTED
        else:
            latest_version = session.scalar(
                select(func.max(PublishedPaperVersion.version_number)).where(
                    PublishedPaperVersion.paper_id == paper.id
                )
            )
            published = PublishedPaperVersion(
                paper_id=paper.id,
                submission_id=submission.id,
                admin_decision_id=decision.id,
                version_number=int(latest_version or 0) + 1,
                snapshot=submission.snapshot,
                content_hash=submission.content_hash,
                decision_action=AdminDecisionAction.APPROVE,
                published_by_id=actor_id,
            )
            session.add(published)
            session.flush()
            paper.current_published_version_id = published.id
            workspace.state = WorkspaceState.APPROVED
            task.status = ReviewTaskState.APPROVED

        workspace.version += 1
        task.version += 1
        session.add(
            ChangeEvent(
                paper_id=paper.id,
                workspace_id=workspace.id,
                entity_type="admin_decision",
                entity_id=decision.id,
                action=f"submission.{action.value}",
                before_value=before,
                after_value={
                    "decision_id": str(decision.id),
                    "submission_id": str(submission.id),
                    "content_hash": submission.content_hash,
                    "reason": decision.reason,
                    "workspace_state": workspace.state.value,
                    "workspace_version": workspace.version,
                    "task_status": task.status.value,
                    "task_version": task.version,
                    "published_version_id": (
                        str(published.id) if published is not None else None
                    ),
                },
                actor_kind=ChangeActorKind.ADMIN,
                actor_id=actor_id,
                ai_run_id=None,
            )
        )
        session.flush()
        return DecisionResult(decision, published)


__all__ = [
    "DecisionForbiddenError",
    "DecisionHashMismatchError",
    "DecisionIdempotencyConflictError",
    "DecisionNotFoundError",
    "DecisionReasonRequiredError",
    "DecisionResult",
    "DecisionStateConflictError",
    "PendingSubmission",
    "PublishedPaper",
    "PublicationService",
    "SubmissionReview",
]
