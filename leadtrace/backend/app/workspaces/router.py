from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import APIError
from app.config import Settings
from app.database import get_db_session
from app.security.permissions import (
    RouteAccess,
    declare_route_access,
    get_authenticated_principal,
    require_request_csrf,
)
from app.security.policies import Action, Principal
from app.workspaces.history import MutationChange
from app.workspaces.models import PaperSection, PaperSectionReview
from app.workspaces.schemas import (
    BibliographyResponse,
    BibliographyUpdateRequest,
    PaperSectionReviewResponse,
    ReviewTaskListResponse,
    ReviewTaskResponse,
    SectionUpdateRequest,
    WorkspaceResponse,
    WorkspaceSourceResponse,
)
from app.workspaces.service import (
    ReviewTaskAggregate,
    WorkspaceAggregate,
    WorkspaceForbiddenError,
    WorkspaceNotFoundError,
    WorkspaceReadOnlyError,
    WorkspaceService,
    WorkspaceVersionConflictError,
)


def _task_response(aggregate: ReviewTaskAggregate) -> ReviewTaskResponse:
    return ReviewTaskResponse(
        review_task_id=aggregate.task.id,
        workspace_id=aggregate.workspace.id,
        paper_id=aggregate.paper.id,
        paper_key=aggregate.paper.paper_key,
        title=aggregate.paper.title,
        task_status=aggregate.task.status,
        task_version=aggregate.task.version,
        workspace_state=aggregate.workspace.state,
        workspace_version=aggregate.workspace.version,
    )


def _workspace_response(aggregate: WorkspaceAggregate) -> WorkspaceResponse:
    return WorkspaceResponse(
        id=aggregate.workspace.id,
        review_task_id=aggregate.task.id,
        assigned_reviewer_id=aggregate.task.assigned_reviewer_id,
        state=aggregate.workspace.state,
        version=aggregate.workspace.version,
        task_status=aggregate.task.status,
        bibliography=BibliographyResponse(
            paper_id=aggregate.paper.id,
            paper_key=aggregate.paper.paper_key,
            title=aggregate.paper.title,
            journal=aggregate.paper.journal,
            publication_year=aggregate.paper.publication_year,
            volume=aggregate.paper.volume,
            issue=aggregate.paper.issue,
            doi=aggregate.paper.doi,
        ),
        source=WorkspaceSourceResponse(
            asset_id=aggregate.source.asset_id,
            source_root_key=aggregate.source.source_root_key,
            source_key=aggregate.source.source_key,
        ),
        sections=[
            PaperSectionReviewResponse.from_model(section)
            for section in aggregate.sections
        ],
    )


def _translate_workspace_error(error: Exception) -> APIError | HTTPException:
    if isinstance(error, WorkspaceNotFoundError):
        return APIError(404, "RESOURCE_NOT_FOUND", "Resource not found")
    if isinstance(error, WorkspaceForbiddenError):
        return HTTPException(status_code=403, detail="Permission denied")
    if isinstance(error, WorkspaceVersionConflictError):
        return APIError(
            409,
            "WORKSPACE_VERSION_CONFLICT",
            "Workspace version changed",
            details={
                "expected_workspace_version": error.expected_version,
                "current_workspace_version": error.current_version,
            },
        )
    if isinstance(error, WorkspaceReadOnlyError):
        return APIError(
            409,
            "WORKSPACE_READ_ONLY",
            "Workspace is read-only",
            details={
                "workspace_state": error.state.value,
                "current_workspace_version": error.current_version,
            },
        )
    raise error


def create_workspaces_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["paper workspaces"])
    service = WorkspaceService()
    session_secret = settings.session_secret.get_secret_value()

    @router.get("/api/v2/review/tasks", response_model=ReviewTaskListResponse)
    @declare_route_access(RouteAccess.PERMISSION, Action.READ_DRAFT)
    def list_review_tasks(
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> ReviewTaskListResponse:
        try:
            with session.begin():
                tasks = service.list_review_tasks(session, actor=principal)
        except (WorkspaceForbiddenError, WorkspaceNotFoundError) as error:
            raise _translate_workspace_error(error) from error
        items = [_task_response(task) for task in tasks]
        return ReviewTaskListResponse(items=items, total=len(items))

    @router.get(
        "/api/v2/workspaces/{workspace_id}",
        response_model=WorkspaceResponse,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.READ_DRAFT)
    def get_workspace(
        workspace_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> WorkspaceResponse:
        try:
            with session.begin():
                aggregate = service.get_workspace(
                    session,
                    workspace_id=workspace_id,
                    actor=principal,
                )
                return _workspace_response(aggregate)
        except (WorkspaceForbiddenError, WorkspaceNotFoundError) as error:
            raise _translate_workspace_error(error) from error

    @router.patch(
        "/api/v2/workspaces/{workspace_id}/bibliography",
        response_model=WorkspaceResponse,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def update_bibliography(
        workspace_id: UUID,
        payload: BibliographyUpdateRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> WorkspaceResponse:
        require_request_csrf(principal, csrf_token, session_secret)
        updates = payload.updates()

        def mutation(context) -> MutationChange:
            before = {field: getattr(context.paper, field) for field in updates}
            for field, value in updates.items():
                setattr(context.paper, field, value)
            after = {field: getattr(context.paper, field) for field in updates}
            return MutationChange(
                entity_type="paper",
                entity_id=context.paper.id,
                action="bibliography.update",
                before_value=before,
                after_value=after,
            )

        try:
            with session.begin():
                service.mutate(
                    session,
                    workspace_id=workspace_id,
                    expected_version=payload.expected_workspace_version,
                    actor=principal,
                    mutation=mutation,
                )
                aggregate = service.get_workspace(
                    session,
                    workspace_id=workspace_id,
                    actor=principal,
                )
                return _workspace_response(aggregate)
        except (
            WorkspaceForbiddenError,
            WorkspaceNotFoundError,
            WorkspaceReadOnlyError,
            WorkspaceVersionConflictError,
        ) as error:
            raise _translate_workspace_error(error) from error

    @router.put(
        "/api/v2/workspaces/{workspace_id}/sections/{section}",
        response_model=WorkspaceResponse,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def update_section(
        workspace_id: UUID,
        section: PaperSection,
        payload: SectionUpdateRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> WorkspaceResponse:
        require_request_csrf(principal, csrf_token, session_secret)

        def mutation(context) -> MutationChange:
            section_row = session.scalar(
                select(PaperSectionReview)
                .where(
                    PaperSectionReview.workspace_id == context.workspace.id,
                    PaperSectionReview.section_key == section,
                )
                .with_for_update()
            )
            if section_row is None:
                raise WorkspaceNotFoundError("Resource not found")
            before = {
                "section_key": section_row.section_key.value,
                "state": section_row.state.value,
                "note": section_row.note,
            }
            section_row.state = payload.state
            section_row.note = payload.note
            after = {
                "section_key": section_row.section_key.value,
                "state": section_row.state.value,
                "note": section_row.note,
            }
            return MutationChange(
                entity_type="paper_section_review",
                entity_id=section_row.id,
                action="section.update",
                before_value=before,
                after_value=after,
            )

        try:
            with session.begin():
                service.mutate(
                    session,
                    workspace_id=workspace_id,
                    expected_version=payload.expected_workspace_version,
                    actor=principal,
                    mutation=mutation,
                )
                aggregate = service.get_workspace(
                    session,
                    workspace_id=workspace_id,
                    actor=principal,
                )
                return _workspace_response(aggregate)
        except (
            WorkspaceForbiddenError,
            WorkspaceNotFoundError,
            WorkspaceReadOnlyError,
            WorkspaceVersionConflictError,
        ) as error:
            raise _translate_workspace_error(error) from error

    return router


__all__ = ["create_workspaces_router"]
