from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.assets.storage import LocalAssetStore
from app.config import Settings
from app.database import get_db_session
from app.documents.service import DocumentKind, DocumentNotFound, DocumentService
from app.jobs.models import (
    CropJob,
    CropJobRetryOperation,
    CropJobStatus,
    CropJobSubscription,
)
from app.jobs.reconciler import JobReconciler
from app.jobs.service import (
    PDF_RENDERER_VERSION,
    CropRequest,
    CropService,
    CropValidationError,
)
from app.maintenance.service import MaintenanceConflict, MaintenanceService
from app.reviews.models import ReviewTask, ReviewTaskStatus
from app.security.permissions import (
    RouteAccess,
    declare_route_access,
    get_authenticated_principal,
    require_permission,
    require_request_csrf,
)
from app.security.policies import Action, Principal
from app.users.models import UserRole
from app.visual_objects.regions import RegionService, RegionValidationError


class MaintenanceUpdate(BaseModel):
    active: bool
    reason: str = Field(min_length=1, max_length=2000)
    expected_end: datetime | None = None

    @model_validator(mode="after")
    def validate_expected_end(self) -> "MaintenanceUpdate":
        if self.active and self.expected_end is None:
            raise ValueError("expected_end is required when enabling maintenance")
        return self


class CropJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: DocumentKind = DocumentKind.ARTICLE
    padding: int = Field(default=0, ge=0, le=1000)
    dpi: int = Field(default=300, ge=72, le=1200)


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def _status_payload(service: MaintenanceService, session: Session) -> dict[str, object]:
    status = service.status(session)
    return {
        "active": status.active,
        "reason": status.reason,
        "started_at": _timestamp(status.started_at),
        "expected_end": _timestamp(status.expected_end_at),
        "started_by_id": (
            str(status.started_by_id) if status.started_by_id is not None else None
        ),
        "allowed_operations": [
            "read_published_data",
            "inspect_system_health",
            "disable_maintenance_mode",
        ],
    }


def _job_payload(job: CropJob) -> dict[str, object]:
    return {
        "id": str(job.id),
        "status": job.status.value,
        "input_hash": job.input_hash,
        "source_pdf_sha256": job.source_pdf_sha256,
        "page_number": job.page_number,
        "error_code": (
            "CROP_JOB_EXECUTION_FAILED" if job.error_message is not None else None
        ),
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "asset_id": str(job.asset_id) if job.asset_id else None,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "dispatched_at": job.dispatched_at.isoformat() if job.dispatched_at else None,
        "heartbeat_at": job.heartbeat_at.isoformat() if job.heartbeat_at else None,
        "superseded_by_id": (
            str(job.superseded_by_id) if job.superseded_by_id else None
        ),
    }


def _reviewer_job_payload(job: CropJob) -> dict[str, object]:
    return {
        "id": str(job.id),
        "status": job.status.value,
        "asset_id": str(job.asset_id) if job.asset_id else None,
        "error_code": (
            "CROP_JOB_EXECUTION_FAILED" if job.error_message is not None else None
        ),
        "error_message": job.error_message,
    }


def create_jobs_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1/admin", tags=["operations"])
    require_admin = require_permission(Action.MANAGE_ACCOUNTS)
    service = MaintenanceService()

    @router.get("/jobs", response_model=list[dict[str, object]])
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_ACCOUNTS)
    def list_jobs(
        status: CropJobStatus | None = None,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_admin),
    ) -> list[dict[str, object]]:
        del principal
        with session.begin():
            statement = select(CropJob).order_by(CropJob.created_at.desc())
            if status is not None:
                statement = statement.where(CropJob.status == status)
            return [_job_payload(job) for job in session.scalars(statement)]

    @router.post("/jobs/{job_id}/retry")
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_ACCOUNTS)
    def retry_job(
        job_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_admin),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, object]:
        require_request_csrf(
            principal,
            csrf_token,
            settings.session_secret.get_secret_value(),
        )
        operation_key = (idempotency_key or "").strip()
        if not operation_key or len(operation_key) > 200:
            raise HTTPException(
                status_code=422,
                detail="Idempotency-Key must contain 1 to 200 characters",
            )
        with session.begin():
            job = session.scalar(
                select(CropJob).where(CropJob.id == job_id).with_for_update()
            )
            if job is None:
                raise HTTPException(status_code=404, detail="Job not found")
            existing = session.scalar(
                select(CropJobRetryOperation).where(
                    CropJobRetryOperation.job_id == job_id,
                    CropJobRetryOperation.actor_id == principal.user_id,
                    CropJobRetryOperation.idempotency_key == operation_key,
                )
            )
            if existing is not None:
                return _job_payload(job)
            attempt_count_before = job.attempt_count
            try:
                job = JobReconciler().retry_failed(session, job_id=job_id)
            except ValueError as error:
                raise HTTPException(status_code=409, detail=str(error)) from error
            session.add(
                CropJobRetryOperation(
                    job_id=job.id,
                    actor_id=principal.user_id,
                    idempotency_key=operation_key,
                    attempt_count_before=attempt_count_before,
                    max_attempts_after=job.max_attempts,
                )
            )
            session.flush()
            payload = _job_payload(job)
        return payload

    @router.get("/maintenance")
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_ACCOUNTS)
    def maintenance_status(
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_admin),
    ) -> dict[str, object]:
        del principal
        with session.begin():
            return _status_payload(service, session)

    @router.put("/maintenance")
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_ACCOUNTS)
    def update_maintenance(
        payload: MaintenanceUpdate,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_admin),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> dict[str, object]:
        require_request_csrf(
            principal,
            csrf_token,
            settings.session_secret.get_secret_value(),
        )
        try:
            with session.begin():
                if payload.active:
                    assert payload.expected_end is not None
                    service.activate(
                        session,
                        actor_id=principal.user_id,
                        reason=payload.reason,
                        expected_end_at=payload.expected_end,
                    )
                else:
                    service.deactivate(
                        session,
                        actor_id=principal.user_id,
                        reason=payload.reason,
                    )
                return _status_payload(service, session)
        except MaintenanceConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except IntegrityError as error:
            raise HTTPException(
                status_code=409,
                detail="Maintenance mode changed concurrently",
            ) from error

    return router


def create_crop_jobs_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["crop jobs"])
    region_service = RegionService()
    document_service = DocumentService()

    def require_crop_edit(
        principal: Principal = Depends(get_authenticated_principal),
    ) -> Principal:
        if principal.must_change_password or principal.role is UserRole.VISITOR:
            raise HTTPException(status_code=403, detail="Permission denied")
        return principal

    setattr(require_crop_edit, "__leadtrace_action__", Action.EDIT_DRAFT)

    @router.post(
        "/papers/{paper_id}/regions/{region_id}/crop-jobs",
        status_code=status.HTTP_202_ACCEPTED,
    )
    @declare_route_access(RouteAccess.PERMISSION, Action.EDIT_DRAFT)
    def enqueue_crop_job(
        paper_id: UUID,
        region_id: UUID,
        payload: CropJobCreate,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
        _permission: Principal = Depends(require_crop_edit),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> dict[str, object]:
        del _permission
        require_request_csrf(
            principal,
            csrf_token,
            settings.session_secret.get_secret_value(),
        )
        try:
            with session.begin():
                region = region_service.ensure_region_belongs_to_paper(
                    session,
                    region_id=region_id,
                    paper_id=paper_id,
                )
                revision = region_service._latest_revision(session, region.id)
                if revision is None or revision.is_tombstone:
                    raise RegionValidationError("Region has no active revision")
                bounds = (
                    revision.region_x0,
                    revision.region_y0,
                    revision.region_x1,
                    revision.region_y1,
                )
                if any(value is None for value in bounds):
                    raise RegionValidationError("Region revision has no crop bounds")
                page_number = revision.snapshot.get("page_number")
                if not isinstance(page_number, int):
                    raise RegionValidationError("Region revision has no page number")
                document = document_service.resolve(
                    session,
                    paper_id=paper_id,
                    kind=payload.source_kind,
                    principal=principal,
                    store=LocalAssetStore(
                        settings.asset_root,
                        source_roots=settings.source_roots,
                    ),
                    range_header=None,
                )
                request = CropRequest(
                    source_pdf_sha256=document.asset.sha256,
                    page_number=page_number,
                    x0=float(bounds[0]),
                    y0=float(bounds[1]),
                    x1=float(bounds[2]),
                    y1=float(bounds[3]),
                    rotation=int(revision.region_rotation or 0),
                    padding=payload.padding,
                    dpi=payload.dpi,
                    renderer_version=PDF_RENDERER_VERSION,
                )
                job = CropService(
                    settings.asset_root,
                    source_roots=settings.source_roots,
                ).enqueue(
                    session,
                    request,
                    source_asset_id=document.asset.id,
                    created_by_id=principal.user_id,
                    paper_id=paper_id,
                    region_id=region_id,
                )
                response = _reviewer_job_payload(job)
            return response
        except DocumentNotFound as error:
            raise HTTPException(status_code=404, detail="Resource not found") from error
        except RegionValidationError as error:
            code = 404 if "not found" in str(error).casefold() else 422
            raise HTTPException(status_code=code, detail=str(error)) from error
        except CropValidationError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.get("/crop-jobs/{job_id}")
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def crop_job_status(
        job_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> dict[str, object]:
        if principal.must_change_password:
            raise HTTPException(status_code=403, detail="Password change required")
        if principal.role not in {UserRole.ADMIN, UserRole.REVIEWER}:
            raise HTTPException(status_code=403, detail="Permission denied")
        with session.begin():
            job = session.get(CropJob, job_id)
            subscribed = principal.role is UserRole.ADMIN or session.scalar(
                select(CropJobSubscription.id)
                .join(
                    ReviewTask,
                    ReviewTask.paper_id == CropJobSubscription.paper_id,
                )
                .where(
                    CropJobSubscription.job_id == job_id,
                    CropJobSubscription.requested_by_id == principal.user_id,
                    ReviewTask.assigned_reviewer_id == principal.user_id,
                    ReviewTask.status != ReviewTaskStatus.COMPLETED,
                )
            ) is not None
            if job is None or not subscribed:
                raise HTTPException(status_code=404, detail="Resource not found")
            return _reviewer_job_payload(job)

    return router


__all__ = ["create_crop_jobs_router", "create_jobs_router"]
