from __future__ import annotations

from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from app.chemistry.drawing import DEFAULT_RENDER_VERSION, DrawingOptions
from app.structures.service import StructureDrawingResult, StructureDrawingService


def run_structure_drawing_job(
    session: Session,
    *,
    managed_root: Path,
    smiles: str,
    options: DrawingOptions = DrawingOptions(),
    render_version: str = DEFAULT_RENDER_VERSION,
    created_by_id: UUID | None = None,
    source_asset_id: UUID | None = None,
) -> StructureDrawingResult:
    return StructureDrawingService(managed_root).draw(
        session,
        smiles=smiles,
        options=options,
        render_version=render_version,
        created_by_id=created_by_id,
        source_asset_id=source_asset_id,
    )
