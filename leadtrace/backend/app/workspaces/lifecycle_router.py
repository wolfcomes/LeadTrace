"""Restricted Admin lifecycle endpoints; no source content or model secrets in replies."""
from pathlib import Path
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from app.api.errors import APIError
from app.database import get_db_session
from app.security.permissions import RouteAccess, declare_route_access, require_permission, require_request_csrf
from app.security.policies import Action, Principal
from app.workspaces.assignment import PaperNotFoundError
from app.workspaces.lifecycle import management, recall_assignment, archive_reset, LifecycleConflict


class Versions(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_workspace_id:UUID
    expected_workspace_version:int=Field(ge=1)
    expected_task_version:int=Field(ge=1)


class ResetRequest(Versions):
    confirm_paper_key:str=Field(min_length=1,max_length=128)


def create_lifecycle_router(settings):
    router=APIRouter(prefix='/api/v2/admin/papers',tags=['article lifecycle'])
    admin=require_permission(Action.MANAGE_PAPER_CATALOG)
    def translate(error):
        if isinstance(error,PaperNotFoundError):return HTTPException(404,'Resource not found')
        if isinstance(error,LifecycleConflict):return APIError(409,'ARTICLE_LIFECYCLE_CONFLICT',str(error))
        return APIError(503,'ARTICLE_ARCHIVE_FAILED','Archive export failed; the working draft was retained. Check archive storage and linked assets.')

    @router.get('/{paper_id}/management')
    @declare_route_access(RouteAccess.PERMISSION,Action.MANAGE_PAPER_CATALOG)
    def get_management(paper_id:UUID,session:Session=Depends(get_db_session),principal:Principal=Depends(admin)):
        try:
            with session.begin():return management(session,paper_id,settings.article_archive_root)
        except PaperNotFoundError as exc:raise translate(exc) from exc

    @router.post('/{paper_id}/recall')
    @declare_route_access(RouteAccess.PERMISSION,Action.MANAGE_PAPER_CATALOG)
    def recall(paper_id:UUID,payload:Versions,session:Session=Depends(get_db_session),principal:Principal=Depends(admin),csrf_token:str|None=Header(default=None,alias='X-CSRF-Token')):
        require_request_csrf(principal,csrf_token,settings.session_secret.get_secret_value())
        try:
            with session.begin():
                recall_assignment(session,paper_id=paper_id,admin_id=principal.user_id,**payload.model_dump())
                return management(session,paper_id,settings.article_archive_root)
        except (PaperNotFoundError,LifecycleConflict) as exc:raise translate(exc) from exc

    @router.post('/{paper_id}/archive-reset')
    @declare_route_access(RouteAccess.PERMISSION,Action.MANAGE_PAPER_CATALOG)
    def reset(paper_id:UUID,payload:ResetRequest,session:Session=Depends(get_db_session),principal:Principal=Depends(admin),csrf_token:str|None=Header(default=None,alias='X-CSRF-Token')):
        require_request_csrf(principal,csrf_token,settings.session_secret.get_secret_value())
        try:
            with session.begin():
                archive_reset(session,paper_id=paper_id,admin_id=principal.user_id,archive_root=settings.article_archive_root,
                              asset_root=settings.asset_root,task_root=settings.ai_task_root,**payload.model_dump())
                return management(session,paper_id,settings.article_archive_root)
        except (PaperNotFoundError,LifecycleConflict,OSError) as exc:raise translate(exc) from exc
    return router
