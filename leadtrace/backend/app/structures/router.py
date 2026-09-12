from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import APIError
from app.chemistry.drawing import DrawingOptions
from app.chemistry.validation import (
    ChemistryValidationError,
    ExperimentalMaterial,
    SourceComparison,
    validate_structure,
)
from app.database import get_db_session
from app.revisions.models import ObjectRevision, StructureState
from app.reviews.models import Changeset, ReviewTask
from app.security.permissions import (
    RouteAccess,
    declare_route_access,
    get_authenticated_principal,
    require_request_csrf,
)
from app.security.policies import Action, Principal
from app.structures.models import Structure
from app.structures.service import (
    StructureDrawingService,
    StructureReviewService,
    StructureValidationError,
    StructureVersionConflict,
)
from app.users.models import UserRole


class ValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    smiles: str = Field(max_length=10000)
    selected_component_smiles: str | None = Field(default=None, max_length=10000)
    experimental_material: ExperimentalMaterial = ExperimentalMaterial.UNIQUE
    source_comparison: SourceComparison = SourceComparison.NOT_COMPARED
    source_verified: bool = False
    human_confirmed: bool = False


class StructureDraftRequest(ValidationRequest):
    compound_id: UUID | None = None
    changeset_id: UUID
    expected_version: int = Field(ge=1)
    structure_key: str | None = Field(default=None, max_length=255)
    structure_state: StructureState
    source: str = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=1, max_length=500)
    drawing_asset_id: UUID | None = None


class DrawingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    smiles: str = Field(min_length=1, max_length=10000)
    width: int = Field(default=600, ge=120, le=2400)
    height: int = Field(default=420, ge=120, le=2400)
    atom_indices: bool = False
    transparent_background: bool = False
    source_asset_id: UUID | None = None


def _authorize_paper(session: Session, principal: Principal, paper_id: UUID) -> None:
    if principal.must_change_password or principal.role is UserRole.VISITOR:
        raise HTTPException(status_code=403, detail="Permission denied")
    if principal.role is not UserRole.ADMIN:
        assigned = session.scalar(
            select(ReviewTask.id).where(
                ReviewTask.paper_id == paper_id,
                ReviewTask.assigned_reviewer_id == principal.user_id,
            )
        )
        if assigned is None:
            raise HTTPException(status_code=404, detail="Resource not found")
    session.rollback()


def require_structure_edit_permission(
    principal: Principal = Depends(get_authenticated_principal),
) -> Principal:
    if principal.must_change_password or principal.role is UserRole.VISITOR:
        raise HTTPException(status_code=403, detail="Permission denied")
    return principal


setattr(require_structure_edit_permission, "__leadtrace_action__", Action.EDIT_DRAFT)


def _error(error: Exception) -> HTTPException:
    if isinstance(error, StructureVersionConflict):
        return APIError(
            409,
            "REVISION_CONFLICT",
            "Structure draft changed concurrently",
            details={
                "expected_version": error.expected_version,
                "current_version": error.current_version,
            },
        )
    if isinstance(error, (StructureValidationError, ChemistryValidationError, ValueError)):
        message = str(error)
        if "not found" in message.casefold():
            return HTTPException(status_code=404, detail="Resource not found")
        return HTTPException(status_code=422, detail=message)
    return HTTPException(status_code=400, detail="The request could not be completed")


def _validation_payload(result: object) -> dict[str, object]:
    payload = asdict(result)
    payload["experimental_material"] = result.experimental_material.value
    payload["source_comparison"] = result.source_comparison.value
    payload["eligible_states"] = [state.value for state in result.eligible_states]
    payload["messages"] = list(result.messages)
    return payload


def _revision_payload(
    structure: Structure,
    revision: ObjectRevision,
    changeset_version: int,
) -> dict[str, object]:
    return {
        "id": str(structure.id),
        "paper_id": str(structure.paper_id),
        "compound_id": str(structure.compound_id),
        "structure_key": structure.structure_key,
        "revision_id": str(revision.id),
        "revision_number": revision.revision_number,
        "changeset_version": changeset_version,
        "snapshot": revision.snapshot,
        "structure_state": revision.structure_state.value if revision.structure_state else None,
        "workflow_state": revision.workflow_state.value,
    }


def create_structures_router(session_secret: str, managed_root: Path) -> APIRouter:
    router = APIRouter(prefix="/api/v1/papers/{paper_id}/structures", tags=["structures"])
    review_service = StructureReviewService()
    drawing_service = StructureDrawingService(managed_root)

    @router.get("")
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def list_structures(
        paper_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        _permission: Principal = Depends(require_structure_edit_permission),
    ) -> list[dict[str, object]]:
        _authorize_paper(session, principal, paper_id)
        structures = session.scalars(
            select(Structure).where(Structure.paper_id == paper_id).order_by(Structure.structure_key)
        )
        result: list[dict[str, object]] = []
        for structure in structures:
            revision = session.scalar(
                select(ObjectRevision)
                .where(ObjectRevision.object_id == structure.id)
                .order_by(ObjectRevision.revision_number.desc())
                .limit(1)
            )
            if revision is not None:
                result.append(_revision_payload(structure, revision, 0))
        return result

    @router.post("/validate")
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def validate_draft(
        paper_id: UUID,
        payload: ValidationRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        _permission: Principal = Depends(require_structure_edit_permission),
    ) -> dict[str, object]:
        _authorize_paper(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            return _validation_payload(
                validate_structure(
                    payload.smiles,
                    selected_component_smiles=payload.selected_component_smiles,
                    experimental_material=payload.experimental_material,
                    source_comparison=payload.source_comparison,
                    source_verified=payload.source_verified,
                    human_confirmed=payload.human_confirmed,
                )
            )
        except Exception as error:
            raise _error(error) from error

    @router.post("/drawings")
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def draw_structure(
        paper_id: UUID,
        payload: DrawingRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        _permission: Principal = Depends(require_structure_edit_permission),
    ) -> dict[str, object]:
        _authorize_paper(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            with session.begin():
                result = drawing_service.draw(
                    session,
                    smiles=payload.smiles,
                    options=DrawingOptions(
                        width=payload.width,
                        height=payload.height,
                        atom_indices=payload.atom_indices,
                        transparent_background=payload.transparent_background,
                    ),
                    source_asset_id=payload.source_asset_id,
                    created_by_id=principal.user_id,
                )
                return {
                    "asset_id": str(result.asset.id),
                    "drawing_key": result.drawing_key,
                    "sha256": result.asset.sha256,
                    "width": result.asset.width,
                    "height": result.asset.height,
                    "reused": result.reused,
                }
        except Exception as error:
            raise _error(error) from error

    @router.post("", status_code=201)
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def create_structure(
        paper_id: UUID,
        payload: StructureDraftRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        _permission: Principal = Depends(require_structure_edit_permission),
    ) -> dict[str, object]:
        _authorize_paper(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        if payload.compound_id is None or payload.structure_key is None:
            raise HTTPException(status_code=422, detail="compound_id and structure_key are required")
        try:
            with session.begin():
                structure, revision = review_service.create_structure(
                    session,
                    paper_id=paper_id,
                    compound_id=payload.compound_id,
                    actor_id=principal.user_id,
                    changeset_id=payload.changeset_id,
                    expected_version=payload.expected_version,
                    structure_key=payload.structure_key,
                    smiles=payload.smiles,
                    structure_state=payload.structure_state,
                    source=payload.source,
                    reason=payload.reason,
                    selected_component_smiles=payload.selected_component_smiles,
                    experimental_material=payload.experimental_material,
                    source_comparison=payload.source_comparison,
                    source_verified=payload.source_verified,
                    human_confirmed=payload.human_confirmed,
                    drawing_asset_id=payload.drawing_asset_id,
                )
                changeset = session.get(Changeset, payload.changeset_id)
                if changeset is None:
                    raise StructureValidationError("Changeset not found")
                return _revision_payload(structure, revision, changeset.version)
        except Exception as error:
            raise _error(error) from error

    @router.patch("/{structure_id}")
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def update_structure(
        paper_id: UUID,
        structure_id: UUID,
        payload: StructureDraftRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        _permission: Principal = Depends(require_structure_edit_permission),
    ) -> dict[str, object]:
        _authorize_paper(session, principal, paper_id)
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            structure = session.get(Structure, structure_id)
            if structure is None or structure.paper_id != paper_id:
                raise StructureValidationError("Structure not found")
            session.rollback()
            with session.begin():
                revision = review_service.update_structure(
                    session,
                    structure_id=structure_id,
                    actor_id=principal.user_id,
                    changeset_id=payload.changeset_id,
                    expected_version=payload.expected_version,
                    smiles=payload.smiles,
                    structure_state=payload.structure_state,
                    source=payload.source,
                    reason=payload.reason,
                    selected_component_smiles=payload.selected_component_smiles,
                    experimental_material=payload.experimental_material,
                    source_comparison=payload.source_comparison,
                    source_verified=payload.source_verified,
                    human_confirmed=payload.human_confirmed,
                    drawing_asset_id=payload.drawing_asset_id,
                )
                structure = session.get(Structure, structure_id)
                changeset = session.get(Changeset, payload.changeset_id)
                if structure is None or changeset is None:
                    raise StructureValidationError("Structure not found")
                return _revision_payload(structure, revision, changeset.version)
        except Exception as error:
            raise _error(error) from error

    return router
