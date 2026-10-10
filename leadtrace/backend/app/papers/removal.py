"""Remove article visibility atomically; retain scientific rows and immutable history."""
from datetime import UTC, datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from app.api.errors import APIError
from app.ai_tasks.models import AiTask
from app.ai_tasks.service import OPEN
from app.ai_prefill.models import AiExtractionRun, AiExtractionRunStatus
from app.audit.service import AuditService, canonical_content_hash
from app.papers.models import Paper
from app.workspaces.models import PaperWorkspace, ReviewTask, ReviewTaskState


class RemovePaperRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reason: str = Field(min_length=1, max_length=2000)
    confirm_paper_key: str = Field(min_length=1, max_length=128)
    expected_workspace_id: UUID | None
    expected_workspace_version: int | None = Field(ge=1)
    expected_task_version: int | None = Field(ge=1)

    @field_validator('reason')
    @classmethod
    def nonempty_reason(cls, value):
        if not value.strip():
            raise ValueError('A removal reason is required')
        return value.strip()


def remove_paper(session, *, paper_id, actor_id, payload, request_id, ip_address):
    # Same lock order as edits/enqueue/delivery: paper, workspace, task, jobs.
    paper = session.scalar(select(Paper).where(Paper.id == paper_id).with_for_update().execution_options(populate_existing=True))
    if paper is None or paper.removed_at is not None:
        raise APIError(404, 'RESOURCE_NOT_FOUND', 'Resource not found')
    # Legacy delivery locks its run before the workspace. Reject its committed
    # active state without waiting for that lock; queue creation now takes our
    # paper lock, so no new run can appear after this check. Terminal states do
    # not transition back to active in the legacy API.
    if session.scalar(select(AiExtractionRun.id).where(AiExtractionRun.paper_id == paper_id,
            AiExtractionRun.status.in_([AiExtractionRunStatus.QUEUED, AiExtractionRunStatus.RUNNING])).limit(1)):
        raise APIError(409, 'PAPER_TASK_ACTIVE', 'Wait for or cancel active AI tasks before removing the article')
    workspace = session.scalar(select(PaperWorkspace).join(ReviewTask, ReviewTask.id == PaperWorkspace.review_task_id)
        .where(PaperWorkspace.paper_id == paper_id, ReviewTask.status.notin_(['archived', 'approved']))
        .with_for_update(of=PaperWorkspace).execution_options(populate_existing=True))
    task = session.scalar(select(ReviewTask).where(ReviewTask.id == workspace.review_task_id)
        .with_for_update().execution_options(populate_existing=True)) if workspace else None
    identity = (workspace.id, workspace.version, task.version) if workspace else (None, None, None)
    if payload.confirm_paper_key != paper.paper_key or identity != (
            payload.expected_workspace_id, payload.expected_workspace_version, payload.expected_task_version):
        raise APIError(409, 'PAPER_VERSION_CONFLICT', 'Article changed; refresh management before removing')
    jobs = list(session.scalars(select(AiTask).where(AiTask.paper_id == paper_id).with_for_update()))
    legacy = list(session.scalars(select(AiExtractionRun).where(AiExtractionRun.paper_id == paper_id).with_for_update()))
    if any(job.state in OPEN for job in jobs) or any(run.status in {AiExtractionRunStatus.QUEUED, AiExtractionRunStatus.RUNNING} for run in legacy):
        raise APIError(409, 'PAPER_TASK_ACTIVE', 'Wait for or cancel active AI tasks before removing the article')
    before = {'removed_at': None, 'task': None if task is None else {
        'id': str(task.id), 'status': task.status.value, 'version': task.version,
        'assigned_reviewer_id': str(task.assigned_reviewer_id) if task.assigned_reviewer_id else None}}
    paper.removed_at = datetime.now(UTC)
    paper.removed_by_id = actor_id
    paper.removal_reason = payload.reason
    if task is not None:
        task.status = ReviewTaskState.ARCHIVED
        task.version += 1
    after = {'removed_at': paper.removed_at.isoformat(), 'removed_by_id': str(actor_id),
             'task_status': task.status.value if task else None, 'task_version': task.version if task else None}
    event = AuditService().append_event(session, actor_id=actor_id, action='paper.remove', target_type='paper',
        target_id=paper_id, paper_id=paper_id, changeset_id=None, release_id=None,
        ip_address=ip_address, request_id=request_id, result='success', reason=payload.reason,
        before_hash=canonical_content_hash(before), after_hash=canonical_content_hash(after),
        details={'before': before, 'after': after, 'workspace_id': str(workspace.id) if workspace else None})
    session.flush()
    return {'paper_id': paper_id, 'removed_at': paper.removed_at, 'audit_event_id': event.id}
