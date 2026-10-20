"""Same-workspace aggregate cloning through the versioned reviewer mutation boundary."""
from uuid import UUID, uuid4
from typing import Literal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.activities.models import Activity
from app.api.errors import APIError
from app.compounds.models import Compound
from app.config import Settings
from app.database import get_db_session
from app.evidence.models import EdgeEvidenceLink
from app.lineages.models import Lineage, LineageEdge, LineageMember
from app.security.permissions import RouteAccess, declare_route_access, get_authenticated_principal, require_request_csrf
from app.security.policies import Action, Principal
from app.structure_images.models import StructureSourceImage
from app.structures.models import Structure
from app.workspaces.history import MutationChange
from app.workspaces.router import _translate_workspace_error
from app.workspaces.service import WorkspaceService, WorkspaceNotFoundError, WorkspaceForbiddenError, WorkspaceReadOnlyError, WorkspaceVersionConflictError


class PasteRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_workspace_version: int = Field(ge=1)
    source_id: UUID
    label: str = Field(min_length=1, max_length=255)
    display_name: str | None = Field(default=None, max_length=512)

    @field_validator('label')
    @classmethod
    def required_label(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError('A new label is required')
        return value


class PasteResponse(BaseModel):
    entity_id: UUID
    workspace_version: int


def _copy(session: Session, source, fields: str, **overrides):
    values = {field: getattr(source, field) for field in fields.split()}
    values.update(id=uuid4(), paper_id=source.paper_id, workspace_id=source.workspace_id, created_by_kind='reviewer')
    values.update(overrides)
    clone = type(source)(**values)
    session.add(clone)
    return clone


def paste_record(session: Session, *, workspace_id: UUID, kind: str, payload: PasteRequest, actor) -> PasteResponse:
    copied_id = uuid4()

    def mutation(context):
        from app.workspaces.snapshot import build_paper_snapshot
        before_snapshot = build_paper_snapshot(session, workspace_id)
        model = Compound if kind == 'compound' else Lineage
        source = session.scalar(select(model).where(model.id == payload.source_id, model.workspace_id == workspace_id))
        if source is None:
            raise WorkspaceNotFoundError('Source record not found')
        order = session.scalar(select(func.max(model.sort_order)).where(model.workspace_id == workspace_id))
        common = dict(id=copied_id, sort_order=(order + 1 if order is not None else 0))
        if kind == 'compound':
            if session.scalar(select(Compound.id).where(Compound.workspace_id == workspace_id, Compound.compound_label == payload.label)):
                raise APIError(409, 'COMPOUND_LABEL_CONFLICT', 'Compound label already exists')
            _copy(session, source, 'description review_hint', compound_label=payload.label, display_name=(payload.display_name or '').strip() or None, **common)
            session.flush()
            structure = session.scalar(select(Structure).where(Structure.compound_id == source.id))
            if structure is not None:
                _copy(session, structure, 'smiles canonical_smiles molfile inchi inchikey depiction_asset_id input_method availability availability_note identity_source checked_sources', compound_id=copied_id, status='draft')
            for image in session.scalars(select(StructureSourceImage).where(StructureSourceImage.compound_id == source.id)):
                _copy(session, image, 'source_sha256 page_number x0 y0 x1 y1 source_context label reviewer_note crop_status crop_asset_id', compound_id=copied_id)
            for activity in session.scalars(select(Activity).where(Activity.compound_id == source.id)):
                _copy(session, activity, 'evidence_id assay_name metric operator value unit context review_hint sort_order', compound_id=copied_id)
        else:
            _copy(session, source, 'description lineage_type', lineage_label=payload.label, **common)
            session.flush()
            for member in session.scalars(select(LineageMember).where(LineageMember.lineage_id == source.id)):
                _copy(session, member, 'compound_id role sort_order', lineage_id=copied_id)
            session.flush()
            for edge in session.scalars(select(LineageEdge).where(LineageEdge.lineage_id == source.id)):
                copied_edge = _copy(session, edge, 'parent_compound_id child_compound_id relation_type modification_summary review_hint sort_order', lineage_id=copied_id, review_status='draft')
                session.flush()
                for link in session.scalars(select(EdgeEvidenceLink).where(EdgeEvidenceLink.edge_id == edge.id)):
                    _copy(session, link, 'evidence_id role', edge_id=copied_edge.id)
        session.flush()
        after_snapshot = build_paper_snapshot(session, workspace_id)
        # WorkspaceService increments the version after this callback.
        after_snapshot['workspace_version'] = context.workspace.version + 1
        return MutationChange(entity_type=kind, entity_id=copied_id, action=f'{kind}.paste', before_value={'snapshot': before_snapshot}, after_value={'snapshot': after_snapshot, 'source_id': str(source.id), 'copied_id': str(copied_id), 'label': payload.label})

    result = WorkspaceService().mutate(session, workspace_id=workspace_id, expected_version=payload.expected_workspace_version, actor=actor, mutation=mutation)
    return PasteResponse(entity_id=copied_id, workspace_version=result.workspace.version)


def create_clipboard_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=['workspace clipboard'])

    @router.post('/api/v2/workspaces/{workspace_id}/clipboard/{kind}', response_model=PasteResponse, status_code=201)
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def paste(workspace_id: UUID, kind: Literal['compound', 'lineage'], payload: PasteRequest,
              csrf_token: str | None = Header(default=None, alias='X-CSRF-Token'),
              session: Session = Depends(get_db_session),
              principal: Principal = Depends(get_authenticated_principal)) -> PasteResponse:
        require_request_csrf(principal, csrf_token, settings.session_secret.get_secret_value())
        try:
            with session.begin():
                return paste_record(session, workspace_id=workspace_id, kind=kind, payload=payload, actor=principal)
        except (WorkspaceNotFoundError, WorkspaceForbiddenError, WorkspaceReadOnlyError, WorkspaceVersionConflictError) as error:
            raise _translate_workspace_error(error) from error

    return router
