from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from app.jobs.service import CropRequest, CropResult, CropService


def run_crop_job(
    session: Session,
    *,
    managed_root: Path,
    request: CropRequest,
    renderer: Callable[[CropRequest], bytes],
    source_asset_id: UUID | None = None,
    created_by_id: UUID | None = None,
) -> CropResult:
    return CropService(managed_root).run_persisted(
        session,
        request,
        renderer=renderer,
        source_asset_id=source_asset_id,
        created_by_id=created_by_id,
    )
