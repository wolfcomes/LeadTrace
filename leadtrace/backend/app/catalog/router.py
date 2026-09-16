from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.errors import APIError, request_id_for
from app.auth.router import resolve_remote_address
from app.catalog.models import PaperSource
from app.catalog.schemas import PaperCatalogPage, PaperCatalogResponse
from app.config import Settings
from app.database import get_db_session
from app.papers.models import Paper
from app.security.permissions import (
    RouteAccess,
    declare_route_access,
    require_permission,
    require_request_csrf,
)
from app.security.policies import Action, Principal
from app.workspaces.assignment import (
    ActiveAssignmentError,
    AssignmentService,
    InvalidReviewerError,
    PaperNotFoundError,
    PaperSourceUnverifiedError,
    ReviewerNotFoundError,
)
from app.workspaces.schemas import AssignmentRequest, AssignmentResponse


def create_catalog_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v2/admin/papers", tags=["paper catalog"])
    require_catalog_management = require_permission(Action.MANAGE_PAPER_CATALOG)
    assignment_service = AssignmentService()

    @router.get("", response_model=PaperCatalogPage)
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_PAPER_CATALOG)
    def list_papers(
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_catalog_management),
    ) -> PaperCatalogPage:
        del principal
        with session.begin():
            total = int(session.scalar(select(func.count()).select_from(Paper)) or 0)
            rows = session.execute(
                select(Paper, PaperSource)
                .join(PaperSource, PaperSource.id == Paper.source_id)
                .order_by(Paper.paper_key, Paper.id)
                .limit(limit)
                .offset(offset)
            ).all()
        return PaperCatalogPage(
            items=[
                PaperCatalogResponse.from_models(paper, source)
                for paper, source in rows
            ],
            total=total,
            limit=limit,
            offset=offset,
        )

    @router.get("/{paper_id}", response_model=PaperCatalogResponse)
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_PAPER_CATALOG)
    def get_paper(
        paper_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_catalog_management),
    ) -> PaperCatalogResponse:
        del principal
        with session.begin():
            row = session.execute(
                select(Paper, PaperSource)
                .join(PaperSource, PaperSource.id == Paper.source_id)
                .where(Paper.id == paper_id)
            ).one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Resource not found")
        return PaperCatalogResponse.from_models(*row)

    @router.post(
        "/{paper_id}/assign",
        response_model=AssignmentResponse,
        status_code=201,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_PAPER_CATALOG)
    def assign_paper(
        paper_id: UUID,
        payload: AssignmentRequest,
        request: Request,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_catalog_management),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> AssignmentResponse:
        try:
            with session.begin():
                require_request_csrf(
                    principal,
                    csrf_token,
                    settings.session_secret.get_secret_value(),
                )
                result = assignment_service.assign(
                    session,
                    paper_id=paper_id,
                    reviewer_id=payload.reviewer_id,
                    admin_id=principal.user_id,
                    request_id=request_id_for(request),
                    ip_address=resolve_remote_address(request, settings),
                )
        except PaperNotFoundError as error:
            raise HTTPException(status_code=404, detail="Resource not found") from error
        except ReviewerNotFoundError as error:
            raise APIError(
                404,
                "REVIEWER_NOT_FOUND",
                "Reviewer not found",
            ) from error
        except InvalidReviewerError as error:
            raise APIError(422, "INVALID_REVIEWER", str(error)) from error
        except ActiveAssignmentError as error:
            raise APIError(409, "ACTIVE_ASSIGNMENT_EXISTS", str(error)) from error
        except PaperSourceUnverifiedError as error:
            raise APIError(409, "PAPER_SOURCE_UNVERIFIED", str(error)) from error
        return AssignmentResponse.from_models(
            result.task,
            result.workspace,
            result.sections,
        )

    return router


__all__ = ["create_catalog_router"]
