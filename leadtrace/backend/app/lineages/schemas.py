from __future__ import annotations

from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.lineages.models import LineageEdgeReviewStatus, LineageMemberRole, LineageType


class WorkspaceVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_workspace_version: int = Field(ge=1)


class LineageCreateRequest(WorkspaceVersionRequest):
    lineage_type: LineageType = LineageType.UNSPECIFIED
    lineage_label: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)


class LineageUpdateRequest(WorkspaceVersionRequest):
    lineage_type: LineageType | None = None
    lineage_label: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)

    @model_validator(mode="after")
    def require_update(self) -> Self:
        if not ({"lineage_label", "lineage_type", "description"} & self.model_fields_set):
            raise ValueError("At least one Lineage field is required")
        for field in ("lineage_label", "lineage_type"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self

    def updates(self) -> dict[str, str | None]:
        return {
            field: getattr(self, field)
            for field in ("lineage_label", "lineage_type", "description")
            if field in self.model_fields_set
        }


class LineageReorderRequest(WorkspaceVersionRequest):
    lineage_ids: list[UUID]


class LineageMemberCreateRequest(WorkspaceVersionRequest):
    compound_id: UUID
    role: LineageMemberRole


class LineageMemberUpdateRequest(WorkspaceVersionRequest):
    role: LineageMemberRole


class LineageMemberReorderRequest(WorkspaceVersionRequest):
    member_ids: list[UUID]


class LineageEdgeCreateRequest(WorkspaceVersionRequest):
    parent_compound_id: UUID
    child_compound_id: UUID
    relation_type: str = Field(min_length=1, max_length=128)
    modification_summary: str | None = Field(default=None, max_length=10_000)
    review_status: LineageEdgeReviewStatus


class LineageEdgeUpdateRequest(WorkspaceVersionRequest):
    parent_compound_id: UUID | None = None
    child_compound_id: UUID | None = None
    relation_type: str | None = Field(default=None, max_length=128)
    modification_summary: str | None = Field(default=None, max_length=10_000)
    review_status: LineageEdgeReviewStatus | None = None

    @model_validator(mode="after")
    def require_update(self) -> Self:
        fields = {
            "parent_compound_id",
            "child_compound_id",
            "relation_type",
            "modification_summary",
            "review_status",
        }
        if not (fields & self.model_fields_set):
            raise ValueError("At least one Edge field is required")
        for field in fields - {"modification_summary"}:
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self

    def updates(self) -> dict[str, object]:
        return {
            field: getattr(self, field)
            for field in (
                "parent_compound_id",
                "child_compound_id",
                "relation_type",
                "modification_summary",
                "review_status",
            )
            if field in self.model_fields_set
        }


class LineageEdgeReorderRequest(WorkspaceVersionRequest):
    edge_ids: list[UUID]


class LineageMemberResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    paper_id: UUID
    workspace_id: UUID
    lineage_id: UUID
    compound_id: UUID
    role: LineageMemberRole
    sort_order: int


class LineageEdgeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    paper_id: UUID
    workspace_id: UUID
    lineage_id: UUID
    parent_compound_id: UUID
    child_compound_id: UUID
    relation_type: str
    modification_summary: str | None
    review_status: LineageEdgeReviewStatus
    sort_order: int


class LineageResponse(BaseModel):
    lineage_type: LineageType = LineageType.UNSPECIFIED
    model_config = ConfigDict(extra="forbid")
    id: UUID
    paper_id: UUID
    workspace_id: UUID
    lineage_label: str
    description: str | None
    sort_order: int
    members: list[LineageMemberResponse]
    edges: list[LineageEdgeResponse]


class LineageMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lineage: LineageResponse
    workspace_version: int


class LineageMemberMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    member: LineageMemberResponse
    workspace_version: int


class LineageEdgeMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    edge: LineageEdgeResponse
    workspace_version: int


class LineageListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    workspace_version: int
    items: list[LineageResponse]
    total: int


class LineageMemberListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lineage_id: UUID
    workspace_version: int
    items: list[LineageMemberResponse]
    total: int


class LineageEdgeListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lineage_id: UUID
    workspace_version: int
    items: list[LineageEdgeResponse]
    total: int


class DeletedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deleted_id: UUID
    workspace_version: int


__all__ = [name for name in globals() if name.endswith(("Request", "Response"))]
