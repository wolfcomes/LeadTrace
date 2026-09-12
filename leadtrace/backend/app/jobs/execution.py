from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import UUID

import pymupdf
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.assets.models import Asset, AssetCategory, AssetIntegrityState
from app.assets.storage import LocalAssetStore
from app.config import Settings
from app.jobs.models import CropJob
from app.jobs.reconciler import JobReconciler
from app.jobs.service import CropRequest, CropService, CropValidationError
from app.maintenance.service import MaintenanceModeActive


class CropExecutionStatus(StrEnum):
    COMPLETED = "completed"
    IGNORED = "ignored"
    PAUSED = "paused"


@dataclass(frozen=True, slots=True)
class CropExecutionReport:
    job_id: UUID
    status: CropExecutionStatus
    attempt_id: UUID | None = None
    asset_id: UUID | None = None


def _request_from_job(job: CropJob) -> CropRequest:
    request = CropRequest(
        source_pdf_sha256=job.source_pdf_sha256,
        page_number=job.page_number,
        x0=job.x0,
        y0=job.y0,
        x1=job.x1,
        y1=job.y1,
        rotation=job.rotation,
        padding=job.padding,
        dpi=job.dpi,
        renderer_version=job.renderer_version,
    )
    if request.input_hash() != job.input_hash:
        raise CropValidationError("Crop job parameters do not match its input hash")
    return request


def _source_pdf_path(
    session: Session,
    job: CropJob,
    store: LocalAssetStore,
) -> Path:
    if job.source_asset_id is None:
        raise CropValidationError("Crop job has no registered source PDF")
    source_asset = session.get(Asset, job.source_asset_id)
    if source_asset is None:
        raise CropValidationError("Crop job source asset no longer exists")
    if source_asset.category not in {
        AssetCategory.ARTICLE_PDF,
        AssetCategory.SI_PDF,
    } or source_asset.mime_type != "application/pdf":
        raise CropValidationError("Crop job source asset is not a PDF")
    if source_asset.integrity_state not in {
        AssetIntegrityState.REGISTERED,
        AssetIntegrityState.VERIFIED,
    }:
        raise CropValidationError("Crop job source PDF is not available for rendering")
    inspected = store.inspect(source_asset.storage_key)
    if (
        inspected.sha256 != source_asset.sha256
        or inspected.sha256 != job.source_pdf_sha256
        or inspected.mime_type != "application/pdf"
    ):
        raise CropValidationError("Crop job source PDF failed its integrity check")
    return inspected.path


def render_pdf_crop(source_path: Path, request: CropRequest) -> bytes:
    """Render normalized crop coordinates against the rotated PDF page."""

    try:
        with pymupdf.open(source_path) as document:
            if request.page_number > document.page_count:
                raise CropValidationError("Crop page is outside the source PDF")
            page = document.load_page(request.page_number - 1)
            if request.rotation:
                page.set_rotation((page.rotation + request.rotation) % 360)
            page_rect = page.rect
            padding_points = request.padding * 72 / request.dpi
            clip = pymupdf.Rect(
                max(page_rect.x0, page_rect.x0 + page_rect.width * request.x0 - padding_points),
                max(page_rect.y0, page_rect.y0 + page_rect.height * request.y0 - padding_points),
                min(page_rect.x1, page_rect.x0 + page_rect.width * request.x1 + padding_points),
                min(page_rect.y1, page_rect.y0 + page_rect.height * request.y1 + padding_points),
            )
            pixmap = page.get_pixmap(
                matrix=pymupdf.Matrix(request.dpi / 72, request.dpi / 72),
                clip=clip,
                alpha=False,
            )
            return pixmap.tobytes("png")
    except CropValidationError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise CropValidationError("Source PDF could not be rendered") from error


def execute_crop_delivery(
    factory: sessionmaker[Session],
    settings: Settings,
    *,
    job_id: UUID,
    delivery_token: UUID,
) -> CropExecutionReport:
    """Execute one recoverable delivery whose authoritative state is PostgreSQL."""

    reconciler = JobReconciler()
    with factory.begin() as session:
        attempt = reconciler.claim_delivery(
            session,
            job_id=job_id,
            delivery_token=delivery_token,
        )
        if attempt is None:
            return CropExecutionReport(job_id, CropExecutionStatus.IGNORED)
        attempt_id = attempt.id

    try:
        with factory.begin() as session:
            job = session.scalar(
                select(CropJob).where(CropJob.id == job_id).with_for_update()
            )
            if job is None:
                raise CropValidationError("Crop job no longer exists")
            request = _request_from_job(job)
            store = LocalAssetStore(
                settings.asset_root,
                source_roots=settings.source_roots,
            )
            source_path = _source_pdf_path(session, job, store)
            result = CropService(
                settings.asset_root,
                source_roots=settings.source_roots,
            ).materialize_persisted(
                session,
                request,
                renderer=lambda crop_request: render_pdf_crop(
                    source_path,
                    crop_request,
                ),
                source_asset_id=job.source_asset_id,
                created_by_id=job.created_by_id,
            )
            assert result.asset_id is not None
            completed = reconciler.complete_delivery(
                session,
                job_id=job_id,
                delivery_token=delivery_token,
                asset_id=result.asset_id,
            )
            if not completed:
                raise CropValidationError("Crop delivery lost its active lease")
            return CropExecutionReport(
                job_id,
                CropExecutionStatus.COMPLETED,
                attempt_id=attempt_id,
                asset_id=result.asset_id,
            )
    except MaintenanceModeActive:
        return CropExecutionReport(
            job_id,
            CropExecutionStatus.PAUSED,
            attempt_id=attempt_id,
        )
    except Exception as error:
        with factory.begin() as session:
            reconciler.fail_delivery(
                session,
                job_id=job_id,
                delivery_token=delivery_token,
                error_message=str(error),
            )
        raise


__all__ = [
    "CropExecutionReport",
    "CropExecutionStatus",
    "execute_crop_delivery",
    "render_pdf_crop",
]
