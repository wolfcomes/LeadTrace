from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response
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
from app.structures.models import Structure
from app.structures.schemas import (
    StructureMutationResponse,
    StructureReadResponse,
    StructureResponse,
    StructureUpsertRequest,
)
from app.structures.service import StructureService, StructureValidationError
from app.workspaces.service import (
    WorkspaceForbiddenError,
    WorkspaceNotFoundError,
    WorkspaceReadOnlyError,
    WorkspaceVersionConflictError,
)


def _structure_response(structure: Structure) -> StructureResponse:
    return StructureResponse(
        id=structure.id,
        paper_id=structure.paper_id,
        workspace_id=structure.workspace_id,
        compound_id=structure.compound_id,
        smiles=structure.smiles,
        molfile=structure.molfile,
        canonical_smiles=structure.canonical_smiles,
        inchi=structure.inchi,
        inchikey=structure.inchikey,
        depiction_asset_id=structure.depiction_asset_id,
        status=structure.status,
        input_method=structure.input_method,
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


def create_structures_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["structures"])
    service = StructureService(settings.asset_root)
    session_secret = settings.session_secret.get_secret_value()

    @router.get(
        "/api/v2/compounds/{compound_id}/structure",
        response_model=StructureReadResponse,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.READ_DRAFT)
    def get_structure(
        compound_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> StructureReadResponse:
        try:
            with session.begin():
                result = service.get_structure(
                    session,
                    compound_id=compound_id,
                    actor=principal,
                )
                return StructureReadResponse(
                    structure=(
                        _structure_response(result.structure)
                        if result.structure is not None
                        else None
                    ),
                    workspace_version=result.workspace.version,
                )
        except (WorkspaceForbiddenError, WorkspaceNotFoundError) as error:
            raise _workspace_error(error) from error

    @router.put(
        "/api/v2/compounds/{compound_id}/structure",
        response_model=StructureMutationResponse,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def upsert_structure(
        compound_id: UUID,
        payload: StructureUpsertRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> StructureMutationResponse:
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            with session.begin():
                result = service.upsert_structure(
                    session,
                    compound_id=compound_id,
                    expected_version=payload.expected_workspace_version,
                    actor=principal,
                    status=payload.status,
                    input_method=payload.input_method,
                    smiles=payload.smiles,
                    molfile=payload.molfile,
                )
                return StructureMutationResponse(
                    structure=_structure_response(result.structure),
                    workspace_version=result.workspace.version,
                )
        except (
            WorkspaceForbiddenError,
            WorkspaceNotFoundError,
            WorkspaceReadOnlyError,
            WorkspaceVersionConflictError,
        ) as error:
            raise _workspace_error(error) from error
        except StructureValidationError as error:
            raise APIError(422, "STRUCTURE_INVALID", str(error)) from error

    @router.get(
        "/api/v2/compounds/{compound_id}/structure/depiction",
        response_class=Response,
        responses={200: {"content": {"image/png": {}}}},
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.READ_DRAFT)
    def get_structure_depiction(
        compound_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> Response:
        try:
            with session.begin():
                depiction = service.get_depiction(
                    session,
                    compound_id=compound_id,
                    actor=principal,
                )
        except (WorkspaceForbiddenError, WorkspaceNotFoundError) as error:
            raise _workspace_error(error) from error
        if depiction is None:
            raise APIError(404, "RESOURCE_NOT_FOUND", "Resource not found")
        return Response(
            content=depiction.content,
            media_type=depiction.media_type,
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    return router


__all__ = ["create_structures_router"]
