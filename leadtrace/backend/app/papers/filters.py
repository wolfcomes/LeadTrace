"""Shared catalog filters, applied before pagination in every Admin directory."""
from dataclasses import dataclass
from typing import Literal

from fastapi import Query
from sqlalchemy import String, case, cast, func, select, union_all

from app.ai_prefill.models import AiExtractionRun
from app.ai_tasks.models import AiTask
from app.api.errors import APIError
from app.papers.models import Paper
from app.workspaces.models import PaperWorkspace, ReviewTask, ReviewTaskState, WorkspaceState

AssignmentStatus = Literal['assigned', 'unassigned']
PrefillStatus = Literal['not_started', 'queued', 'running', 'succeeded', 'failed', 'superseded']


def current_prefill_status():
    """Latest prefill event of the current workspace; reviews/revisions are separate.

    Modern generation succeeds only after delivery. Legacy extraction rows are
    also included, since their apply transaction can be the latest status event.
    """
    workspaces = select(
        PaperWorkspace.id, PaperWorkspace.paper_id,
        func.row_number().over(partition_by=PaperWorkspace.paper_id,
            order_by=(PaperWorkspace.created_at.desc(), PaperWorkspace.id.desc())).label('rank'),
    ).join(ReviewTask, ReviewTask.id == PaperWorkspace.review_task_id).where(
        PaperWorkspace.state != WorkspaceState.ARCHIVED,
        ReviewTask.status != ReviewTaskState.ARCHIVED,
    ).subquery()
    modern_status = case(
        (AiTask.delivery_state == 'applied', 'succeeded'),
        (AiTask.state == 'queued', 'queued'),
        (AiTask.state.in_(['preparing', 'running', 'validating', 'cancel_requested']), 'running'),
        (AiTask.state.in_(['superseded', 'cancelled']), 'superseded'),
        else_='failed',
    )
    events = union_all(
        select(AiExtractionRun.workspace_id.label('workspace_id'),
            cast(AiExtractionRun.status, String).label('status'),
            AiExtractionRun.queued_at.label('occurred_at'), AiExtractionRun.id.label('id')),
        select(AiTask.workspace_id, modern_status, AiTask.created_at, AiTask.id)
            .where(AiTask.action == 'prefill'),
    ).subquery()
    status = select(events.c.status).join(workspaces, workspaces.c.id == events.c.workspace_id).where(
        workspaces.c.rank == 1, workspaces.c.paper_id == Paper.id,
    ).order_by(events.c.occurred_at.desc(), events.c.id.desc()).limit(1).correlate(Paper).scalar_subquery()
    return func.coalesce(status, 'not_started')


@dataclass(frozen=True)
class PaperFilters:
    journal: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    volume: str | None = None
    issue: str | None = None
    assignment_status: AssignmentStatus | None = None
    prefill_status: PrefillStatus | None = None

    @property
    def active(self) -> bool:
        return any(value is not None for value in vars(self).values())

    def predicates(self):
        conditions = [Paper.removed_at.is_(None)]
        for field in ('journal', 'volume', 'issue'):
            value = getattr(self, field)
            if value is not None:
                conditions.append(getattr(Paper, field) == value)
        if self.year_from is not None:
            conditions.append(Paper.publication_year >= self.year_from)
        if self.year_to is not None:
            conditions.append(Paper.publication_year <= self.year_to)
        if self.assignment_status is not None:
            assignee = select(ReviewTask.assigned_reviewer_id).join(
                PaperWorkspace, PaperWorkspace.review_task_id == ReviewTask.id,
            ).where(ReviewTask.paper_id == Paper.id,
                ReviewTask.status != ReviewTaskState.ARCHIVED,
                PaperWorkspace.state != WorkspaceState.ARCHIVED,
            ).order_by(ReviewTask.updated_at.desc(), ReviewTask.id.desc()).limit(1).correlate(Paper).scalar_subquery()
            conditions.append(assignee.is_not(None) if self.assignment_status == 'assigned' else assignee.is_(None))
        if self.prefill_status is not None:
            conditions.append(current_prefill_status() == self.prefill_status)
        return conditions

    def paper_ids(self):
        return select(Paper.id).where(*self.predicates())


def paper_filters(
    journal: str | None = Query(default=None, max_length=255),
    year_from: int | None = Query(default=None, ge=1000, le=9999),
    year_to: int | None = Query(default=None, ge=1000, le=9999),
    volume: str | None = Query(default=None, max_length=64),
    issue: str | None = Query(default=None, max_length=64),
    assignment_status: AssignmentStatus | None = Query(default=None),
    prefill_status: PrefillStatus | None = Query(default=None),
) -> PaperFilters:
    if year_from is not None and year_to is not None and year_from > year_to:
        raise APIError(422, 'INVALID_YEAR_RANGE', 'Start year must not exceed end year')
    return PaperFilters(
        journal=(journal.strip() or None) if journal is not None else None,
        year_from=year_from, year_to=year_to,
        volume=(volume.strip() or None) if volume is not None else None,
        issue=(issue.strip() or None) if issue is not None else None,
        assignment_status=assignment_status, prefill_status=prefill_status,
    )
