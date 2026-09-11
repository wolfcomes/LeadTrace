from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.errors import request_id_for
from app.database import get_db_session
from app.releases.service import PublishedRelease, get_current_release
from app.security.permissions import (
    RouteAccess,
    declare_route_access,
    require_published_data,
)
from app.security.policies import Action, Principal


def create_releases_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1/published", tags=["published data"])

    @router.get("/overview")
    @declare_route_access(RouteAccess.PERMISSION, Action.READ_PUBLISHED_DATA)
    def published_overview(
        request: Request,
        session: Session = Depends(get_db_session),
        _: Principal = Depends(require_published_data),
    ) -> dict[str, object]:
        with session.begin():
            release = get_current_release(session)
            metadata = PublishedRelease.from_model(release)
        return {
            "request_id": request_id_for(request),
            "release": {
                "id": str(metadata.id),
                "key": metadata.key,
                "title": metadata.title,
                "published_at": metadata.published_at.isoformat(),
            },
            "metrics": metadata.metrics,
        }

    return router
