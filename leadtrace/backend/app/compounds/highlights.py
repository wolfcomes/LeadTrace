"""Evidence-backed article selections, orthogonal to Lineage topology roles."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.errors import APIError
from app.compounds.models import Compound, CompoundHighlight
from app.compounds.router import _workspace_error
from app.database import get_db_session
from app.evidence.models import Evidence
from app.security.permissions import RouteAccess, declare_route_access, get_authenticated_principal, require_request_csrf
from app.security.policies import Action, Principal
from app.workspaces.history import MutationChange
from app.workspaces.service import WorkspaceService, WorkspaceNotFoundError, WorkspaceForbiddenError, WorkspaceReadOnlyError, WorkspaceVersionConflictError

Role = Literal['study_start', 'paper_selected']
ReviewStatus = Literal['draft', 'reviewer_confirmed', 'unresolved']
FIELDS = ('id', 'paper_id', 'workspace_id', 'compound_id', 'evidence_id', 'role', 'scope', 'rationale', 'review_hint', 'review_status', 'created_by_kind')
EDIT_FIELDS = ('compound_id', 'evidence_id', 'role', 'scope', 'rationale', 'review_hint', 'review_status')


def highlight_snapshot(row):
    return {field: str(value) if isinstance(value, UUID) else value
            for field in FIELDS for value in [getattr(row, field)]}


class HighlightCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_workspace_version: int = Field(ge=1)
    compound_id: UUID
    evidence_id: UUID
    role: Role
    scope: str = Field(min_length=1, max_length=512)
    rationale: str = Field(min_length=1, max_length=10_000)
    review_hint: str | None = Field(default=None, max_length=1000)
    review_status: ReviewStatus = 'draft'

    @field_validator('scope', 'rationale')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Nonblank text is required')
        return value.strip()


class HighlightUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_workspace_version: int = Field(ge=1)
    compound_id: UUID | None = None
    evidence_id: UUID | None = None
    role: Role | None = None
    scope: str | None = Field(default=None, min_length=1, max_length=512)
    rationale: str | None = Field(default=None, min_length=1, max_length=10_000)
    review_hint: str | None = Field(default=None, max_length=1000)
    review_status: ReviewStatus | None = None

    @model_validator(mode='after')
    def validate_update(self):
        fields = self.model_fields_set - {'expected_workspace_version'}
        if not fields:
            raise ValueError('At least one highlight field is required')
        for field in fields - {'review_hint'}:
            value = getattr(self, field)
            if value is None or (isinstance(value, str) and not value.strip()):
                raise ValueError(f'{field} cannot be empty')
            if isinstance(value, str):
                setattr(self, field, value.strip())
        return self


class HighlightDelete(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_workspace_version: int = Field(ge=1)


class HighlightResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: UUID
    paper_id: UUID
    workspace_id: UUID
    compound_id: UUID
    evidence_id: UUID
    role: Role
    scope: str
    rationale: str
    review_hint: str | None
    review_status: ReviewStatus
    created_by_kind: str


class HighlightMutationResponse(BaseModel):
    highlight: HighlightResponse
    workspace_version: int


class HighlightListResponse(BaseModel):
    workspace_id: UUID
    workspace_version: int
    items: list[HighlightResponse]
    total: int


class HighlightDeleteResponse(BaseModel):
    deleted_highlight_id: UUID
    workspace_version: int


WORKSPACE_ERRORS = (WorkspaceNotFoundError, WorkspaceForbiddenError, WorkspaceReadOnlyError, WorkspaceVersionConflictError)


def create_highlights_router(settings):
    router = APIRouter(tags=['compound-highlights'])
    service = WorkspaceService()
    secret = settings.session_secret.get_secret_value()

    @router.get('/api/v2/workspaces/{workspace_id}/compound-highlights', response_model=HighlightListResponse)
    @declare_route_access(RouteAccess.PERMISSION, Action.READ_DRAFT)
    def listing(workspace_id: UUID, session: Session = Depends(get_db_session), principal: Principal = Depends(get_authenticated_principal)):
        try:
            with session.begin():
                aggregate = service.get_workspace(session, workspace_id=workspace_id, actor=principal)
                rows = list(session.scalars(select(CompoundHighlight).where(CompoundHighlight.workspace_id == workspace_id).order_by(CompoundHighlight.role, CompoundHighlight.scope, CompoundHighlight.id)))
                return {'workspace_id': workspace_id, 'workspace_version': aggregate.workspace.version,
                        'items': [highlight_snapshot(row) for row in rows], 'total': len(rows)}
        except WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error

    def mutate(session, principal, version, values, workspace_id=None, highlight_id=None, delete=False):
        if workspace_id is None:
            workspace_id = session.scalar(select(CompoundHighlight.workspace_id).where(CompoundHighlight.id == highlight_id))
            if workspace_id is None:
                raise WorkspaceNotFoundError('Resource not found')
        result = {}
        def mutation(context):
            row = session.get(CompoundHighlight, highlight_id) if highlight_id else None
            if highlight_id and (row is None or row.workspace_id != context.workspace.id):
                raise WorkspaceNotFoundError('Resource not found')
            before = highlight_snapshot(row) if row else None
            if delete:
                session.delete(row)
                return MutationChange(entity_type='compound_highlight', entity_id=highlight_id, action='compound_highlight.delete', before_value=before, after_value=None)
            data = {field: getattr(row, field) for field in EDIT_FIELDS} if row else {}
            data.update(values)
            if data.get('review_hint') is not None:
                data['review_hint'] = data['review_hint'].strip() or None
            # Editing a confirmed scientific assertion invalidates its prior approval unless explicitly reconfirmed.
            if row and 'review_status' not in values and any(data[f] != getattr(row, f) for f in EDIT_FIELDS if f != 'review_status'):
                data['review_status'] = 'draft'
            for model, key in ((Compound, 'compound_id'), (Evidence, 'evidence_id')):
                referenced = session.get(model, data[key])
                if referenced is None or referenced.workspace_id != context.workspace.id or referenced.paper_id != context.workspace.paper_id:
                    raise APIError(422, 'COMPOUND_HIGHLIGHT_INVALID', 'Compound and Evidence must belong to this Workspace')
            if row is None:
                row = CompoundHighlight(paper_id=context.workspace.paper_id, workspace_id=context.workspace.id, created_by_kind='reviewer', **data)
                session.add(row)
            else:
                for key, value in data.items():
                    setattr(row, key, value)
            session.flush()
            result['highlight'] = highlight_snapshot(row)
            return MutationChange(entity_type='compound_highlight', entity_id=row.id, action='compound_highlight.update' if before else 'compound_highlight.create', before_value=before, after_value=result['highlight'])
        changed = service.mutate(session, workspace_id=workspace_id, expected_version=version, actor=principal, mutation=mutation)
        return ({'deleted_highlight_id': highlight_id} if delete else result) | {'workspace_version': changed.workspace.version}

    def run(session, **kwargs):
        try:
            with session.begin():
                return mutate(session, **kwargs)
        except WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error
        except IntegrityError as error:
            raise APIError(409, 'COMPOUND_HIGHLIGHT_CONFLICT', 'A highlight with this Compound, role and scope already exists') from error

    @router.post('/api/v2/workspaces/{workspace_id}/compound-highlights', response_model=HighlightMutationResponse, status_code=201)
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def create(workspace_id: UUID, payload: HighlightCreate, csrf_token: str | None = Header(default=None, alias='X-CSRF-Token'), session: Session = Depends(get_db_session), principal: Principal = Depends(get_authenticated_principal)):
        require_request_csrf(principal, csrf_token, secret)
        return run(session, principal=principal, version=payload.expected_workspace_version, values=payload.model_dump(exclude={'expected_workspace_version'}), workspace_id=workspace_id)

    @router.patch('/api/v2/compound-highlights/{highlight_id}', response_model=HighlightMutationResponse)
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def update(highlight_id: UUID, payload: HighlightUpdate, csrf_token: str | None = Header(default=None, alias='X-CSRF-Token'), session: Session = Depends(get_db_session), principal: Principal = Depends(get_authenticated_principal)):
        require_request_csrf(principal, csrf_token, secret)
        return run(session, principal=principal, version=payload.expected_workspace_version, values=payload.model_dump(exclude_unset=True, exclude={'expected_workspace_version'}), highlight_id=highlight_id)

    @router.delete('/api/v2/compound-highlights/{highlight_id}', response_model=HighlightDeleteResponse)
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def delete(highlight_id: UUID, payload: HighlightDelete, csrf_token: str | None = Header(default=None, alias='X-CSRF-Token'), session: Session = Depends(get_db_session), principal: Principal = Depends(get_authenticated_principal)):
        require_request_csrf(principal, csrf_token, secret)
        return run(session, principal=principal, version=payload.expected_workspace_version, values={}, highlight_id=highlight_id, delete=True)

    return router
