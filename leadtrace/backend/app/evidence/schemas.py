from __future__ import annotations

from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.evidence.models import EvidenceKind, EvidenceRole
from app.structure_images.schemas import BBoxResponse, NormalizedBBox


class WorkspaceVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_workspace_version: int = Field(ge=1)


class EvidenceCreateRequest(WorkspaceVersionRequest):
    kind: EvidenceKind
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_number: int = Field(ge=1)
    bbox: NormalizedBBox | None = None
    quoted_text: str | None = Field(default=None, max_length=20_000)
    caption: str | None = Field(default=None, max_length=10_000)
    reviewer_note: str | None = Field(default=None, max_length=10_000)


class EvidenceUpdateRequest(WorkspaceVersionRequest):
    kind: EvidenceKind | None = None
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    page_number: int | None = Field(default=None, ge=1)
    bbox: NormalizedBBox | None = None
    quoted_text: str | None = Field(default=None, max_length=20_000)
    caption: str | None = Field(default=None, max_length=10_000)
    reviewer_note: str | None = Field(default=None, max_length=10_000)

    @model_validator(mode="after")
    def require_update(self) -> Self:
        fields = {
            "kind",
            "source_sha256",
            "page_number",
            "bbox",
            "quoted_text",
            "caption",
            "reviewer_note",
        }
        if not (fields & self.model_fields_set):
            raise ValueError("At least one Evidence field is required")
        for field in ("kind", "source_sha256", "page_number"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self

    def updates(self) -> dict[str, object]:
        return {
            field: getattr(self, field)
            for field in (
                "kind",
                "source_sha256",
                "page_number",
                "bbox",
                "quoted_text",
                "caption",
                "reviewer_note",
            )
            if field in self.model_fields_set
        }


class EvidenceLinkCreateRequest(WorkspaceVersionRequest):
    evidence_id: UUID
    role: EvidenceRole


class EvidenceLinkUpdateRequest(WorkspaceVersionRequest):
    role: EvidenceRole


class EvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    paper_id: UUID
    workspace_id: UUID
    kind: EvidenceKind
    source_sha256: str
    page_number: int
    bbox: BBoxResponse | None
    quoted_text: str | None
    caption: str | None
    crop_asset_id: UUID | None
    reviewer_note: str | None


class EvidenceLinkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    paper_id: UUID
    workspace_id: UUID
    edge_id: UUID
    evidence_id: UUID
    role: EvidenceRole


class EvidenceMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence: EvidenceResponse
    workspace_version: int


class EvidenceLinkMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    link: EvidenceLinkResponse
    workspace_version: int


class EvidenceListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    workspace_version: int
    items: list[EvidenceResponse]
    total: int


class EvidenceLinkListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    edge_id: UUID
    workspace_version: int
    items: list[EvidenceLinkResponse]
    total: int


class DeletedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deleted_id: UUID
    workspace_version: int


__all__ = [name for name in globals() if name.endswith(("Request", "Response"))]
