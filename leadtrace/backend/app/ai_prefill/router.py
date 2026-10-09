from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_prefill.models import AiExtractionRun, AiExtractionRunStatus
from app.ai_prefill.schemas import (
    AiExtractionRunResponse,
    AiPrefillStatusResponse,
)
from app.ai_prefill.service import (
    AiPrefillNotFoundError,
    AiPrefillService,
    AiPrefillUnavailableError,
)
from app.api.errors import APIError
from app.config import Settings
from app.database import get_db_session
from app.security.permissions import (
    RouteAccess,
    declare_route_access,
    require_permission,
    require_request_csrf,
)
from app.security.policies import Action, Principal
from app.workspaces.models import PaperWorkspace


AiPrefillDispatch = Callable[[UUID, UUID], None]


def _default_dispatch(run_id: UUID, dispatch_token: UUID) -> None:
    from app.ai_prefill.celery_tasks import dispatch_ai_prefill_run

    dispatch_ai_prefill_run(run_id, dispatch_token)


def _workspace_for_paper(session: Session, paper_id: UUID) -> PaperWorkspace:
    workspace = session.scalar(
        select(PaperWorkspace)
        .where(PaperWorkspace.paper_id == paper_id)
        .order_by(PaperWorkspace.created_at.desc(), PaperWorkspace.id.desc())
    )
    if workspace is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    return workspace


def _status(
    session: Session,
    service: AiPrefillService,
    workspace: PaperWorkspace,
) -> AiPrefillStatusResponse:
    latest = session.scalar(
        select(AiExtractionRun)
        .where(AiExtractionRun.workspace_id == workspace.id)
        .order_by(AiExtractionRun.queued_at.desc(), AiExtractionRun.id.desc())
        .limit(1)
    )
    blocked_reason = service.unavailable_reason(session, workspace=workspace)
    return AiPrefillStatusResponse(
        run=(AiExtractionRunResponse.from_model(latest) if latest else None),
        can_start=blocked_reason is None,
        blocked_reason=blocked_reason,
    )


def create_ai_prefill_router(
    settings: Settings,
    dispatch: AiPrefillDispatch | None = None,
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v2/admin/papers",
        tags=["AI paper prefill"],
    )
    require_catalog_management = require_permission(Action.MANAGE_PAPER_CATALOG)
    service = AiPrefillService()
    dispatch_run = dispatch or _default_dispatch

    @router.get(
        "/{paper_id}/ai-prefill",
        response_model=AiPrefillStatusResponse,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_PAPER_CATALOG)
    def get_ai_prefill_status(
        paper_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_catalog_management),
    ) -> AiPrefillStatusResponse:
        del principal
        with session.begin():
            workspace = _workspace_for_paper(session, paper_id)
            status = _status(session, service, workspace)
            if settings.environment == "preview":
                status.can_start = False
                status.blocked_reason = "Preview requires candidate application"
            return status

    @router.post(
        "/{paper_id}/ai-prefill",
        response_model=AiPrefillStatusResponse,
        status_code=202,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_PAPER_CATALOG)
    def start_ai_prefill(
        paper_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_catalog_management),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> AiPrefillStatusResponse:
        try:
            with session.begin():
                require_request_csrf(
                    principal,
                    csrf_token,
                    settings.session_secret.get_secret_value(),
                )
                if settings.ai_task_worker_enabled:
                    raise AiPrefillUnavailableError("Use the Admin AI task console")
                if settings.environment == "preview":
                    raise AiPrefillUnavailableError(
                        "Preview requires candidate application"
                    )
                workspace = _workspace_for_paper(session, paper_id)
                queue_result = service.queue(
                    session,
                    workspace_id=workspace.id,
                    requested_by_id=principal.user_id,
                    engine=settings.ai_prefill_engine,
                    engine_version=settings.ai_prefill_engine_version,
                )
                response = _status(session, service, workspace)
        except AiPrefillNotFoundError as error:
            raise HTTPException(status_code=404, detail="Resource not found") from error
        except AiPrefillUnavailableError as error:
            raise APIError(
                409,
                "AI_PREFILL_UNAVAILABLE",
                str(error),
            ) from error

        run = queue_result.run
        if queue_result.created and run.status is AiExtractionRunStatus.QUEUED:
            if run.dispatch_token is None:
                raise RuntimeError("Queued AI extraction run has no dispatch token")
            run_id = run.id
            dispatch_token = run.dispatch_token
            try:
                dispatch_run(run_id, dispatch_token)
            except Exception as error:
                with session.begin():
                    queued = session.scalar(
                        select(AiExtractionRun)
                        .where(AiExtractionRun.id == run_id)
                        .execution_options(populate_existing=True)
                        .with_for_update()
                    )
                    if (
                        queued is not None
                        and queued.status is AiExtractionRunStatus.QUEUED
                        and queued.dispatch_token == dispatch_token
                    ):
                        queued.dispatched_at = None
                        queued.error_summary = (
                            "AI task dispatch failed; queued for retry"
                        )
                        queued.completed_at = None
                raise APIError(
                    503,
                    "AI_PREFILL_DISPATCH_FAILED",
                    "AI prefill could not be queued",
                ) from error
        return response

    return router


__all__ = ["AiPrefillDispatch", "create_ai_prefill_router"]
