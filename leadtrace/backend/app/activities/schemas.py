from __future__ import annotations

from decimal import Decimal
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.activities.models import ActivityOperator


class WorkspaceVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_workspace_version: int = Field(ge=1)


class ActivityCreateRequest(WorkspaceVersionRequest):
    evidence_id: UUID | None = None
    assay_name: str = Field(min_length=1, max_length=512)
    metric: str = Field(min_length=1, max_length=128)
    operator: ActivityOperator
    value: Decimal
    unit: str | None = Field(default=None, max_length=128)
    context: str | None = Field(default=None, max_length=10_000)
    review_hint: str | None = Field(default=None, max_length=1000)


class ActivityUpdateRequest(WorkspaceVersionRequest):
    evidence_id: UUID | None = None
    assay_name: str | None = Field(default=None, max_length=512)
    metric: str | None = Field(default=None, max_length=128)
    operator: ActivityOperator | None = None
    value: Decimal | None = None
    unit: str | None = Field(default=None, max_length=128)
    context: str | None = Field(default=None, max_length=10_000)
    review_hint: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def require_update(self) -> Self:
        fields = {
            "evidence_id",
            "assay_name",
            "metric",
            "operator",
            "value",
            "unit",
            "context",
            "review_hint",
        }
        if not (fields & self.model_fields_set):
            raise ValueError("At least one Activity field is required")
        for field in ("assay_name", "metric", "operator", "value"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self

    def updates(self) -> dict[str, object]:
        return {
            field: getattr(self, field)
            for field in (
                "evidence_id",
                "assay_name",
                "metric",
                "operator",
                "value",
                "unit",
                "context",
                "review_hint",
            )
            if field in self.model_fields_set
        }


class ActivityReorderRequest(WorkspaceVersionRequest):
    activity_ids: list[UUID]


class ActivityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    paper_id: UUID
    workspace_id: UUID
    compound_id: UUID
    evidence_id: UUID | None
    assay_name: str
    metric: str
    operator: ActivityOperator
    value: Decimal
    unit: str | None
    context: str | None
    review_hint: str | None = None
    sort_order: int


class ActivityMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    activity: ActivityResponse
    workspace_version: int


class ActivityListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    compound_id: UUID
    workspace_version: int
    items: list[ActivityResponse]
    total: int


class ActivityDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deleted_activity_id: UUID
    workspace_version: int


__all__ = [name for name in globals() if name.endswith(("Request", "Response"))]
