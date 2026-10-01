from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.errors import APIError
from app.config import Settings
from app.database import get_db_session
from app.evidence.models import EdgeEvidenceLink, Evidence
from app.evidence.schemas import (
    DeletedResponse,
    EvidenceCreateRequest,
    EvidenceLinkCreateRequest,
    EvidenceLinkListResponse,
    EvidenceLinkMutationResponse,
    EvidenceLinkResponse,
    EvidenceLinkUpdateRequest,
    EvidenceListResponse,
    EvidenceMutationResponse,
    EvidenceResponse,
    EvidenceUpdateRequest,
    WorkspaceVersionRequest,
)
from app.evidence.service import (
    EvidenceConflictError,
    EvidenceReferencedError,
    EvidenceService,
    EvidenceValidationError,
)
from app.security.permissions import (
    RouteAccess,
    declare_route_access,
    get_authenticated_principal,
    require_request_csrf,
)
from app.security.policies import Action, Principal
from app.structure_images.schemas import BBoxResponse
from app.workspaces.service import (
    WorkspaceForbiddenError,
    WorkspaceNotFoundError,
    WorkspaceReadOnlyError,
    WorkspaceVersionConflictError,
)


def _evidence_response(row: Evidence) -> EvidenceResponse:
    bbox = None
    if row.x0 is not None:
        bbox = BBoxResponse(
            x0=float(row.x0),
            y0=float(row.y0),
            x1=float(row.x1),
            y1=float(row.y1),
        )
    return EvidenceResponse(
        id=row.id,
        paper_id=row.paper_id,
        workspace_id=row.workspace_id,
        kind=row.kind,
        source_sha256=row.source_sha256,
        page_number=row.page_number,
        bbox=bbox,
        quoted_text=row.quoted_text,
        caption=row.caption,
        crop_asset_id=row.crop_asset_id,
        reviewer_note=row.reviewer_note,
    )


def _link_response(row: EdgeEvidenceLink) -> EvidenceLinkResponse:
    return EvidenceLinkResponse(
        id=row.id,
        paper_id=row.paper_id,
        workspace_id=row.workspace_id,
        edge_id=row.edge_id,
        evidence_id=row.evidence_id,
        role=row.role,
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
    if isinstance(error, EvidenceValidationError):
        return APIError(422, "EVIDENCE_INVALID", str(error))
    if isinstance(error, EvidenceReferencedError):
        return APIError(
            409,
            "EVIDENCE_REFERENCED",
            "Evidence is referenced by scientific records",
            details={
                "edge_references": error.edge_references,
                "activity_references": error.activity_references,
                **({"highlight_references": error.highlight_references} if error.highlight_references else {}),
            },
        )
    if isinstance(error, (EvidenceConflictError, IntegrityError)):
        return APIError(
            409,
            "EVIDENCE_CONFLICT",
            "Evidence conflicts with an existing record",
        )
    raise error


_WORKSPACE_ERRORS = (
    WorkspaceForbiddenError,
    WorkspaceNotFoundError,
    WorkspaceReadOnlyError,
    WorkspaceVersionConflictError,
)
_DOMAIN_ERRORS = (
    EvidenceValidationError,
    EvidenceReferencedError,
    EvidenceConflictError,
    IntegrityError,
)


def create_evidence_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["evidence"])
    service = EvidenceService()
    secret = settings.session_secret.get_secret_value()

    @router.get(
        "/api/v2/workspaces/{workspace_id}/evidence",
        response_model=EvidenceListResponse,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.READ_DRAFT)
    def list_evidence(
        workspace_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> EvidenceListResponse:
        try:
            with session.begin():
                result = service.list_evidence(
                    session, workspace_id=workspace_id, actor=principal
                )
                items = [_evidence_response(row) for row in result.evidence]
                return EvidenceListResponse(
                    workspace_id=workspace_id,
                    workspace_version=result.workspace.version,
                    items=items,
                    total=len(items),
                )
        except _WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error

    @router.post(
        "/api/v2/workspaces/{workspace_id}/evidence",
        response_model=EvidenceMutationResponse,
        status_code=201,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def create_evidence(
        workspace_id: UUID,
        payload: EvidenceCreateRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> EvidenceMutationResponse:
        require_request_csrf(principal, csrf_token, secret)
        try:
            with session.begin():
                result = service.create_evidence(
                    session,
                    workspace_id=workspace_id,
                    expected_version=payload.expected_workspace_version,
                    actor=principal,
                    kind=payload.kind,
                    source_sha256=payload.source_sha256,
                    page_number=payload.page_number,
                    bbox=payload.bbox,
                    quoted_text=payload.quoted_text,
                    caption=payload.caption,
                    reviewer_note=payload.reviewer_note,
                )
                return EvidenceMutationResponse(
                    evidence=_evidence_response(result.evidence),
                    workspace_version=result.workspace.version,
                )
        except _WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error
        except _DOMAIN_ERRORS as error:
            raise _domain_error(error) from error

    @router.patch(
        "/api/v2/evidence/{evidence_id}", response_model=EvidenceMutationResponse
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def update_evidence(
        evidence_id: UUID,
        payload: EvidenceUpdateRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> EvidenceMutationResponse:
        require_request_csrf(principal, csrf_token, secret)
        try:
            with session.begin():
                result = service.update_evidence(
                    session,
                    evidence_id=evidence_id,
                    expected_version=payload.expected_workspace_version,
                    actor=principal,
                    updates=payload.updates(),
                )
                return EvidenceMutationResponse(
                    evidence=_evidence_response(result.evidence),
                    workspace_version=result.workspace.version,
                )
        except _WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error
        except _DOMAIN_ERRORS as error:
            raise _domain_error(error) from error

    @router.delete(
        "/api/v2/evidence/{evidence_id}", response_model=DeletedResponse
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def delete_evidence(
        evidence_id: UUID,
        payload: WorkspaceVersionRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> DeletedResponse:
        require_request_csrf(principal, csrf_token, secret)
        try:
            with session.begin():
                workspace = service.delete_evidence(
                    session,
                    evidence_id=evidence_id,
                    expected_version=payload.expected_workspace_version,
                    actor=principal,
                )
                return DeletedResponse(
                    deleted_id=evidence_id, workspace_version=workspace.version
                )
        except _WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error
        except _DOMAIN_ERRORS as error:
            raise _domain_error(error) from error

    @router.get(
        "/api/v2/lineage-edges/{edge_id}/evidence-links",
        response_model=EvidenceLinkListResponse,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.READ_DRAFT)
    def list_links(
        edge_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> EvidenceLinkListResponse:
        try:
            with session.begin():
                result = service.list_links(session, edge_id=edge_id, actor=principal)
                items = [_link_response(row) for row in result.links]
                return EvidenceLinkListResponse(
                    edge_id=edge_id,
                    workspace_version=result.workspace.version,
                    items=items,
                    total=len(items),
                )
        except _WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error

    @router.post(
        "/api/v2/lineage-edges/{edge_id}/evidence-links",
        response_model=EvidenceLinkMutationResponse,
        status_code=201,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def create_link(
        edge_id: UUID,
        payload: EvidenceLinkCreateRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> EvidenceLinkMutationResponse:
        require_request_csrf(principal, csrf_token, secret)
        try:
            with session.begin():
                result = service.create_link(
                    session,
                    edge_id=edge_id,
                    expected_version=payload.expected_workspace_version,
                    actor=principal,
                    evidence_id=payload.evidence_id,
                    role=payload.role,
                )
                return EvidenceLinkMutationResponse(
                    link=_link_response(result.link),
                    workspace_version=result.workspace.version,
                )
        except _WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error
        except _DOMAIN_ERRORS as error:
            raise _domain_error(error) from error

    @router.patch(
        "/api/v2/edge-evidence-links/{link_id}",
        response_model=EvidenceLinkMutationResponse,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def update_link(
        link_id: UUID,
        payload: EvidenceLinkUpdateRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> EvidenceLinkMutationResponse:
        require_request_csrf(principal, csrf_token, secret)
        try:
            with session.begin():
                result = service.update_link(
                    session,
                    link_id=link_id,
                    expected_version=payload.expected_workspace_version,
                    actor=principal,
                    role=payload.role,
                )
                return EvidenceLinkMutationResponse(
                    link=_link_response(result.link),
                    workspace_version=result.workspace.version,
                )
        except _WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error
        except _DOMAIN_ERRORS as error:
            raise _domain_error(error) from error

    @router.delete(
        "/api/v2/edge-evidence-links/{link_id}", response_model=DeletedResponse
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def delete_link(
        link_id: UUID,
        payload: WorkspaceVersionRequest,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> DeletedResponse:
        require_request_csrf(principal, csrf_token, secret)
        try:
            with session.begin():
                workspace = service.delete_link(
                    session,
                    link_id=link_id,
                    expected_version=payload.expected_workspace_version,
                    actor=principal,
                )
                return DeletedResponse(
                    deleted_id=link_id, workspace_version=workspace.version
                )
        except _WORKSPACE_ERRORS as error:
            raise _workspace_error(error) from error
        except _DOMAIN_ERRORS as error:
            raise _domain_error(error) from error

    return router


__all__ = ["create_evidence_router"]
