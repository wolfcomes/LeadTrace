from __future__ import annotations

from collections.abc import Iterator
from typing import BinaryIO
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.assets.models import AssetCategory, AssetIntegrityState
from app.assets.repository import AssetRepository
from app.assets.schemas import AssetResponse
from app.assets.service import AssetService
from app.assets.storage import LocalAssetStore
from app.database import get_db_session
from app.security.permissions import (
    RouteAccess,
    declare_route_access,
    get_authenticated_principal,
    require_permission,
)
from app.security.policies import Action, Principal
from app.structure_images.models import StructureSourceImage


def _stream_snapshot(snapshot: BinaryIO) -> Iterator[bytes]:
    try:
        while chunk := snapshot.read(1024 * 1024):
            yield chunk
    finally:
        snapshot.close()


def create_assets_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1/assets", tags=["assets"])
    repository = AssetRepository()
    require_file_management = require_permission(Action.MANAGE_FILES)

    @router.get("/{asset_id}/content")
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def get_asset_content(
        asset_id: UUID,
        request: Request,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> StreamingResponse:
        settings = request.app.state.settings
        snapshot: BinaryIO | None = None
        try:
            with session.begin():
                asset = repository.get(session, asset_id)
                if (
                    asset is None
                    or asset.integrity_state is not AssetIntegrityState.VERIFIED
                ):
                    raise HTTPException(status_code=404, detail="Asset not found")
                if (
                    asset.derivation_metadata.get("visibility_scope")
                    == "structure_source_image"
                    or session.scalar(
                        select(StructureSourceImage.id)
                        .where(StructureSourceImage.crop_asset_id == asset.id)
                        .limit(1)
                    )
                    is not None
                ):
                    raise HTTPException(status_code=404, detail="Asset not found")
                if (
                    asset.category is AssetCategory.RDKIT_STRUCTURE
                    and principal.role.value != "admin"
                ):
                    raise HTTPException(status_code=404, detail="Asset not found")
                if (
                    principal.role.value == "visitor"
                    and asset.access_level.value != "visitor"
                ):
                    raise HTTPException(status_code=404, detail="Asset not found")
                if (
                    principal.role.value == "reviewer"
                    and asset.access_level.value == "admin"
                ):
                    raise HTTPException(status_code=403, detail="Permission denied")
                store = LocalAssetStore(
                    settings.asset_root,
                    source_roots=settings.source_roots,
                )
                snapshot = AssetService.open_verified_content(asset, store)
                media_type = asset.mime_type
                content_length = asset.byte_size
                filename = asset.original_filename.replace("\r", "").replace("\n", "")
        except BaseException:
            if snapshot is not None:
                snapshot.close()
            raise
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Asset not found")
        encoded_filename = quote(filename)
        if encoded_filename == filename:
            content_disposition = f'attachment; filename="{filename}"'
        else:
            content_disposition = f"attachment; filename*=utf-8''{encoded_filename}"
        return StreamingResponse(
            content=_stream_snapshot(snapshot),
            media_type=media_type,
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": content_disposition,
                "Content-Length": str(content_length),
            },
        )

    @router.get("/{asset_id}", response_model=AssetResponse)
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_FILES)
    def get_asset(
        asset_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_file_management),
    ) -> AssetResponse:
        with session.begin():
            asset = repository.get(session, asset_id)
            if asset is None:
                raise HTTPException(status_code=404, detail="Asset not found")
            return AssetResponse.model_validate(asset)

    return router
