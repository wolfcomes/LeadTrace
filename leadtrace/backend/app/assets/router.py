from __future__ import annotations

from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

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
    ) -> Response:
        settings = request.app.state.settings
        content: bytes | None = None
        with session.begin():
            asset = repository.get(session, asset_id)
            if asset is None or asset.integrity_state is not AssetIntegrityState.VERIFIED:
                raise HTTPException(status_code=404, detail="Asset not found")
            if (
                asset.category is AssetCategory.RDKIT_STRUCTURE
                and principal.role.value != "admin"
            ):
                raise HTTPException(status_code=404, detail="Asset not found")
            if principal.role.value == "visitor" and asset.access_level.value != "visitor":
                raise HTTPException(status_code=404, detail="Asset not found")
            if principal.role.value == "reviewer" and asset.access_level.value == "admin":
                raise HTTPException(status_code=403, detail="Permission denied")
            store = LocalAssetStore(
                settings.asset_root,
                source_roots=settings.source_roots,
            )
            content = AssetService.read_verified_content(asset, store)
            media_type = asset.mime_type
            filename = asset.original_filename.replace("\r", "").replace("\n", "")
        if content is None:
            raise HTTPException(status_code=404, detail="Asset not found")
        encoded_filename = quote(filename)
        if encoded_filename == filename:
            content_disposition = f'attachment; filename="{filename}"'
        else:
            content_disposition = f"attachment; filename*=utf-8''{encoded_filename}"
        return Response(
            content=content,
            media_type=media_type,
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": content_disposition,
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
