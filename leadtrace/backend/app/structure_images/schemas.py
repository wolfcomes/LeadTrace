from __future__ import annotations

from decimal import Decimal
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.structure_images.models import CropStatus


class NormalizedBBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x0: Decimal = Field(ge=0, le=1)
    y0: Decimal = Field(ge=0, le=1)
    x1: Decimal = Field(ge=0, le=1)
    y1: Decimal = Field(ge=0, le=1)

    @model_validator(mode="after")
    def positive_area(self) -> Self:
        if self.x0 >= self.x1 or self.y0 >= self.y1:
            raise ValueError("bbox must have positive normalized area")
        return self


class StructureSourceImageCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_workspace_version: int = Field(ge=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_number: int = Field(ge=1)
    bbox: NormalizedBBox
    source_context: str | None = Field(default=None, max_length=10_000)
    label: str | None = Field(default=None, max_length=255)
    reviewer_note: str | None = Field(default=None, max_length=10_000)


class StructureSourceImageUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_workspace_version: int = Field(ge=1)
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    page_number: int | None = Field(default=None, ge=1)
    bbox: NormalizedBBox | None = None
    source_context: str | None = Field(default=None, max_length=10_000)
    label: str | None = Field(default=None, max_length=255)
    reviewer_note: str | None = Field(default=None, max_length=10_000)

    @model_validator(mode="after")
    def require_update(self) -> Self:
        if not (self.model_fields_set - {"expected_workspace_version"}):
            raise ValueError("At least one source-image field is required")
        for field in ("source_sha256", "page_number", "bbox"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self

    def updates(self) -> dict[str, object]:
        return {
            field: getattr(self, field)
            for field in (
                "source_sha256",
                "page_number",
                "bbox",
                "source_context",
                "label",
                "reviewer_note",
            )
            if field in self.model_fields_set
        }


class WorkspaceVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_workspace_version: int = Field(ge=1)


class BBoxResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x0: float
    y0: float
    x1: float
    y1: float


class StructureSourceImageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    paper_id: UUID
    workspace_id: UUID
    compound_id: UUID
    source_sha256: str
    page_number: int
    bbox: BBoxResponse
    source_context: str | None
    label: str | None
    reviewer_note: str | None
    crop_status: CropStatus
    crop_asset_id: UUID | None


class StructureSourceImageMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_image: StructureSourceImageResponse
    workspace_version: int


class StructureSourceImageListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    compound_id: UUID
    workspace_version: int
    items: list[StructureSourceImageResponse]
    total: int


class StructureSourceImageDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deleted_source_image_id: UUID
    workspace_version: int


__all__ = [
    "BBoxResponse",
    "NormalizedBBox",
    "StructureSourceImageCreateRequest",
    "StructureSourceImageDeleteResponse",
    "StructureSourceImageListResponse",
    "StructureSourceImageMutationResponse",
    "StructureSourceImageResponse",
    "StructureSourceImageUpdateRequest",
    "WorkspaceVersionRequest",
]
