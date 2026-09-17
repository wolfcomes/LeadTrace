from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.assets.models import Asset
from app.audit.models import AuditEvent
from app.audit.service import AuditService
from app.catalog.models import PaperSource
from app.config import Settings
from app.database import get_db_session
from app.evidence.models import Evidence
from app.health.service import CheckProbe, HealthService
from app.jobs.models import CropJob, CropJobRetryOperation, CropJobStatus
from app.jobs.reconciler import JobReconciler
from app.maintenance.service import MaintenanceConflict, MaintenanceService
from app.security.permissions import (
    RouteAccess,
    declare_route_access,
    require_permission,
    require_request_csrf,
)
from app.security.policies import Action, Principal
from app.structure_images.models import StructureSourceImage
from app.structures.models import Structure


class MaintenanceUpdate(BaseModel):
    active: bool
    reason: str = Field(min_length=1, max_length=2000)
    expected_end: datetime | None = None

    @model_validator(mode="after")
    def validate_expected_end(self) -> "MaintenanceUpdate":
        if self.active and self.expected_end is None:
            raise ValueError("expected_end is required when enabling maintenance")
        return self


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def _maintenance_payload(
    service: MaintenanceService,
    session: Session,
) -> dict[str, object]:
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
        "created_at": _timestamp(job.created_at),
        "started_at": _timestamp(job.started_at),
        "heartbeat_at": _timestamp(job.heartbeat_at),
        "completed_at": _timestamp(job.completed_at),
        "dispatched_at": _timestamp(job.dispatched_at),
        "asset_id": str(job.asset_id) if job.asset_id else None,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "superseded_by_id": (
            str(job.superseded_by_id) if job.superseded_by_id else None
        ),
    }


def _safe_asset(asset: Asset) -> dict[str, object]:
    source_root_key = asset.source_metadata.get("source_root_key")
    if isinstance(source_root_key, str) and (
        source_root_key.startswith("/") or "://" in source_root_key
    ):
        source_root_key = Path(source_root_key).name
    return {
        "id": str(asset.id),
        "filename": asset.original_filename,
        "sha256": asset.sha256,
        "byte_size": asset.byte_size,
        "mime_type": asset.mime_type,
        "category": asset.category.value,
        "access_level": asset.access_level.value,
        "access_class": asset.access_level.value,
        "integrity": asset.integrity_state.value,
        "integrity_state": asset.integrity_state.value,
        "source_asset_id": (
            str(asset.source_asset_id) if asset.source_asset_id else None
        ),
        "has_derivation": bool(asset.derivation_metadata),
        "source_root_key": source_root_key,
    }


def _asset_references(session: Session, asset: Asset) -> list[dict[str, object]]:
    references: list[dict[str, object]] = []
    for source in session.scalars(
        select(PaperSource).where(PaperSource.asset_id == asset.id)
    ):
        references.append(
            {"kind": "paper_source", "id": str(source.id), "role": "source_pdf"}
        )
    for structure in session.scalars(
        select(Structure).where(Structure.depiction_asset_id == asset.id)
    ):
        references.append(
            {"kind": "structure", "id": str(structure.id), "role": "depiction"}
        )
    for source_image in session.scalars(
        select(StructureSourceImage).where(
            StructureSourceImage.crop_asset_id == asset.id
        )
    ):
        references.append(
            {
                "kind": "structure_source_image",
                "id": str(source_image.id),
                "role": "crop",
            }
        )
    for evidence in session.scalars(
        select(Evidence).where(Evidence.crop_asset_id == asset.id)
    ):
        references.append(
            {"kind": "evidence", "id": str(evidence.id), "role": "crop"}
        )
    for job in session.scalars(
        select(CropJob).where(
            (CropJob.asset_id == asset.id) | (CropJob.source_asset_id == asset.id)
        )
    ):
        references.append(
            {
                "kind": "crop_job",
                "id": str(job.id),
                "role": "output" if job.asset_id == asset.id else "source",
            }
        )
    for derivative in session.scalars(
        select(Asset).where(Asset.source_asset_id == asset.id)
    ):
        references.append(
            {
                "kind": "asset",
                "id": str(derivative.id),
                "role": "derivative",
                "filename": derivative.original_filename,
            }
        )
    return references


def _audit_payload(event: AuditEvent) -> dict[str, object]:
    return {
        "id": str(event.id),
        "sequence_number": event.sequence_number,
        "actor_id": str(event.actor_id),
        "action": event.action,
        "target_type": event.target_type,
        "target_id": str(event.target_id),
        "paper_id": str(event.paper_id) if event.paper_id else None,
        "occurred_at": _timestamp(event.occurred_at),
        "request_id": event.request_id,
        "result": event.result,
        "reason": event.reason,
        "details": event.details,
    }


def create_operations_router(
    settings: Settings,
    *,
    database_probe: CheckProbe,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/admin", tags=["operations"])
    require_admin = require_permission(Action.MANAGE_ACCOUNTS)
    maintenance = MaintenanceService()

    @router.get("/files", response_model=list[dict[str, object]])
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_ACCOUNTS)
    def list_files(
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        category: str | None = None,
        integrity: str | None = None,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_admin),
    ) -> list[dict[str, object]]:
        del principal
        statement = select(Asset).order_by(Asset.created_at.desc(), Asset.id)
        if category:
            statement = statement.where(Asset.category == category)
        if integrity:
            statement = statement.where(Asset.integrity_state == integrity)
        with session.begin():
            assets = session.scalars(statement.limit(limit).offset(offset))
            return [_safe_asset(asset) for asset in assets]

    @router.get("/files/{asset_id}/references")
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_ACCOUNTS)
    def file_references(
        asset_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_admin),
    ) -> dict[str, object]:
        del principal
        with session.begin():
            asset = session.get(Asset, asset_id)
            if asset is None:
                raise HTTPException(status_code=404, detail="Asset not found")
            return {
                "asset": _safe_asset(asset),
                "references": _asset_references(session, asset),
            }

    @router.get("/audit", response_model=list[dict[str, object]])
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_ACCOUNTS)
    def list_audit(
        action: str | None = None,
        actor_id: UUID | None = None,
        target_type: str | None = None,
        result: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_admin),
    ) -> list[dict[str, object]]:
        del principal
        with session.begin():
            events = AuditService().list_events(
                session,
                actor_id=actor_id,
                action=action,
                target_type=target_type,
                result=result,
                limit=limit,
                offset=offset,
            )
            return [_audit_payload(event) for event in events]

    @router.get("/jobs", response_model=list[dict[str, object]])
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_ACCOUNTS)
    def list_jobs(
        status: CropJobStatus | None = None,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_admin),
    ) -> list[dict[str, object]]:
        del principal
        statement = select(CropJob).order_by(CropJob.created_at.desc(), CropJob.id)
        if status is not None:
            statement = statement.where(CropJob.status == status)
        with session.begin():
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
            return _job_payload(job)

    @router.get("/maintenance")
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_ACCOUNTS)
    def maintenance_status(
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_admin),
    ) -> dict[str, object]:
        del principal
        with session.begin():
            return _maintenance_payload(maintenance, session)

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
                    maintenance.activate(
                        session,
                        actor_id=principal.user_id,
                        reason=payload.reason,
                        expected_end_at=payload.expected_end,
                    )
                else:
                    maintenance.deactivate(
                        session,
                        actor_id=principal.user_id,
                        reason=payload.reason,
                    )
                return _maintenance_payload(maintenance, session)
        except MaintenanceConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except IntegrityError as error:
            raise HTTPException(
                status_code=409,
                detail="Maintenance mode changed concurrently",
            ) from error

    @router.get("/system")
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_ACCOUNTS)
    def system(
        request: Request,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_admin),
    ) -> dict[str, object]:
        del principal
        with session.begin():
            report = HealthService(
                settings,
                database_probe=database_probe,
            ).collect(session)
        request_id = getattr(request.state, "request_id", None) or "admin-system"
        return {**report.as_dict(), "request_id": request_id}

    return router


__all__ = ["create_operations_router"]
