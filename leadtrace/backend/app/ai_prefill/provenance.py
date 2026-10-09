"""Read-only reviewer provenance; version-checked administrator attestations."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.ai_prefill.models import AiProvenance
from app.api.errors import APIError
from app.database import get_db_session
from app.config import Settings
from app.security.permissions import RouteAccess, declare_route_access, get_authenticated_principal, require_permission, require_request_csrf
from app.security.policies import Action, Principal
from app.workspaces.models import PaperWorkspace
from app.workspaces.service import WorkspaceService, WorkspaceForbiddenError, WorkspaceNotFoundError

class ProvenanceInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    run_key: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$')
    stage: Literal['prefill','producer_self_check','repair','independent_review']
    adapter: str | None = Field(default=None, pattern=r'^[A-Za-z0-9._-]{1,64}$')
    model: str | None = Field(default=None, pattern=r'^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$')
    reasoning_effort: str | None = Field(default=None, pattern=r'^[A-Za-z0-9_-]{1,32}$')
    observed_model: str | None = Field(default=None, pattern=r'^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$')
    observed_reasoning_effort: str | None = Field(default=None, pattern=r'^[A-Za-z0-9_-]{1,32}$')
    verification: Literal['unknown','candidate_declared','requested_only','request_observed','mismatch'] = 'unknown'
    source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    candidate_file_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    evidence_sha256: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    guide_version: str | None = Field(default=None,max_length=128)
    guide_bundle_sha256: str | None = Field(default=None,pattern=r'^[a-f0-9]{64}$')
    completed_at: datetime | None = None
    outcome: Literal['completed','needs_revision','partial','failed','unknown'] = 'unknown'
    applied_workspace_version: int | None = Field(default=None,ge=1)
    @model_validator(mode='after')
    def evidence_required(self):
        if self.verification in {'request_observed','mismatch'} and (not self.evidence_sha256 or not self.observed_model):
            raise ValueError('Observed configuration requires model and evidence hash')
        if self.stage == 'independent_review' and self.applied_workspace_version is not None:
            raise ValueError('A review cannot apply a candidate')
        if self.outcome == 'failed' and self.applied_workspace_version is not None:
            raise ValueError('A failed run cannot be recorded as applied')
        if self.verification == 'request_observed':
            if self.model and self.model != self.observed_model:
                raise ValueError('Observed model differs from request; record mismatch')
            if self.reasoning_effort and self.reasoning_effort != self.observed_reasoning_effort:
                raise ValueError('Observed effort differs from request; record mismatch')
        return self

class ProvenanceAppend(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_workspace_version: int = Field(ge=1)
    record: ProvenanceInput


def list_provenance(session: Session, workspace_id: UUID) -> list[dict]:
    return [r.record for r in session.scalars(select(AiProvenance).where(AiProvenance.workspace_id==workspace_id).order_by(AiProvenance.recorded_at,AiProvenance.id))]


def append_provenance(session: Session, *, workspace: PaperWorkspace, source_sha256: str, actor_id: UUID, record: ProvenanceInput) -> bool:
    if workspace.state.value == 'archived':
        raise ValueError('Archived workspace provenance is immutable')
    if record.source_sha256 != source_sha256:
        raise ValueError('Provenance source does not match article')
    if record.applied_workspace_version and record.applied_workspace_version>workspace.version:
        raise ValueError('Applied version cannot exceed current workspace version')
    body=record.model_dump(mode='json')
    previous=session.scalar(select(AiProvenance).where(AiProvenance.workspace_id==workspace.id,AiProvenance.run_key==record.run_key))
    if previous:
        if previous.record != body:raise ValueError('Run identity already has a different provenance record')
        return False
    session.add(AiProvenance(workspace_id=workspace.id,paper_id=workspace.paper_id,run_key=record.run_key,recorded_by_id=actor_id,record=body))
    session.flush()
    return True


def create_provenance_router(settings: Settings):
    router=APIRouter(tags=['AI provenance'])
    service=WorkspaceService()
    @router.get('/api/v2/workspaces/{workspace_id}/ai-provenance')
    @declare_route_access(RouteAccess.PERMISSION,Action.READ_DRAFT)
    def get_records(workspace_id: UUID, session: Session=Depends(get_db_session), principal: Principal=Depends(get_authenticated_principal)):
        try:
            with session.begin():
                a=service.get_workspace(session,workspace_id=workspace_id,actor=principal)
                return {'items':list_provenance(session,workspace_id),'workspace_version':a.workspace.version}
        except (WorkspaceNotFoundError,WorkspaceForbiddenError):raise APIError(404,'RESOURCE_NOT_FOUND','Resource not found') from None
    @router.post('/api/v2/admin/workspaces/{workspace_id}/ai-provenance')
    @declare_route_access(RouteAccess.PERMISSION,Action.MANAGE_PAPER_CATALOG)
    def append_record(workspace_id: UUID, body: ProvenanceAppend, session: Session=Depends(get_db_session), principal: Principal=Depends(require_permission(Action.MANAGE_PAPER_CATALOG)), csrf_token: str|None=Header(default=None,alias='X-CSRF-Token')):
        require_request_csrf(principal,csrf_token,settings.session_secret.get_secret_value())
        try:
            with session.begin():
                a=service.get_workspace(session,workspace_id=workspace_id,actor=principal)
                w=session.scalar(select(PaperWorkspace).where(PaperWorkspace.id==workspace_id).with_for_update())
                if w.version!=body.expected_workspace_version:raise APIError(409,'WORKSPACE_VERSION_CONFLICT','Workspace version changed')
                created=append_provenance(session,workspace=w,source_sha256=a.source.sha256,actor_id=principal.user_id,record=body.record)
                return {'created':created,'items':list_provenance(session,workspace_id),'workspace_version':w.version}
        except ValueError as e:raise APIError(409,'PROVENANCE_CONFLICT',str(e)) from None
        except (WorkspaceNotFoundError,WorkspaceForbiddenError):raise APIError(404,'RESOURCE_NOT_FOUND','Resource not found') from None
    return router
