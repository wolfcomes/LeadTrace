from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.activities.models import Activity
from app.activities.schemas import (
    ActivityCreateRequest,
    ActivityDeleteResponse,
    ActivityListResponse,
    ActivityMutationResponse,
    ActivityReorderRequest,
    ActivityResponse,
    ActivityUpdateRequest,
    WorkspaceVersionRequest,
)
from app.activities.service import (
    ActivityOrderError,
    ActivityService,
    ActivityValidationError,
)
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
from app.workspaces.service import (
    WorkspaceForbiddenError,
    WorkspaceNotFoundError,
    WorkspaceReadOnlyError,
    WorkspaceVersionConflictError,
)


def _activity_response(row: Activity) -> ActivityResponse:
    return ActivityResponse(
        id=row.id,
        paper_id=row.paper_id,
        workspace_id=row.workspace_id,
        compound_id=row.compound_id,
        evidence_id=row.evidence_id,
        assay_name=row.assay_name,
        metric=row.metric,
        operator=row.operator,
        value=row.value,
        unit=row.unit,
        context=row.context,
        sort_order=row.sort_order,
    )


def _workspace_error(error: Exception) -> APIError | HTTPException:
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


def _domain_error(error: Exception) -> APIError:
    if isinstance(error, ActivityOrderError):
        return APIError(422, "ACTIVITY_ORDER_INVALID", str(error))
    if isinstance(error, ActivityValidationError):
        return APIError(422, "ACTIVITY_INVALID", str(error))
    if isinstance(error, IntegrityError):
        return APIError(
            409,
            "ACTIVITY_CONFLICT",
            "Activity conflicts with an existing record",
        )
    raise error


_WORKSPACE_ERRORS = (
    WorkspaceForbiddenError,
    WorkspaceNotFoundError,
    WorkspaceReadOnlyError,
    WorkspaceVersionConflictError,
)
_DOMAIN_ERRORS = (ActivityValidationError, IntegrityError)


def create_activities_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["activities"])
    service = ActivityService()
    secret = settings.session_secret.get_secret_value()

    @router.get(
        "/api/v2/compounds/{compound_id}/activities",
        response_model=ActivityListResponse,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.READ_DRAFT)
    def list_activities(
        compound_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> ActivityListResponse:
        try:
            with session.begin():
                result = service.list_activities(
                    session, compound_id=compound_id, actor=principal
                )
                items = [_activity_response(row) for row in result.activities]
                return ActivityListResponse(
                    compound_id=compound_id,
                    workspace_version=result.workspace.version,
                    items=items,
                    total=len(items),
                )
        except _WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error

    @router.post(
        "/api/v2/compounds/{compound_id}/activities",
        response_model=ActivityMutationResponse,
        status_code=201,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def create_activity(
        compound_id: UUID,
        payload: ActivityCreateRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> ActivityMutationResponse:
        require_request_csrf(principal, csrf_token, secret)
        try:
            with session.begin():
                result = service.create_activity(
                    session,
                    compound_id=compound_id,
                    expected_version=payload.expected_workspace_version,
                    actor=principal,
                    evidence_id=payload.evidence_id,
                    assay_name=payload.assay_name,
                    metric=payload.metric,
                    operator=payload.operator,
                    value=payload.value,
                    unit=payload.unit,
                    context_value=payload.context,
                )
                return ActivityMutationResponse(
                    activity=_activity_response(result.activity),
                    workspace_version=result.workspace.version,
                )
        except _WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error
        except _DOMAIN_ERRORS as error:
            raise _domain_error(error) from error

    @router.patch(
        "/api/v2/activities/{activity_id}",
        response_model=ActivityMutationResponse,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def update_activity(
        activity_id: UUID,
        payload: ActivityUpdateRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> ActivityMutationResponse:
        require_request_csrf(principal, csrf_token, secret)
        try:
            with session.begin():
                result = service.update_activity(
                    session,
                    activity_id=activity_id,
                    expected_version=payload.expected_workspace_version,
                    actor=principal,
                    updates=payload.updates(),
                )
                return ActivityMutationResponse(
                    activity=_activity_response(result.activity),
                    workspace_version=result.workspace.version,
                )
        except _WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error
        except _DOMAIN_ERRORS as error:
            raise _domain_error(error) from error

    @router.put(
        "/api/v2/compounds/{compound_id}/activities/order",
        response_model=ActivityListResponse,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def reorder_activities(
        compound_id: UUID,
        payload: ActivityReorderRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> ActivityListResponse:
        require_request_csrf(principal, csrf_token, secret)
        try:
            with session.begin():
                result = service.reorder_activities(
                    session,
                    compound_id=compound_id,
                    expected_version=payload.expected_workspace_version,
                    actor=principal,
                    activity_ids=payload.activity_ids,
                )
                items = [_activity_response(row) for row in result.activities]
                return ActivityListResponse(
                    compound_id=compound_id,
                    workspace_version=result.workspace.version,
                    items=items,
                    total=len(items),
                )
        except _WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error
        except _DOMAIN_ERRORS as error:
            raise _domain_error(error) from error

    @router.delete(
        "/api/v2/activities/{activity_id}",
        response_model=ActivityDeleteResponse,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def delete_activity(
        activity_id: UUID,
        payload: WorkspaceVersionRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> ActivityDeleteResponse:
        require_request_csrf(principal, csrf_token, secret)
        try:
            with session.begin():
                workspace = service.delete_activity(
                    session,
                    activity_id=activity_id,
                    expected_version=payload.expected_workspace_version,
                    actor=principal,
                )
                return ActivityDeleteResponse(
                    deleted_activity_id=activity_id,
                    workspace_version=workspace.version,
                )
        except _WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error
        except _DOMAIN_ERRORS as error:
            raise _domain_error(error) from error

    return router


__all__ = ["create_activities_router"]
