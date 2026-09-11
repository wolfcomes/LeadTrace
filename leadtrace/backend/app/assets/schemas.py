from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.assets.models import (
    AssetAccessLevel,
    AssetCategory,
    AssetIntegrityState,
)


class AssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    original_filename: str
    sha256: str
    byte_size: int
    mime_type: str
    width: int | None
    height: int | None
    page_count: int | None
    category: AssetCategory
    access_level: AssetAccessLevel
    integrity_state: AssetIntegrityState
