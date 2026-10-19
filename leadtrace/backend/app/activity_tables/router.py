from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.activities.router import _workspace_error, _WORKSPACE_ERRORS
from app.activity_tables.schemas import (TableWrite, TableVersion, TableConfirm, TableListResponse,
                                         TableMutationResponse, TableDeleteResponse)
from app.activity_tables.service import ActivityTableService
from app.api.errors import APIError
from app.database import get_db_session
from app.security.permissions import RouteAccess, declare_route_access, get_authenticated_principal, require_request_csrf
from app.security.policies import Action, Principal


def create_activity_tables_router(settings):
    router = APIRouter(tags=['activity-tables'])
    service = ActivityTableService()
    secret = settings.session_secret.get_secret_value()

    @router.get('/api/v2/workspaces/{workspace_id}/activity-tables', response_model=TableListResponse)
    @declare_route_access(RouteAccess.PERMISSION, Action.READ_DRAFT)
    def listing(workspace_id: UUID, session: Session = Depends(get_db_session), principal: Principal = Depends(get_authenticated_principal)):
        try:
            with session.begin():
                return service.listing(session, workspace_id, principal)
        except _WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error

    def run(session, principal, csrf_token, **kwargs):
        require_request_csrf(principal, csrf_token, secret)
        try:
            with session.begin():
                return service.mutate(session, actor=principal, **kwargs)
        except _WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error
        except IntegrityError as error:
            raise APIError(409, 'ACTIVITY_TABLE_CONFLICT', 'Activity table conflicts with the current Workspace') from error

    @router.put('/api/v2/workspaces/{workspace_id}/activity-tables/{table_id}', response_model=TableMutationResponse)
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def save(workspace_id: UUID, table_id: UUID, payload: TableWrite, session: Session = Depends(get_db_session), principal: Principal = Depends(get_authenticated_principal), csrf_token: str | None = Header(default=None, alias='X-CSRF-Token')):
        return run(session, principal, csrf_token, workspace_id=workspace_id, table_id=table_id,
                   version=payload.expected_workspace_version, values=payload.model_dump(mode='json', exclude={'expected_workspace_version'}))

    @router.delete('/api/v2/workspaces/{workspace_id}/activity-tables/{table_id}', response_model=TableDeleteResponse)
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def delete(workspace_id: UUID, table_id: UUID, payload: TableVersion, session: Session = Depends(get_db_session), principal: Principal = Depends(get_authenticated_principal), csrf_token: str | None = Header(default=None, alias='X-CSRF-Token')):
        return run(session, principal, csrf_token, workspace_id=workspace_id, table_id=table_id, version=payload.expected_workspace_version, delete=True)

    @router.post('/api/v2/workspaces/{workspace_id}/activity-tables/{table_id}/confirm', response_model=TableMutationResponse)
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def confirm(workspace_id: UUID, table_id: UUID, payload: TableConfirm, session: Session = Depends(get_db_session), principal: Principal = Depends(get_authenticated_principal), csrf_token: str | None = Header(default=None, alias='X-CSRF-Token')):
        return run(session, principal, csrf_token, workspace_id=workspace_id, table_id=table_id, version=payload.expected_workspace_version, confirm=payload.review_status)

    return router
