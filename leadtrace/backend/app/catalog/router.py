from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.errors import APIError, request_id_for
from app.ai_prefill.models import AiExtractionRun, AiExtractionRunStatus
from app.ai_prefill.schemas import AiExtractionRunResponse, AiPrefillStatusResponse
from app.auth.router import resolve_remote_address
from app.catalog.models import PaperSource
from app.catalog.schemas import (
    CatalogReviewResponse,
    PaperCatalogPage,
    PaperCatalogResponse,
)
from app.config import Settings
from app.database import get_db_session
from app.papers.models import Paper
from app.security.permissions import (
    RouteAccess,
    declare_route_access,
    require_permission,
    require_request_csrf,
)
from app.security.policies import Action, Principal
from app.users.models import User
from app.workspaces.assignment import (
    ActiveAssignmentError,
    AssignmentService,
    InvalidReviewerError,
    PaperNotFoundError,
    PaperSourceUnverifiedError,
    ReviewerNotFoundError,
)
from app.workspaces.models import (
    PaperSectionReview,
    PaperSectionState,
    PaperWorkspace,
    ReviewTask,
)
from app.workspaces.schemas import AssignmentRequest, AssignmentResponse


def _literal_search_pattern(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return f"%{escaped}%"


def _review_summaries(
    session: Session,
    paper_ids: list[UUID],
) -> dict[UUID, CatalogReviewResponse]:
    if not paper_ids:
        return {}
    task_rows = session.execute(
        select(ReviewTask, PaperWorkspace, User)
        .join(PaperWorkspace, PaperWorkspace.review_task_id == ReviewTask.id)
        .join(User, User.id == ReviewTask.assigned_reviewer_id)
        .where(ReviewTask.paper_id.in_(paper_ids))
        .order_by(
            ReviewTask.paper_id,
            ReviewTask.updated_at.desc(),
            ReviewTask.id.desc(),
        )
    ).all()
    latest_by_paper: dict[UUID, tuple[ReviewTask, PaperWorkspace, User]] = {}
    for task, workspace, assignee in task_rows:
        latest_by_paper.setdefault(task.paper_id, (task, workspace, assignee))

    workspace_ids = [workspace.id for _, workspace, _ in latest_by_paper.values()]
    section_counts = (
        {
            workspace_id: (int(total), int(resolved))
            for workspace_id, total, resolved in session.execute(
                select(
                    PaperSectionReview.workspace_id,
                    func.count(PaperSectionReview.id),
                    func.count(PaperSectionReview.id).filter(
                        PaperSectionReview.state != PaperSectionState.PENDING
                    ),
                )
                .where(PaperSectionReview.workspace_id.in_(workspace_ids))
                .group_by(PaperSectionReview.workspace_id)
            ).all()
        }
        if workspace_ids
        else {}
    )

    summaries: dict[UUID, CatalogReviewResponse] = {}
    for paper_id, (task, workspace, assignee) in latest_by_paper.items():
        total, resolved = section_counts.get(workspace.id, (0, 0))
        summaries[paper_id] = CatalogReviewResponse(
            review_task_id=task.id,
            workspace_id=workspace.id,
            assigned_reviewer_id=task.assigned_reviewer_id,
            assignee_display_name=assignee.display_name,
            task_status=task.status,
            workspace_state=workspace.state,
            sections_resolved=resolved,
            sections_total=total,
            submission_state=(
                "not_submitted" if task.status.value == "assigned" else task.status.value
            ),
        )
    return summaries


def _ai_prefill_summaries(
    session: Session,
    paper_ids: list[UUID],
) -> dict[UUID, AiPrefillStatusResponse]:
    if not paper_ids:
        return {}
    workspace_rows = session.scalars(
        select(PaperWorkspace)
        .where(PaperWorkspace.paper_id.in_(paper_ids))
        .order_by(
            PaperWorkspace.paper_id,
            PaperWorkspace.created_at.desc(),
            PaperWorkspace.id.desc(),
        )
    ).all()
    latest_workspace: dict[UUID, PaperWorkspace] = {}
    for workspace in workspace_rows:
        latest_workspace.setdefault(workspace.paper_id, workspace)
    workspace_ids = [workspace.id for workspace in latest_workspace.values()]
    run_rows = (
        session.scalars(
            select(AiExtractionRun)
            .where(AiExtractionRun.workspace_id.in_(workspace_ids))
            .order_by(
                AiExtractionRun.workspace_id,
                AiExtractionRun.queued_at.desc(),
                AiExtractionRun.id.desc(),
            )
        ).all()
        if workspace_ids
        else []
    )
    latest_run: dict[UUID, AiExtractionRun] = {}
    for run in run_rows:
        latest_run.setdefault(run.workspace_id, run)

    summaries: dict[UUID, AiPrefillStatusResponse] = {}
    for paper_id in paper_ids:
        workspace = latest_workspace.get(paper_id)
        if workspace is None:
            summaries[paper_id] = AiPrefillStatusResponse(
                run=None,
                can_start=False,
                blocked_reason="Assign a Reviewer before AI prefill",
            )
            continue
        run = latest_run.get(workspace.id)
        if run is not None and run.status in {
            AiExtractionRunStatus.QUEUED,
            AiExtractionRunStatus.RUNNING,
        }:
            blocked_reason = "AI prefill is already queued or running"
        elif workspace.state.value != "editing":
            blocked_reason = "Workspace is not editable"
        elif workspace.version != 1:
            blocked_reason = "Workspace has already been modified"
        else:
            blocked_reason = None
        summaries[paper_id] = AiPrefillStatusResponse(
            run=AiExtractionRunResponse.from_model(run) if run else None,
            can_start=blocked_reason is None,
            blocked_reason=blocked_reason,
        )
    return summaries


def create_catalog_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v2/admin/papers", tags=["paper catalog"])
    require_catalog_management = require_permission(Action.MANAGE_PAPER_CATALOG)
    assignment_service = AssignmentService()

    @router.get("", response_model=PaperCatalogPage)
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_PAPER_CATALOG)
    def list_papers(
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        search: str | None = Query(default=None, min_length=1, max_length=200),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_catalog_management),
    ) -> PaperCatalogPage:
        del principal
        with session.begin():
            filters = []
            if search is not None and search.strip():
                pattern = _literal_search_pattern(search.strip())
                filters.append(or_(
                    Paper.paper_key.ilike(pattern, escape="\\"),
                    Paper.title.ilike(pattern, escape="\\"),
                    Paper.journal.ilike(pattern, escape="\\"),
                    Paper.doi.ilike(pattern, escape="\\"),
                ))
            total_query = select(func.count()).select_from(Paper)
            rows_query = (
                select(Paper, PaperSource)
                .join(PaperSource, PaperSource.id == Paper.source_id)
            )
            if filters:
                total_query = total_query.where(*filters)
                rows_query = rows_query.where(*filters)
            total = int(session.scalar(total_query) or 0)
            rows = session.execute(
                rows_query
                .order_by(Paper.paper_key, Paper.id)
                .limit(limit)
                .offset(offset)
            ).all()
            reviews = _review_summaries(session, [paper.id for paper, _ in rows])
            ai_prefill = _ai_prefill_summaries(
                session, [paper.id for paper, _ in rows]
            )
        return PaperCatalogPage(
            items=[
                PaperCatalogResponse.from_models(
                    paper,
                    source,
                    reviews.get(paper.id),
                    ai_prefill.get(paper.id),
                )
                for paper, source in rows
            ],
            total=total,
            limit=limit,
            offset=offset,
        )

    @router.get("/{paper_id}", response_model=PaperCatalogResponse)
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_PAPER_CATALOG)
    def get_paper(
        paper_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_catalog_management),
    ) -> PaperCatalogResponse:
        del principal
        with session.begin():
            row = session.execute(
                select(Paper, PaperSource)
                .join(PaperSource, PaperSource.id == Paper.source_id)
                .where(Paper.id == paper_id)
            ).one_or_none()
            reviews = _review_summaries(
                session,
                [row[0].id] if row is not None else [],
            )
            ai_prefill = _ai_prefill_summaries(
                session,
                [row[0].id] if row is not None else [],
            )
        if row is None:
            raise HTTPException(status_code=404, detail="Resource not found")
        return PaperCatalogResponse.from_models(
            *row,
            reviews.get(row[0].id),
            ai_prefill.get(row[0].id),
        )

    @router.post(
        "/{paper_id}/assign",
        response_model=AssignmentResponse,
        status_code=201,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_PAPER_CATALOG)
    def assign_paper(
        paper_id: UUID,
        payload: AssignmentRequest,
        request: Request,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_catalog_management),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> AssignmentResponse:
        try:
            with session.begin():
                require_request_csrf(
                    principal,
                    csrf_token,
                    settings.session_secret.get_secret_value(),
                )
                result = assignment_service.assign(
                    session,
                    paper_id=paper_id,
                    reviewer_id=payload.reviewer_id,
                    admin_id=principal.user_id,
                    request_id=request_id_for(request),
                    ip_address=resolve_remote_address(request, settings),
                )
        except PaperNotFoundError as error:
            raise HTTPException(status_code=404, detail="Resource not found") from error
        except ReviewerNotFoundError as error:
            raise APIError(
                404,
                "REVIEWER_NOT_FOUND",
                "Reviewer not found",
            ) from error
        except InvalidReviewerError as error:
            raise APIError(422, "INVALID_REVIEWER", str(error)) from error
        except ActiveAssignmentError as error:
            raise APIError(409, "ACTIVE_ASSIGNMENT_EXISTS", str(error)) from error
        except PaperSourceUnverifiedError as error:
            raise APIError(409, "PAPER_SOURCE_UNVERIFIED", str(error)) from error
        return AssignmentResponse.from_models(
            result.task,
            result.workspace,
            result.sections,
        )

    return router


__all__ = ["create_catalog_router"]
