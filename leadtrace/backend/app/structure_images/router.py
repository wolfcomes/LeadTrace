from __future__ import annotations

from collections.abc import Iterator
from typing import BinaryIO
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.assets.models import (
    Asset,
    AssetAccessLevel,
    AssetCategory,
    AssetIntegrityState,
)
from app.assets.responses import SnapshotStreamingResponse
from app.assets.service import AssetService
from app.assets.storage import LocalAssetStore
from app.api.errors import APIError
from app.catalog.models import PaperSource, PaperSourceIntegrityState
from app.config import Settings
from app.database import get_db_session
from app.papers.models import Paper
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
    crop_request_for_source_image,
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
        diagnostic = getattr(getattr(error, "orig", None), "diag", None)
        if getattr(diagnostic, "constraint_name", None) == "uq_structure_source_images_compound_occurrence":
            return APIError(409, "STRUCTURE_SOURCE_IMAGE_DUPLICATE", "This PDF occurrence is already captured for the Compound")
    raise error


def _persist_integrity_failure(
    session: Session,
    error: StructureSourceImageValidationError,
) -> None:
    if error.integrity_failure is None:
        return
    asset_id, source_id, state = error.integrity_failure
    with session.begin():
        asset = session.get(Asset, asset_id)
        source = session.get(PaperSource, source_id)
        if asset is not None:
            asset.integrity_state = state
        if source is not None:
            source.integrity_state = PaperSourceIntegrityState(state.value)


def _stream_snapshot(snapshot: BinaryIO) -> Iterator[bytes]:
    try:
        while chunk := snapshot.read(1024 * 1024):
            yield chunk
    finally:
        snapshot.close()


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
            if isinstance(error, StructureSourceImageValidationError):
                _persist_integrity_failure(session, error)
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

    @router.get("/api/v2/structure-source-images/{source_image_id}/content")
    @declare_route_access(RouteAccess.PERMISSION, Action.READ_DRAFT)
    def get_source_image_content(
        source_image_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> StreamingResponse:
        snapshot: BinaryIO | None = None
        media_type = "image/png"
        content_length = 0
        filename = "source-crop.png"
        try:
            with session.begin():
                result = service.get_source_image(
                    session,
                    source_image_id=source_image_id,
                    actor=principal,
                )
                asset = (
                    session.get(Asset, result.source_image.crop_asset_id)
                    if result.source_image.crop_asset_id is not None
                    else None
                )
                expected_source_asset_id = session.scalar(
                    select(PaperSource.asset_id)
                    .join(Paper, Paper.source_id == PaperSource.id)
                    .where(Paper.id == result.source_image.paper_id)
                )
                expected_crop_input_hash = crop_request_for_source_image(
                    result.source_image
                ).input_hash()
                if (
                    asset is not None
                    and asset.category is AssetCategory.EVIDENCE_CROP
                    and asset.access_level is AssetAccessLevel.REVIEWER
                    and asset.integrity_state is AssetIntegrityState.VERIFIED
                    and asset.mime_type == "image/png"
                    and asset.source_asset_id == expected_source_asset_id
                    and asset.derivation_metadata.get("crop_input_hash")
                    == expected_crop_input_hash
                ):
                    snapshot = AssetService.open_verified_content(
                        asset,
                        LocalAssetStore(
                            settings.asset_root,
                            source_roots=settings.source_roots,
                        ),
                    )
                    media_type = asset.mime_type
                    content_length = asset.byte_size
                    filename = asset.original_filename.replace("\r", "").replace("\n", "")
        except (WorkspaceForbiddenError, WorkspaceNotFoundError):
            if snapshot is not None:
                snapshot.close()
            raise APIError(404, "RESOURCE_NOT_FOUND", "Resource not found") from None
        except BaseException:
            if snapshot is not None:
                snapshot.close()
            raise
        if snapshot is None:
            raise APIError(404, "RESOURCE_NOT_FOUND", "Resource not found")
        encoded_filename = quote(filename)
        disposition = (
            f'inline; filename="{filename}"'
            if encoded_filename == filename
            else f"inline; filename*=utf-8''{encoded_filename}"
        )
        return SnapshotStreamingResponse(
            snapshot=snapshot,
            content=_stream_snapshot(snapshot),
            media_type=media_type,
            headers={
                "Cache-Control": "private, no-store",
                "Content-Disposition": disposition,
                "Content-Length": str(content_length),
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.patch("/api/v2/structure-source-images/{source_image_id}", response_model=StructureSourceImageMutationResponse)
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def update_source_image(source_image_id: UUID, payload: StructureSourceImageUpdateRequest, csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"), session: Session = Depends(get_db_session), principal: Principal = Depends(get_authenticated_principal)) -> StructureSourceImageMutationResponse:
        require_request_csrf(principal, csrf_token, secret)
        try:
            with session.begin():
                result = service.update_source_image(session, source_image_id=source_image_id, expected_version=payload.expected_workspace_version, actor=principal, updates=payload.updates())
                return StructureSourceImageMutationResponse(source_image=_response(result.source_image), workspace_version=result.workspace.version)
        except (WorkspaceForbiddenError, WorkspaceNotFoundError, WorkspaceReadOnlyError, WorkspaceVersionConflictError, StructureSourceImageDuplicateError, StructureSourceImageValidationError, IntegrityError) as error:
            if isinstance(error, StructureSourceImageValidationError):
                _persist_integrity_failure(session, error)
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
            if isinstance(error, StructureSourceImageValidationError):
                _persist_integrity_failure(session, error)
            raise _error(error) from error

    return router


__all__ = ["create_structure_images_router"]
