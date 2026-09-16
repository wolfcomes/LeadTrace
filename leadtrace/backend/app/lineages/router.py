from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.errors import APIError
from app.config import Settings
from app.database import get_db_session
from app.lineages.models import Lineage, LineageEdge, LineageMember
from app.lineages.schemas import (
    DeletedResponse,
    LineageCreateRequest,
    LineageEdgeCreateRequest,
    LineageEdgeListResponse,
    LineageEdgeMutationResponse,
    LineageEdgeReorderRequest,
    LineageEdgeResponse,
    LineageEdgeUpdateRequest,
    LineageListResponse,
    LineageMemberCreateRequest,
    LineageMemberListResponse,
    LineageMemberMutationResponse,
    LineageMemberReorderRequest,
    LineageMemberResponse,
    LineageMemberUpdateRequest,
    LineageMutationResponse,
    LineageReorderRequest,
    LineageResponse,
    LineageUpdateRequest,
    WorkspaceVersionRequest,
)
from app.lineages.service import (
    LineageConflictError,
    LineageMemberReferencedError,
    LineageOrderError,
    LineageRecord,
    LineageService,
    LineageValidationError,
)
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


def _member_response(row: LineageMember) -> LineageMemberResponse:
    return LineageMemberResponse(
        id=row.id,
        paper_id=row.paper_id,
        workspace_id=row.workspace_id,
        lineage_id=row.lineage_id,
        compound_id=row.compound_id,
        role=row.role,
        sort_order=row.sort_order,
    )


def _edge_response(row: LineageEdge) -> LineageEdgeResponse:
    return LineageEdgeResponse(
        id=row.id,
        paper_id=row.paper_id,
        workspace_id=row.workspace_id,
        lineage_id=row.lineage_id,
        parent_compound_id=row.parent_compound_id,
        child_compound_id=row.child_compound_id,
        relation_type=row.relation_type,
        modification_summary=row.modification_summary,
        review_status=row.review_status,
        sort_order=row.sort_order,
    )


def _lineage_response(record: LineageRecord) -> LineageResponse:
    row: Lineage = record.lineage
    return LineageResponse(
        id=row.id,
        paper_id=row.paper_id,
        workspace_id=row.workspace_id,
        lineage_label=row.lineage_label,
        description=row.description,
        sort_order=row.sort_order,
        members=[_member_response(member) for member in record.members],
        edges=[_edge_response(edge) for edge in record.edges],
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
    if isinstance(error, LineageOrderError):
        return APIError(422, "LINEAGE_ORDER_INVALID", str(error))
    if isinstance(error, LineageValidationError):
        return APIError(422, "LINEAGE_INVALID", str(error))
    if isinstance(error, LineageMemberReferencedError):
        return APIError(
            409,
            "LINEAGE_MEMBER_REFERENCED",
            "Lineage member is referenced by Edges",
            details={"edge_references": error.edge_references},
        )
    if isinstance(error, (LineageConflictError, IntegrityError)):
        return APIError(
            409,
            "LINEAGE_CONFLICT",
            "Lineage record conflicts with an existing record",
        )
    raise error


_WORKSPACE_ERRORS = (
    WorkspaceForbiddenError,
    WorkspaceNotFoundError,
    WorkspaceReadOnlyError,
    WorkspaceVersionConflictError,
)
_DOMAIN_ERRORS = (
    LineageValidationError,
    LineageConflictError,
    LineageMemberReferencedError,
    IntegrityError,
)


def create_lineages_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["lineages"])
    service = LineageService()
    secret = settings.session_secret.get_secret_value()

    @router.get(
        "/api/v2/workspaces/{workspace_id}/lineages",
        response_model=LineageListResponse,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.READ_DRAFT)
    def list_lineages(
        workspace_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> LineageListResponse:
        try:
            with session.begin():
                result = service.list_lineages(
                    session, workspace_id=workspace_id, actor=principal
                )
                items = [_lineage_response(record) for record in result.records]
                return LineageListResponse(
                    workspace_id=workspace_id,
                    workspace_version=result.workspace.version,
                    items=items,
                    total=len(items),
                )
        except _WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error

    @router.post(
        "/api/v2/workspaces/{workspace_id}/lineages",
        response_model=LineageMutationResponse,
        status_code=201,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def create_lineage(
        workspace_id: UUID,
        payload: LineageCreateRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> LineageMutationResponse:
        require_request_csrf(principal, csrf_token, secret)
        try:
            with session.begin():
                result = service.create_lineage(
                    session,
                    workspace_id=workspace_id,
                    expected_version=payload.expected_workspace_version,
                    actor=principal,
                    lineage_label=payload.lineage_label,
                    description=payload.description,
                )
                return LineageMutationResponse(
                    lineage=_lineage_response(result.record),
                    workspace_version=result.workspace.version,
                )
        except _WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error
        except _DOMAIN_ERRORS as error:
            raise _domain_error(error) from error

    @router.patch(
        "/api/v2/lineages/{lineage_id}", response_model=LineageMutationResponse
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def update_lineage(
        lineage_id: UUID,
        payload: LineageUpdateRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> LineageMutationResponse:
        require_request_csrf(principal, csrf_token, secret)
        try:
            with session.begin():
                result = service.update_lineage(
                    session,
                    lineage_id=lineage_id,
                    expected_version=payload.expected_workspace_version,
                    actor=principal,
                    updates=payload.updates(),
                )
                return LineageMutationResponse(
                    lineage=_lineage_response(result.record),
                    workspace_version=result.workspace.version,
                )
        except _WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error
        except _DOMAIN_ERRORS as error:
            raise _domain_error(error) from error

    @router.put(
        "/api/v2/workspaces/{workspace_id}/lineages/order",
        response_model=LineageListResponse,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def reorder_lineages(
        workspace_id: UUID,
        payload: LineageReorderRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> LineageListResponse:
        require_request_csrf(principal, csrf_token, secret)
        try:
            with session.begin():
                result = service.reorder_lineages(
                    session,
                    workspace_id=workspace_id,
                    expected_version=payload.expected_workspace_version,
                    actor=principal,
                    lineage_ids=payload.lineage_ids,
                )
                items = [_lineage_response(record) for record in result.records]
                return LineageListResponse(
                    workspace_id=workspace_id,
                    workspace_version=result.workspace.version,
                    items=items,
                    total=len(items),
                )
        except _WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error
        except _DOMAIN_ERRORS as error:
            raise _domain_error(error) from error

    @router.delete(
        "/api/v2/lineages/{lineage_id}", response_model=DeletedResponse
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def delete_lineage(
        lineage_id: UUID,
        payload: WorkspaceVersionRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> DeletedResponse:
        require_request_csrf(principal, csrf_token, secret)
        try:
            with session.begin():
                workspace = service.delete_lineage(
                    session,
                    lineage_id=lineage_id,
                    expected_version=payload.expected_workspace_version,
                    actor=principal,
                )
                return DeletedResponse(
                    deleted_id=lineage_id, workspace_version=workspace.version
                )
        except _WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error
        except _DOMAIN_ERRORS as error:
            raise _domain_error(error) from error

    @router.get(
        "/api/v2/lineages/{lineage_id}/members",
        response_model=LineageMemberListResponse,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.READ_DRAFT)
    def list_members(
        lineage_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> LineageMemberListResponse:
        try:
            with session.begin():
                result = service.list_members(
                    session, lineage_id=lineage_id, actor=principal
                )
                items = [_member_response(row) for row in result.members]
                return LineageMemberListResponse(
                    lineage_id=lineage_id,
                    workspace_version=result.workspace.version,
                    items=items,
                    total=len(items),
                )
        except _WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error

    @router.post(
        "/api/v2/lineages/{lineage_id}/members",
        response_model=LineageMemberMutationResponse,
        status_code=201,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def add_member(
        lineage_id: UUID,
        payload: LineageMemberCreateRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> LineageMemberMutationResponse:
        require_request_csrf(principal, csrf_token, secret)
        try:
            with session.begin():
                result = service.add_member(
                    session,
                    lineage_id=lineage_id,
                    expected_version=payload.expected_workspace_version,
                    actor=principal,
                    compound_id=payload.compound_id,
                    role=payload.role,
                )
                return LineageMemberMutationResponse(
                    member=_member_response(result.member),
                    workspace_version=result.workspace.version,
                )
        except _WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error
        except _DOMAIN_ERRORS as error:
            raise _domain_error(error) from error

    @router.patch(
        "/api/v2/lineage-members/{member_id}",
        response_model=LineageMemberMutationResponse,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def update_member(
        member_id: UUID,
        payload: LineageMemberUpdateRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> LineageMemberMutationResponse:
        require_request_csrf(principal, csrf_token, secret)
        try:
            with session.begin():
                result = service.update_member(
                    session,
                    member_id=member_id,
                    expected_version=payload.expected_workspace_version,
                    actor=principal,
                    role=payload.role,
                )
                return LineageMemberMutationResponse(
                    member=_member_response(result.member),
                    workspace_version=result.workspace.version,
                )
        except _WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error
        except _DOMAIN_ERRORS as error:
            raise _domain_error(error) from error

    @router.put(
        "/api/v2/lineages/{lineage_id}/members/order",
        response_model=LineageMemberListResponse,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def reorder_members(
        lineage_id: UUID,
        payload: LineageMemberReorderRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> LineageMemberListResponse:
        require_request_csrf(principal, csrf_token, secret)
        try:
            with session.begin():
                result = service.reorder_members(
                    session,
                    lineage_id=lineage_id,
                    expected_version=payload.expected_workspace_version,
                    actor=principal,
                    member_ids=payload.member_ids,
                )
                items = [_member_response(row) for row in result.members]
                return LineageMemberListResponse(
                    lineage_id=lineage_id,
                    workspace_version=result.workspace.version,
                    items=items,
                    total=len(items),
                )
        except _WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error
        except _DOMAIN_ERRORS as error:
            raise _domain_error(error) from error

    @router.delete(
        "/api/v2/lineage-members/{member_id}", response_model=DeletedResponse
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def delete_member(
        member_id: UUID,
        payload: WorkspaceVersionRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> DeletedResponse:
        require_request_csrf(principal, csrf_token, secret)
        try:
            with session.begin():
                workspace = service.delete_member(
                    session,
                    member_id=member_id,
                    expected_version=payload.expected_workspace_version,
                    actor=principal,
                )
                return DeletedResponse(
                    deleted_id=member_id, workspace_version=workspace.version
                )
        except _WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error
        except _DOMAIN_ERRORS as error:
            raise _domain_error(error) from error

    @router.get(
        "/api/v2/lineages/{lineage_id}/edges",
        response_model=LineageEdgeListResponse,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.READ_DRAFT)
    def list_edges(
        lineage_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> LineageEdgeListResponse:
        try:
            with session.begin():
                result = service.list_edges(
                    session, lineage_id=lineage_id, actor=principal
                )
                items = [_edge_response(row) for row in result.edges]
                return LineageEdgeListResponse(
                    lineage_id=lineage_id,
                    workspace_version=result.workspace.version,
                    items=items,
                    total=len(items),
                )
        except _WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error

    @router.post(
        "/api/v2/lineages/{lineage_id}/edges",
        response_model=LineageEdgeMutationResponse,
        status_code=201,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def create_edge(
        lineage_id: UUID,
        payload: LineageEdgeCreateRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> LineageEdgeMutationResponse:
        require_request_csrf(principal, csrf_token, secret)
        try:
            with session.begin():
                result = service.create_edge(
                    session,
                    lineage_id=lineage_id,
                    expected_version=payload.expected_workspace_version,
                    actor=principal,
                    parent_compound_id=payload.parent_compound_id,
                    child_compound_id=payload.child_compound_id,
                    relation_type=payload.relation_type,
                    modification_summary=payload.modification_summary,
                    review_status=payload.review_status,
                )
                return LineageEdgeMutationResponse(
                    edge=_edge_response(result.edge),
                    workspace_version=result.workspace.version,
                )
        except _WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error
        except _DOMAIN_ERRORS as error:
            raise _domain_error(error) from error

    @router.patch(
        "/api/v2/lineage-edges/{edge_id}",
        response_model=LineageEdgeMutationResponse,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def update_edge(
        edge_id: UUID,
        payload: LineageEdgeUpdateRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> LineageEdgeMutationResponse:
        require_request_csrf(principal, csrf_token, secret)
        try:
            with session.begin():
                result = service.update_edge(
                    session,
                    edge_id=edge_id,
                    expected_version=payload.expected_workspace_version,
                    actor=principal,
                    updates=payload.updates(),
                )
                return LineageEdgeMutationResponse(
                    edge=_edge_response(result.edge),
                    workspace_version=result.workspace.version,
                )
        except _WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error
        except _DOMAIN_ERRORS as error:
            raise _domain_error(error) from error

    @router.put(
        "/api/v2/lineages/{lineage_id}/edges/order",
        response_model=LineageEdgeListResponse,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def reorder_edges(
        lineage_id: UUID,
        payload: LineageEdgeReorderRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> LineageEdgeListResponse:
        require_request_csrf(principal, csrf_token, secret)
        try:
            with session.begin():
                result = service.reorder_edges(
                    session,
                    lineage_id=lineage_id,
                    expected_version=payload.expected_workspace_version,
                    actor=principal,
                    edge_ids=payload.edge_ids,
                )
                items = [_edge_response(row) for row in result.edges]
                return LineageEdgeListResponse(
                    lineage_id=lineage_id,
                    workspace_version=result.workspace.version,
                    items=items,
                    total=len(items),
                )
        except _WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error
        except _DOMAIN_ERRORS as error:
            raise _domain_error(error) from error

    @router.delete(
        "/api/v2/lineage-edges/{edge_id}", response_model=DeletedResponse
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def delete_edge(
        edge_id: UUID,
        payload: WorkspaceVersionRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> DeletedResponse:
        require_request_csrf(principal, csrf_token, secret)
        try:
            with session.begin():
                workspace = service.delete_edge(
                    session,
                    edge_id=edge_id,
                    expected_version=payload.expected_workspace_version,
                    actor=principal,
                )
                return DeletedResponse(
                    deleted_id=edge_id, workspace_version=workspace.version
                )
        except _WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error
        except _DOMAIN_ERRORS as error:
            raise _domain_error(error) from error

    return router


__all__ = ["create_lineages_router"]
