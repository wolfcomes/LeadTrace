from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.errors import request_id_for
from app.database import get_db_session
from app.papers.repository import PaperListFilters
from app.papers.service import paper_detail_payload, paper_list_payload
from app.releases.service import get_current_release
from app.security.permissions import (
    RouteAccess,
    declare_route_access,
    require_published_data,
)
from app.security.policies import Action, Principal


SortOrder = Literal["manifest", "paper_id", "-paper_id", "title", "-title"]
BooleanFilter = Literal["true", "false"]


def create_papers_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1/papers", tags=["published papers"])

    @router.get("")
    @declare_route_access(RouteAccess.PERMISSION, Action.READ_PUBLISHED_DATA)
    def list_papers(
        request: Request,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
        search: str | None = Query(default=None, min_length=1, max_length=255),
        doi: str | None = Query(default=None, min_length=1, max_length=255),
        target: str | None = Query(default=None, min_length=1, max_length=255),
        has_lineage: BooleanFilter | None = None,
        relation_status: str | None = Query(default=None, max_length=80),
        structure_state: str | None = Query(default=None, max_length=32),
        review_status: str | None = Query(default=None, max_length=80),
        sort: SortOrder = "manifest",
        session: Session = Depends(get_db_session),
        _: Principal = Depends(require_published_data),
    ) -> dict[str, object]:
        filters = PaperListFilters(
            search=search,
            doi=doi,
            target=target,
            has_lineage=has_lineage,
            relation_status=relation_status,
            structure_state=structure_state,
            review_status=review_status,
            sort=sort,
        )
        with session.begin():
            release = get_current_release(session)
            return paper_list_payload(
                session,
                release,
                filters,
                page=page,
                page_size=page_size,
                request_id=request_id_for(request),
            )

    @router.get("/{paper_id}")
    @declare_route_access(RouteAccess.PERMISSION, Action.READ_PUBLISHED_DATA)
    def paper_detail(
        paper_id: UUID,
        request: Request,
        session: Session = Depends(get_db_session),
        _: Principal = Depends(require_published_data),
    ) -> dict[str, object]:
        with session.begin():
            release = get_current_release(session)
            return paper_detail_payload(
                session,
                release,
                paper_id,
                request_id=request_id_for(request),
            )

    return router
