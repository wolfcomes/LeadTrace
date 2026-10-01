from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.errors import APIError
from app.compounds.models import Compound
from app.compounds.schemas import (
    CompoundCreateRequest,
    CompoundDeleteRequest,
    CompoundDeleteResponse,
    CompoundListResponse,
    CompoundMutationResponse,
    CompoundReorderRequest,
    CompoundResponse,
    CompoundUpdateRequest,
)
from app.compounds.service import (
    CompoundLabelConflictError,
    CompoundOrderError,
    CompoundReferencedError,
    CompoundService,
    CompoundValidationError,
)
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


def _compound_response(compound: Compound) -> CompoundResponse:
    return CompoundResponse(
        id=compound.id,
        paper_id=compound.paper_id,
        workspace_id=compound.workspace_id,
        compound_label=compound.compound_label,
        display_name=compound.display_name,
        description=compound.description,
        review_hint=compound.review_hint,
        sort_order=compound.sort_order,
        created_by_kind=compound.created_by_kind,
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
    if isinstance(error, CompoundOrderError):
        return APIError(
            422,
            "COMPOUND_ORDER_INVALID",
            "Compound order must contain each Workspace Compound exactly once",
        )
    if isinstance(error, CompoundLabelConflictError):
        return APIError(
            409,
            "COMPOUND_LABEL_CONFLICT",
            "Compound label conflicts with another Compound",
        )
    if isinstance(error, CompoundReferencedError):
        return APIError(
            409,
            "COMPOUND_REFERENCED",
            "Compound is referenced by scientific records",
            details={
                "lineage_references": error.lineage_references,
                "activity_references": error.activity_references,
                **({"highlight_references": error.highlight_references} if error.highlight_references else {}),
            },
        )
    if isinstance(error, CompoundValidationError):
        return APIError(422, "COMPOUND_INVALID", str(error))
    if isinstance(error, IntegrityError):
        return APIError(
            409,
            "COMPOUND_CONFLICT",
            "Compound conflicts with an existing record",
        )
    raise error


def create_compounds_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["compounds"])
    service = CompoundService()
    session_secret = settings.session_secret.get_secret_value()

    @router.get(
        "/api/v2/workspaces/{workspace_id}/compounds",
        response_model=CompoundListResponse,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.READ_DRAFT)
    def list_compounds(
        workspace_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> CompoundListResponse:
        try:
            with session.begin():
                result = service.list_compounds(
                    session,
                    workspace_id=workspace_id,
                    actor=principal,
                )
                items = [_compound_response(compound) for compound in result.compounds]
                return CompoundListResponse(
                    workspace_id=result.workspace.id,
                    workspace_version=result.workspace.version,
                    items=items,
                    total=len(items),
                )
        except (WorkspaceForbiddenError, WorkspaceNotFoundError) as error:
            raise _workspace_error(error) from error

    @router.post(
        "/api/v2/workspaces/{workspace_id}/compounds",
        response_model=CompoundMutationResponse,
        status_code=201,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def create_compound(
        workspace_id: UUID,
        payload: CompoundCreateRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> CompoundMutationResponse:
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            with session.begin():
                result = service.create_compound(
                    session,
                    workspace_id=workspace_id,
                    expected_version=payload.expected_workspace_version,
                    actor=principal,
                    compound_label=payload.compound_label,
                    display_name=payload.display_name,
                    description=payload.description,
                    review_hint=payload.review_hint,
                )
                return CompoundMutationResponse(
                    compound=_compound_response(result.compound),
                    workspace_version=result.workspace.version,
                )
        except (
            WorkspaceForbiddenError,
            WorkspaceNotFoundError,
            WorkspaceReadOnlyError,
            WorkspaceVersionConflictError,
        ) as error:
            raise _workspace_error(error) from error
        except (CompoundValidationError, IntegrityError) as error:
            raise _domain_error(error) from error

    @router.patch(
        "/api/v2/compounds/{compound_id}",
        response_model=CompoundMutationResponse,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def update_compound(
        compound_id: UUID,
        payload: CompoundUpdateRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> CompoundMutationResponse:
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            with session.begin():
                result = service.update_compound(
                    session,
                    compound_id=compound_id,
                    expected_version=payload.expected_workspace_version,
                    actor=principal,
                    updates=payload.updates(),
                )
                return CompoundMutationResponse(
                    compound=_compound_response(result.compound),
                    workspace_version=result.workspace.version,
                )
        except (
            WorkspaceForbiddenError,
            WorkspaceNotFoundError,
            WorkspaceReadOnlyError,
            WorkspaceVersionConflictError,
        ) as error:
            raise _workspace_error(error) from error
        except (CompoundValidationError, IntegrityError) as error:
            raise _domain_error(error) from error

    @router.put(
        "/api/v2/workspaces/{workspace_id}/compounds/order",
        response_model=CompoundListResponse,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def reorder_compounds(
        workspace_id: UUID,
        payload: CompoundReorderRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> CompoundListResponse:
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            with session.begin():
                result = service.reorder_compounds(
                    session,
                    workspace_id=workspace_id,
                    expected_version=payload.expected_workspace_version,
                    actor=principal,
                    compound_ids=payload.compound_ids,
                )
                items = [_compound_response(compound) for compound in result.compounds]
                return CompoundListResponse(
                    workspace_id=result.workspace.id,
                    workspace_version=result.workspace.version,
                    items=items,
                    total=len(items),
                )
        except (
            WorkspaceForbiddenError,
            WorkspaceNotFoundError,
            WorkspaceReadOnlyError,
            WorkspaceVersionConflictError,
        ) as error:
            raise _workspace_error(error) from error
        except CompoundValidationError as error:
            raise _domain_error(error) from error

    @router.delete(
        "/api/v2/compounds/{compound_id}",
        response_model=CompoundDeleteResponse,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def delete_compound(
        compound_id: UUID,
        payload: CompoundDeleteRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> CompoundDeleteResponse:
        require_request_csrf(principal, csrf_token, session_secret)
        try:
            with session.begin():
                workspace = service.delete_compound(
                    session,
                    compound_id=compound_id,
                    expected_version=payload.expected_workspace_version,
                    actor=principal,
                )
                return CompoundDeleteResponse(
                    deleted_compound_id=compound_id,
                    workspace_version=workspace.version,
                )
        except (
            WorkspaceForbiddenError,
            WorkspaceNotFoundError,
            WorkspaceReadOnlyError,
            WorkspaceVersionConflictError,
        ) as error:
            raise _workspace_error(error) from error
        except CompoundReferencedError as error:
            raise _domain_error(error) from error

    return router


__all__ = ["create_compounds_router"]
