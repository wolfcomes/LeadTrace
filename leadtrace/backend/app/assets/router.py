from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.assets.repository import AssetRepository
from app.assets.schemas import AssetResponse
from app.database import get_db_session
from app.security.permissions import RouteAccess, declare_route_access, require_permission
from app.security.policies import Action, Principal


def create_assets_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1/assets", tags=["assets"])
    repository = AssetRepository()
    require_file_management = require_permission(Action.MANAGE_FILES)

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
