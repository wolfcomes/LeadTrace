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


class SubmissionIdempotencyConflictError(RuntimeError):
    pass


# Only scientific review incompleteness may be waived. New validator failures
# remain blocking until explicitly assessed for this exceptional workflow.
PROBLEM_REPORT_WAIVABLE_CODES = frozenset({
    'SECTION_PENDING', 'RECORD_NOT_VIEWED', 'COMPOUND_HIGHLIGHT_NOT_REVIEWED',
    'STRUCTURE_NOT_CONFIRMED', 'LINEAGE_ROOT_REQUIRED', 'LINEAGE_TERMINAL_REQUIRED',
    'EDGE_NOT_DISPOSITIONED',
})


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
        problem_reason: str | None = None,
    ) -> PaperSubmission:
        if problem_reason is not None:
            problem_reason = problem_reason.strip()
            if not problem_reason or len(problem_reason) > 10_000:
                raise ValueError('A problem explanation of 1 to 10000 characters is required')
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
            existing_report = existing.snapshot.get('problem_report')
            if (bool(existing_report) != (problem_reason is not None)
                    or (existing_report and existing_report.get('reason') != problem_reason)):
                raise SubmissionIdempotencyConflictError('Idempotency key was used for a different submission')
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
        blocking = validation.blockers if problem_reason is None else [
            item for item in validation.blockers if item.code not in PROBLEM_REPORT_WAIVABLE_CODES
        ]
        if blocking:
            raise SubmissionValidationError(blocking)

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
        if progress['tracking_started'] or problem_reason is not None:
            snapshot['review_progress'] = progress
            for section in snapshot['sections']:
                if problem_reason is None and section['state'] == 'pending' and any(x['section_key'] == section['section_key'] and x['complete'] for x in progress['sections']):
                    section['state'] = 'completed'
        if problem_reason is not None:
            snapshot['problem_report'] = {
                'reason': problem_reason,
                'blockers': [{
                    'code': item.code, 'message': item.message,
                    'entity_type': item.entity_type,
                    'entity_id': str(item.entity_id) if item.entity_id else None,
                    'section_key': item.section_key.value if item.section_key else None,
                } for item in validation.blockers],
            }
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
