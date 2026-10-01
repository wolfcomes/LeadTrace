from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.workspaces.history import lock_workspace
from app.workspaces.models import (
    ChangeActorKind,
    ChangeEvent,
    PaperSubmission,
    ReviewTaskState,
    WorkspaceState,
)
from app.workspaces.snapshot import build_paper_snapshot, canonical_snapshot_hash
from app.workspaces.validation import (
    SubmissionBlocker,
    SubmissionValidation,
    validate_submission,
)


class SubmissionValidationError(ValueError):
    def __init__(self, blockers: list[SubmissionBlocker]) -> None:
        super().__init__("Paper Workspace is not ready for submission")
        self.blockers = blockers


class SubmissionNotFoundError(LookupError):
    pass


class SubmissionVersionConflictError(RuntimeError):
    def __init__(self, expected_version: int, current_version: int) -> None:
        super().__init__("Workspace version changed")
        self.expected_version = expected_version
        self.current_version = current_version


class SubmissionReadOnlyError(RuntimeError):
    def __init__(self, state: WorkspaceState, current_version: int) -> None:
        super().__init__("Workspace is read-only")
        self.state = state
        self.current_version = current_version


class SubmissionService:
    def validate(self, session: Session, *, workspace_id: UUID) -> SubmissionValidation:
        return validate_submission(session, workspace_id)

    def submit(
        self,
        session: Session,
        *,
        workspace_id: UUID,
        reviewer_id: UUID,
        expected_workspace_version: int,
        idempotency_key: str,
        reviewer_note: str | None,
    ) -> PaperSubmission:
        key = idempotency_key.strip()
        if not key:
            raise ValueError("idempotency_key is required")
        if len(key) > 255:
            raise ValueError("idempotency_key must not exceed 255 characters")
        context = lock_workspace(session, workspace_id)
        if context is None:
            raise SubmissionNotFoundError("Resource not found")
        if context.task.assigned_reviewer_id != reviewer_id:
            raise SubmissionNotFoundError("Resource not found")

        existing = session.scalar(
            select(PaperSubmission).where(
                PaperSubmission.workspace_id == workspace_id,
                PaperSubmission.idempotency_key == key,
            )
        )
        if existing is not None:
            return existing
        if context.workspace.state is not WorkspaceState.EDITING:
            raise SubmissionReadOnlyError(
                context.workspace.state, context.workspace.version
            )
        if context.workspace.version != expected_workspace_version:
            raise SubmissionVersionConflictError(
                expected_workspace_version, context.workspace.version
            )

        validation = validate_submission(session, workspace_id)
        if validation.blockers:
            raise SubmissionValidationError(validation.blockers)

        latest_number = session.scalar(
            select(func.max(PaperSubmission.submission_number)).where(
                PaperSubmission.workspace_id == workspace_id
            )
        )
        before = {
            "workspace_state": context.workspace.state.value,
            "task_status": context.task.status.value,
            "workspace_version": context.workspace.version,
        }
        context.workspace.state = WorkspaceState.SUBMITTED
        context.workspace.version += 1
        context.task.status = ReviewTaskState.SUBMITTED
        context.task.version += 1
        snapshot = build_paper_snapshot(session, workspace_id)
        from app.workspaces.review_progress import get_progress
        progress = get_progress(session, workspace_id, reviewer_id)
        if progress['tracking_started']:
            snapshot['review_progress'] = progress
            for section in snapshot['sections']:
                if section['state'] == 'pending' and any(x['section_key'] == section['section_key'] and x['complete'] for x in progress['sections']):
                    section['state'] = 'completed'
        content_hash = canonical_snapshot_hash(snapshot)
        submission = PaperSubmission(
            paper_id=context.workspace.paper_id,
            workspace_id=context.workspace.id,
            review_task_id=context.task.id,
            submission_number=int(latest_number or 0) + 1,
            idempotency_key=key,
            snapshot=snapshot,
            content_hash=content_hash,
            workspace_version=context.workspace.version,
            submitted_by_id=reviewer_id,
            reviewer_note=reviewer_note.strip() if reviewer_note else None,
        )
        session.add(submission)
        session.flush()
        session.add(
            ChangeEvent(
                paper_id=context.workspace.paper_id,
                workspace_id=context.workspace.id,
                entity_type="paper_submission",
                entity_id=submission.id,
                action="workspace.submit",
                before_value=before,
                after_value={
                    "submission_id": str(submission.id),
                    "submission_number": submission.submission_number,
                    "content_hash": submission.content_hash,
                    "workspace_state": context.workspace.state.value,
                    "task_status": context.task.status.value,
                    "workspace_version": context.workspace.version,
                },
                actor_kind=ChangeActorKind.REVIEWER,
                actor_id=reviewer_id,
                ai_run_id=None,
            )
        )
        session.flush()
        return submission


__all__ = [
    "SubmissionNotFoundError",
    "SubmissionReadOnlyError",
    "SubmissionService",
    "SubmissionValidationError",
    "SubmissionVersionConflictError",
]
