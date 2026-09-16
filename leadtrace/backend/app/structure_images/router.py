from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.errors import APIError
from app.config import Settings
from app.database import get_db_session
from app.security.permissions import RouteAccess, declare_route_access, get_authenticated_principal, require_request_csrf
from app.security.policies import Action, Principal
from app.structure_images.models import StructureSourceImage
from app.structure_images.schemas import (
    BBoxResponse,
    StructureSourceImageCreateRequest,
    StructureSourceImageDeleteResponse,
    StructureSourceImageListResponse,
    StructureSourceImageMutationResponse,
    StructureSourceImageResponse,
    StructureSourceImageUpdateRequest,
    WorkspaceVersionRequest,
)
from app.structure_images.service import (
    StructureSourceImageDuplicateError,
    StructureSourceImageService,
    StructureSourceImageValidationError,
)
from app.workspaces.service import WorkspaceForbiddenError, WorkspaceNotFoundError, WorkspaceReadOnlyError, WorkspaceVersionConflictError


def _response(source_image: StructureSourceImage) -> StructureSourceImageResponse:
    return StructureSourceImageResponse(
        id=source_image.id,
        paper_id=source_image.paper_id,
        workspace_id=source_image.workspace_id,
        compound_id=source_image.compound_id,
        source_sha256=source_image.source_sha256,
        page_number=source_image.page_number,
        bbox=BBoxResponse(x0=float(source_image.x0), y0=float(source_image.y0), x1=float(source_image.x1), y1=float(source_image.y1)),
        source_context=source_image.source_context,
        label=source_image.label,
        reviewer_note=source_image.reviewer_note,
        crop_status=source_image.crop_status,
        crop_asset_id=source_image.crop_asset_id,
    )


def _error(error: Exception) -> APIError | HTTPException:
    if isinstance(error, WorkspaceNotFoundError):
        return APIError(404, "RESOURCE_NOT_FOUND", "Resource not found")
    if isinstance(error, WorkspaceForbiddenError):
        return HTTPException(status_code=403, detail="Permission denied")
    if isinstance(error, WorkspaceVersionConflictError):
        return APIError(409, "WORKSPACE_VERSION_CONFLICT", "Workspace version changed", details={"expected_workspace_version": error.expected_version, "current_workspace_version": error.current_version})
    if isinstance(error, WorkspaceReadOnlyError):
        return APIError(409, "WORKSPACE_READ_ONLY", "Workspace is read-only", details={"workspace_state": error.state.value, "current_workspace_version": error.current_version})
    if isinstance(error, StructureSourceImageDuplicateError):
        return APIError(409, "STRUCTURE_SOURCE_IMAGE_DUPLICATE", "This PDF occurrence is already captured for the Compound")
    if isinstance(error, StructureSourceImageValidationError):
        code = "STRUCTURE_SOURCE_MISMATCH" if "SHA-256" in str(error) else "STRUCTURE_SOURCE_IMAGE_INVALID"
        return APIError(422, code, str(error))
    if isinstance(error, IntegrityError):
        return APIError(409, "STRUCTURE_SOURCE_IMAGE_DUPLICATE", "This PDF occurrence is already captured for the Compound")
    raise error


def create_structure_images_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["structure source images"])
    service = StructureSourceImageService(settings.asset_root, source_roots=settings.source_roots)
    secret = settings.session_secret.get_secret_value()

    @router.get("/api/v2/compounds/{compound_id}/source-images", response_model=StructureSourceImageListResponse)
    @declare_route_access(RouteAccess.PERMISSION, Action.READ_DRAFT)
    def list_source_images(compound_id: UUID, session: Session = Depends(get_db_session), principal: Principal = Depends(get_authenticated_principal)) -> StructureSourceImageListResponse:
        try:
            with session.begin():
                result = service.list_source_images(session, compound_id=compound_id, actor=principal)
                items = [_response(item) for item in result.source_images]
                return StructureSourceImageListResponse(compound_id=compound_id, workspace_version=result.workspace.version, items=items, total=len(items))
        except (WorkspaceForbiddenError, WorkspaceNotFoundError) as error:
            raise _error(error) from error

    @router.post("/api/v2/compounds/{compound_id}/source-images", status_code=201, response_model=StructureSourceImageMutationResponse)
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def create_source_image(compound_id: UUID, payload: StructureSourceImageCreateRequest, csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"), session: Session = Depends(get_db_session), principal: Principal = Depends(get_authenticated_principal)) -> StructureSourceImageMutationResponse:
        require_request_csrf(principal, csrf_token, secret)
        try:
            with session.begin():
                result = service.create_source_image(session, compound_id=compound_id, expected_version=payload.expected_workspace_version, actor=principal, source_sha256=payload.source_sha256, page_number=payload.page_number, bbox=payload.bbox, source_context=payload.source_context, label=payload.label, reviewer_note=payload.reviewer_note)
                return StructureSourceImageMutationResponse(source_image=_response(result.source_image), workspace_version=result.workspace.version)
        except (WorkspaceForbiddenError, WorkspaceNotFoundError, WorkspaceReadOnlyError, WorkspaceVersionConflictError, StructureSourceImageDuplicateError, StructureSourceImageValidationError, IntegrityError) as error:
            raise _error(error) from error

    @router.get("/api/v2/structure-source-images/{source_image_id}", response_model=StructureSourceImageMutationResponse)
    @declare_route_access(RouteAccess.PERMISSION, Action.READ_DRAFT)
    def get_source_image(source_image_id: UUID, session: Session = Depends(get_db_session), principal: Principal = Depends(get_authenticated_principal)) -> StructureSourceImageMutationResponse:
        try:
            with session.begin():
                result = service.get_source_image(session, source_image_id=source_image_id, actor=principal)
                return StructureSourceImageMutationResponse(source_image=_response(result.source_image), workspace_version=result.workspace.version)
        except (WorkspaceForbiddenError, WorkspaceNotFoundError) as error:
            raise _error(error) from error

    @router.patch("/api/v2/structure-source-images/{source_image_id}", response_model=StructureSourceImageMutationResponse)
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def update_source_image(source_image_id: UUID, payload: StructureSourceImageUpdateRequest, csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"), session: Session = Depends(get_db_session), principal: Principal = Depends(get_authenticated_principal)) -> StructureSourceImageMutationResponse:
        require_request_csrf(principal, csrf_token, secret)
        try:
            with session.begin():
                result = service.update_source_image(session, source_image_id=source_image_id, expected_version=payload.expected_workspace_version, actor=principal, updates=payload.updates())
                return StructureSourceImageMutationResponse(source_image=_response(result.source_image), workspace_version=result.workspace.version)
        except (WorkspaceForbiddenError, WorkspaceNotFoundError, WorkspaceReadOnlyError, WorkspaceVersionConflictError, StructureSourceImageDuplicateError, StructureSourceImageValidationError, IntegrityError) as error:
            raise _error(error) from error

    @router.delete("/api/v2/structure-source-images/{source_image_id}", response_model=StructureSourceImageDeleteResponse)
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def delete_source_image(source_image_id: UUID, payload: WorkspaceVersionRequest, csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"), session: Session = Depends(get_db_session), principal: Principal = Depends(get_authenticated_principal)) -> StructureSourceImageDeleteResponse:
        require_request_csrf(principal, csrf_token, secret)
        try:
            with session.begin():
                workspace = service.delete_source_image(session, source_image_id=source_image_id, expected_version=payload.expected_workspace_version, actor=principal)
                return StructureSourceImageDeleteResponse(deleted_source_image_id=source_image_id, workspace_version=workspace.version)
        except (WorkspaceForbiddenError, WorkspaceNotFoundError, WorkspaceReadOnlyError, WorkspaceVersionConflictError) as error:
            raise _error(error) from error

    @router.post("/api/v2/structure-source-images/{source_image_id}/retry", response_model=StructureSourceImageMutationResponse)
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def retry_source_image(source_image_id: UUID, payload: WorkspaceVersionRequest, csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"), session: Session = Depends(get_db_session), principal: Principal = Depends(get_authenticated_principal)) -> StructureSourceImageMutationResponse:
        require_request_csrf(principal, csrf_token, secret)
        try:
            with session.begin():
                result = service.retry_crop(session, source_image_id=source_image_id, expected_version=payload.expected_workspace_version, actor=principal)
                return StructureSourceImageMutationResponse(source_image=_response(result.source_image), workspace_version=result.workspace.version)
        except (WorkspaceForbiddenError, WorkspaceNotFoundError, WorkspaceReadOnlyError, WorkspaceVersionConflictError, StructureSourceImageValidationError) as error:
            raise _error(error) from error

    return router


__all__ = ["create_structure_images_router"]
