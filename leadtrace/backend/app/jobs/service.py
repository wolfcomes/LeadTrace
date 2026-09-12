from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable
from uuid import UUID

import pymupdf
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.assets.models import Asset, AssetAccessLevel, AssetCategory, AssetIntegrityState
from app.assets.service import AssetService
from app.assets.storage import LocalAssetStore, StoredFile
from app.jobs.models import CropJob, CropJobStatus
from app.maintenance.service import MaintenanceService


class CropValidationError(ValueError):
    pass


PDF_RENDERER_VERSION = f"pymupdf-{pymupdf.VersionBind}"


@dataclass(frozen=True, slots=True)
class CropRequest:
    source_pdf_sha256: str
    page_number: int
    x0: float
    y0: float
    x1: float
    y1: float
    rotation: int
    padding: int
    dpi: int
    renderer_version: str

    def __post_init__(self) -> None:
        if len(self.source_pdf_sha256) != 64 or any(c not in "0123456789abcdefABCDEF" for c in self.source_pdf_sha256):
            raise CropValidationError("source_pdf_sha256 must be a SHA-256 hex digest")
        if self.page_number < 1:
            raise CropValidationError("page_number must be positive")
        values = (self.x0, self.y0, self.x1, self.y1)
        if any(not math.isfinite(float(v)) or float(v) < 0 or float(v) > 1 for v in values):
            raise CropValidationError("crop bounds must be normalized to 0..1")
        if self.x0 >= self.x1 or self.y0 >= self.y1:
            raise CropValidationError("crop bounds must have positive size")
        if self.rotation not in {0, 90, 180, 270}:
            raise CropValidationError("rotation must be 0, 90, 180, or 270")
        if self.padding < 0 or self.dpi < 1 or not self.renderer_version.strip():
            raise CropValidationError("padding, dpi, and renderer_version are invalid")

    def input_hash(self) -> str:
        payload = {
            "source_pdf_sha256": self.source_pdf_sha256.lower(),
            "page_number": self.page_number,
            "x0": round(float(self.x0), 12),
            "y0": round(float(self.y0), 12),
            "x1": round(float(self.x1), 12),
            "y1": round(float(self.y1), 12),
            "rotation": self.rotation,
            "padding": self.padding,
            "dpi": self.dpi,
            "renderer_version": self.renderer_version.strip(),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def model_copy(self, update: dict[str, object] | None = None, **changes: object) -> "CropRequest":
        merged = dict(update or {})
        merged.update(changes)
        return replace(self, **merged)


@dataclass(frozen=True, slots=True)
class CropResult:
    asset_key: str
    path: Path
    reused: bool
    asset_id: UUID | None = None
    input_hash: str = ""


Renderer = Callable[[CropRequest], bytes]


def _request_metadata(request: CropRequest) -> dict[str, object]:
    return {
        "source_pdf_sha256": request.source_pdf_sha256.lower(),
        "page_number": request.page_number,
        "x0": request.x0,
        "y0": request.y0,
        "x1": request.x1,
        "y1": request.y1,
        "rotation": request.rotation,
        "padding": request.padding,
        "dpi": request.dpi,
        "renderer_version": request.renderer_version,
    }


class CropService:
    """Deterministic crop registry with atomic managed-file writes."""

    def __init__(self, managed_root: Path, *, source_roots: dict[str, Path] | None = None) -> None:
        self.store = LocalAssetStore(managed_root, source_roots=source_roots)
        self._memory: dict[str, CropResult] = {}

    def find(self, request: CropRequest) -> CropResult | None:
        result = self._memory.get(request.input_hash())
        if result is not None and result.path.is_file():
            return result
        return None

    def run(self, request: CropRequest, *, renderer: Renderer) -> CropResult:
        input_hash = request.input_hash()
        existing = self.find(request)
        if existing is not None:
            return replace(existing, reused=True)
        content = renderer(request)
        if not isinstance(content, bytes) or not content:
            raise CropValidationError("renderer must return non-empty bytes")
        stored: StoredFile = self.store.put_bytes(content, suffix=".png")
        result = CropResult(
            asset_key=stored.storage_key,
            path=stored.path,
            reused=False,
            input_hash=input_hash,
        )
        self._memory[input_hash] = result
        return result

    def enqueue(
        self,
        session: Session,
        request: CropRequest,
        *,
        source_asset_id: UUID,
        created_by_id: UUID,
    ) -> CropJob:
        """Create or reuse one PostgreSQL-authoritative crop job."""

        MaintenanceService().require_writes_enabled(session)
        input_hash = request.input_hash()
        created_id = session.scalar(
            insert(CropJob)
            .values(
                input_hash=input_hash,
                source_pdf_sha256=request.source_pdf_sha256.lower(),
                source_asset_id=source_asset_id,
                page_number=request.page_number,
                x0=request.x0,
                y0=request.y0,
                x1=request.x1,
                y1=request.y1,
                rotation=request.rotation,
                padding=request.padding,
                dpi=request.dpi,
                renderer_version=request.renderer_version.strip(),
                status=CropJobStatus.PENDING,
                created_by_id=created_by_id,
            )
            .on_conflict_do_nothing(index_elements=[CropJob.input_hash])
            .returning(CropJob.id)
        )
        if created_id is not None:
            job = session.get(CropJob, created_id)
            assert job is not None
            return job

        job = session.scalar(
            select(CropJob)
            .where(CropJob.input_hash == input_hash)
            .with_for_update()
        )
        if job is None:
            raise CropValidationError("Crop job could not be created")
        if job.status is CropJobStatus.SUPERSEDED:
            raise CropValidationError("Crop job was superseded by newer work")
        return job

    def run_persisted(
        self,
        session: Session,
        request: CropRequest,
        *,
        renderer: Renderer,
        source_asset_id: UUID | None = None,
        created_by_id: UUID | None = None,
    ) -> CropResult:
        input_hash = request.input_hash()
        MaintenanceService().require_writes_enabled(session)
        job = session.scalar(select(CropJob).where(CropJob.input_hash == input_hash).with_for_update())
        if job is not None and job.status is CropJobStatus.SUPERSEDED:
            raise CropValidationError("Crop job was superseded by newer work")
        if job is not None and job.status is CropJobStatus.COMPLETED and job.asset_id is not None:
            asset = session.get(Asset, job.asset_id)
            if asset is not None and self.store.path_for(asset.storage_key).is_file():
                return CropResult(asset.storage_key, self.store.path_for(asset.storage_key), True, asset.id, input_hash)
        now = datetime.now(UTC)
        if job is None:
            job = CropJob(
                input_hash=input_hash,
                source_pdf_sha256=request.source_pdf_sha256.lower(),
                source_asset_id=source_asset_id,
                page_number=request.page_number,
                x0=request.x0, y0=request.y0, x1=request.x1, y1=request.y1,
                rotation=request.rotation, padding=request.padding, dpi=request.dpi,
                renderer_version=request.renderer_version.strip(),
                status=CropJobStatus.RUNNING,
                started_at=now,
                created_by_id=created_by_id,
            )
            session.add(job)
            session.flush()
        else:
            job.status = CropJobStatus.RUNNING
            job.error_message = None
            job.started_at = now
        try:
            result = self.materialize_persisted(
                session,
                request,
                renderer=renderer,
                source_asset_id=source_asset_id,
                created_by_id=created_by_id,
            )
            job.status = CropJobStatus.COMPLETED
            job.asset_id = result.asset_id
            job.completed_at = datetime.now(UTC)
            session.flush()
            return result
        except Exception as error:
            job.status = CropJobStatus.FAILED
            job.error_message = str(error)[:2000]
            job.completed_at = datetime.now(UTC)
            session.flush()
            raise

    def materialize_persisted(
        self,
        session: Session,
        request: CropRequest,
        *,
        renderer: Renderer,
        source_asset_id: UUID | None = None,
        created_by_id: UUID | None = None,
    ) -> CropResult:
        """Render and register a crop without owning the job state machine."""

        MaintenanceService().require_writes_enabled(session)
        result = self.run(request, renderer=renderer)
        inspected = self.store.inspect(result.asset_key)
        asset, _ = AssetService().register_inspected(
            session,
            storage_key=result.asset_key,
            inspected=inspected,
            category=AssetCategory.EVIDENCE_CROP,
            access_level=AssetAccessLevel.REVIEWER,
            integrity_state=AssetIntegrityState.VERIFIED,
            source_asset_id=source_asset_id,
            created_by_id=created_by_id,
            derivation_metadata={
                "crop_input_hash": request.input_hash(),
                "request": _request_metadata(request),
            },
        )
        return replace(result, asset_id=asset.id)
