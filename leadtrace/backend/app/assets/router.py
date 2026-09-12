from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.assets.models import AssetIntegrityState
from app.assets.repository import AssetRepository
from app.assets.schemas import AssetResponse
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
    ) -> FileResponse:
        settings = request.app.state.settings
        with session.begin():
            asset = repository.get(session, asset_id)
            if asset is None or asset.integrity_state is not AssetIntegrityState.VERIFIED:
                raise HTTPException(status_code=404, detail="Asset not found")
            if principal.role.value == "visitor" and asset.access_level.value != "visitor":
                raise HTTPException(status_code=404, detail="Asset not found")
            if principal.role.value == "reviewer" and asset.access_level.value == "admin":
                raise HTTPException(status_code=403, detail="Permission denied")
            store = LocalAssetStore(
                settings.asset_root,
                source_roots=settings.source_roots,
            )
            try:
                inspected = store.inspect(asset.storage_key)
            except (OSError, ValueError, FileNotFoundError):
                asset.integrity_state = AssetIntegrityState.MISSING
                raise HTTPException(status_code=404, detail="Asset not found") from None
            if inspected.sha256 != asset.sha256 or inspected.byte_size != asset.byte_size:
                asset.integrity_state = AssetIntegrityState.CORRUPT
                raise HTTPException(status_code=404, detail="Asset not found")
            path = inspected.path
            filename = asset.original_filename.replace("\r", "").replace("\n", "")
        return FileResponse(
            path,
            media_type=asset.mime_type,
            filename=filename,
            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
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
