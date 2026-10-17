from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.database import get_db_session
from app.security.permissions import RouteAccess, declare_route_access, get_authenticated_principal, require_request_csrf
from app.security.policies import Action, Principal
from app.users.models import UserRole
from app.workspaces.history import lock_workspace
from app.workspaces.models import WorkspaceState
from app.workspaces.service import (WorkspaceService, WorkspaceNotFoundError, WorkspaceForbiddenError, WorkspaceReadOnlyError, WorkspaceVersionConflictError)
from app.workspaces.edit_history import status, move

class EditInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_workspace_version: int = Field(ge=1)

def create_edit_router(settings):
    router=APIRouter(tags=['reviewer editing'])
    def access(session,wid,actor,version=None):
        from app.workspaces.router import _translate_workspace_error
        try:
            context=lock_workspace(session,wid)
            if context is None: raise WorkspaceNotFoundError('Resource not found')
            WorkspaceService()._authorize_read(actor_id=actor.user_id,role=actor.role,assigned_reviewer_id=context.task.assigned_reviewer_id)
            if version is not None:
                if actor.role!=UserRole.REVIEWER: raise WorkspaceForbiddenError('Permission denied')
                if context.workspace.state!=WorkspaceState.EDITING: raise WorkspaceReadOnlyError(context.workspace.state,context.workspace.version)
                if context.workspace.version!=version: raise WorkspaceVersionConflictError(version,context.workspace.version)
            return context
        except (WorkspaceNotFoundError,WorkspaceForbiddenError,WorkspaceReadOnlyError,WorkspaceVersionConflictError) as exc:
            raise _translate_workspace_error(exc) from exc

    @router.get('/api/v2/workspaces/{workspace_id}/edit-history')
    @declare_route_access(RouteAccess.PERMISSION,Action.READ_DRAFT)
    def history(workspace_id:UUID,session:Session=Depends(get_db_session),actor:Principal=Depends(get_authenticated_principal)):
        with session.begin():
            return status(session,access(session,workspace_id,actor),actor.user_id)

    @router.post('/api/v2/workspaces/{workspace_id}/edit-history/{direction}')
    @declare_route_access(RouteAccess.PERMISSION,Action.EDIT_DRAFT)
    def change(workspace_id:UUID,direction:Literal['undo','redo'],payload:EditInput,session:Session=Depends(get_db_session),actor:Principal=Depends(get_authenticated_principal),csrf_token:str|None=Header(default=None,alias='X-CSRF-Token')):
        require_request_csrf(actor,csrf_token,settings.session_secret.get_secret_value())
        try:
            with session.begin():
                context=access(session,workspace_id,actor,payload.expected_workspace_version)
                return move(session,context,actor.user_id,direction)
        except IntegrityError as error:
            from app.api.errors import APIError
            from app.workspaces.router import _integrity_constraint_name
            if _integrity_constraint_name(error) == 'uq_papers_doi':
                raise APIError(409, 'EDIT_HISTORY_CHANGED',
                    'Restored bibliography conflicts with another Paper') from error
            raise
    return router
