"""Authenticated non-scientific layout and viewing mutations."""
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.errors import APIError
from app.database import get_db_session
from app.lineages.models import Lineage, LineageMember, LineageEdge, LineagePresentation
from app.security.permissions import RouteAccess, declare_route_access, get_authenticated_principal, require_request_csrf
from app.security.policies import Action, Principal
from app.users.models import UserRole
from app.workspaces.models import PaperWorkspace, WorkspaceViewReceipt, WorkspaceState
from app.workspaces.service import WorkspaceService, WorkspaceForbiddenError, WorkspaceNotFoundError, WorkspaceReadOnlyError
from app.workspaces.review_progress import get_progress

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class Point(Strict):
    x: float = Field(ge=-1000000,le=1000000)
    y: float = Field(ge=-1000000,le=1000000)

class EdgeControl(Strict):
    distance: float = Field(ge=-10000,le=10000)
    weight: float = Field(ge=0.05,le=0.95)

class LayoutInput(Strict):
    expected_revision: int = Field(ge=0)
    positions: dict[UUID,Point] = Field(default_factory=dict,max_length=5000)
    edge_controls: dict[UUID,EdgeControl] = Field(default_factory=dict,max_length=5000)

class ViewInput(Strict):
    kind: Literal['compound','lineage']
    entity_id: UUID
    signature: str = Field(pattern='^[0-9a-f]{64}$')
    viewed: bool


def create_workbench_router(settings):
    router=APIRouter(tags=['reviewer workbench'])
    service=WorkspaceService()
    def access(session,workspace_id,actor,write=False):
        from app.workspaces.router import _translate_workspace_error
        try:
            # Shared workspace lock serializes a content change against viewing/layout saves.
            if write:
                session.scalar(select(PaperWorkspace).where(PaperWorkspace.id==workspace_id).with_for_update())
            aggregate=service.get_workspace(session,workspace_id=workspace_id,actor=actor)
            if write:
                if actor.role != UserRole.REVIEWER:raise WorkspaceForbiddenError('Permission denied')
                if aggregate.workspace.state != WorkspaceState.EDITING:
                    raise WorkspaceReadOnlyError(aggregate.workspace.state,aggregate.workspace.version)
            return aggregate
        except (WorkspaceForbiddenError,WorkspaceNotFoundError,WorkspaceReadOnlyError) as exc:
            raise _translate_workspace_error(exc) from exc
    def csrf(actor,token):require_request_csrf(actor,token,settings.session_secret.get_secret_value())
    def lineage_access(session,lid,actor,write=False):
        lineage=session.get(Lineage,lid)
        if lineage is None:raise APIError(404,'RESOURCE_NOT_FOUND','Resource not found')
        access(session,lineage.workspace_id,actor,write)
        return lineage
    def layout_value(session,lid,mode):
        row=session.scalar(select(LineagePresentation).where(LineagePresentation.lineage_id==lid,LineagePresentation.mode==mode))
        members={str(x) for x in session.scalars(select(LineageMember.compound_id).where(LineageMember.lineage_id==lid))}
        edges={str(x) for x in session.scalars(select(LineageEdge.id).where(LineageEdge.lineage_id==lid))}
        return {'revision':row.revision if row else 0,'positions':{k:v for k,v in (row.positions if row else {}).items() if k in members},
                'edge_controls':{k:v for k,v in (row.edge_controls if row else {}).items() if k in edges},'mode':mode}

    @router.get('/api/v2/workspaces/{workspace_id}/review-progress')
    @declare_route_access(RouteAccess.PERMISSION,Action.READ_DRAFT)
    def progress(workspace_id:UUID,session:Session=Depends(get_db_session),actor:Principal=Depends(get_authenticated_principal)):
        with session.begin():
            aggregate=access(session,workspace_id,actor)
            return get_progress(session,workspace_id,aggregate.task.assigned_reviewer_id)

    @router.post('/api/v2/workspaces/{workspace_id}/views')
    @declare_route_access(RouteAccess.PERMISSION,Action.EDIT_DRAFT)
    def view(workspace_id:UUID,payload:ViewInput,session:Session=Depends(get_db_session),actor:Principal=Depends(get_authenticated_principal),csrf_token:str|None=Header(default=None,alias='X-CSRF-Token')):
        csrf(actor,csrf_token)
        with session.begin():
            access(session,workspace_id,actor,True)
            result=get_progress(session,workspace_id,actor.user_id)
            item=next((x for x in result['items'] if x['kind']==payload.kind and x['entity_id']==str(payload.entity_id)),None)
            if item is None:raise APIError(404,'RESOURCE_NOT_FOUND','Resource not found')
            if item['signature']!=payload.signature:raise APIError(409,'VIEW_CONTENT_CHANGED','Content changed; reopen the record')
            row=session.scalar(select(WorkspaceViewReceipt).where(WorkspaceViewReceipt.workspace_id==workspace_id,WorkspaceViewReceipt.reviewer_id==actor.user_id,WorkspaceViewReceipt.kind==payload.kind,WorkspaceViewReceipt.entity_id==payload.entity_id))
            if row is None:
                row=WorkspaceViewReceipt(workspace_id=workspace_id,reviewer_id=actor.user_id,kind=payload.kind,entity_id=payload.entity_id,signature=payload.signature);session.add(row)
            if row.signature!=payload.signature or bool(row.viewed_at)!=payload.viewed:
                row.signature=payload.signature;row.viewed_at=datetime.now(timezone.utc) if payload.viewed else None
            session.flush()
            return get_progress(session,workspace_id,actor.user_id)

    @router.get('/api/v2/lineages/{lineage_id}/layouts/{mode}')
    @declare_route_access(RouteAccess.PERMISSION,Action.READ_DRAFT)
    def get_layout(lineage_id:UUID,mode:Literal['points','structures'],session:Session=Depends(get_db_session),actor:Principal=Depends(get_authenticated_principal)):
        with session.begin():
            lineage_access(session,lineage_id,actor)
            return layout_value(session,lineage_id,mode)

    @router.put('/api/v2/lineages/{lineage_id}/layouts/{mode}')
    @declare_route_access(RouteAccess.PERMISSION,Action.EDIT_DRAFT)
    def put_layout(lineage_id:UUID,mode:Literal['points','structures'],payload:LayoutInput,session:Session=Depends(get_db_session),actor:Principal=Depends(get_authenticated_principal),csrf_token:str|None=Header(default=None,alias='X-CSRF-Token')):
        csrf(actor,csrf_token)
        with session.begin():
            lineage=lineage_access(session,lineage_id,actor,True)
            row=session.scalar(select(LineagePresentation).where(LineagePresentation.lineage_id==lineage_id,LineagePresentation.mode==mode))
            if payload.expected_revision!=(row.revision if row else 0):raise APIError(409,'LAYOUT_VERSION_CONFLICT','Layout changed; reload before saving')
            members=set(session.scalars(select(LineageMember.compound_id).where(LineageMember.lineage_id==lineage_id)))
            edges=set(session.scalars(select(LineageEdge.id).where(LineageEdge.lineage_id==lineage_id)))
            if not payload.positions.keys()<=members or not payload.edge_controls.keys()<=edges:
                raise APIError(422,'INVALID_LAYOUT_REFERENCE','Layout refers outside this lineage')
            if row is None:
                row=LineagePresentation(workspace_id=lineage.workspace_id,lineage_id=lineage_id,mode=mode,revision=0,updated_by_id=actor.user_id);session.add(row)
            row.positions={str(k):v.model_dump() for k,v in payload.positions.items()}
            row.edge_controls={str(k):v.model_dump() for k,v in payload.edge_controls.items()}
            row.revision+=1;row.updated_by_id=actor.user_id;row.updated_at=datetime.now(timezone.utc)
            session.flush()
            return layout_value(session,lineage_id,mode)
    return router
