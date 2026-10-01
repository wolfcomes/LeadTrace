from __future__ import annotations

from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.workspaces.models import ChangeActorKind


class CompoundCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_workspace_version: int = Field(ge=1)
    compound_label: str = Field(min_length=1, max_length=255)
    display_name: str | None = Field(default=None, max_length=512)
    description: str | None = Field(default=None, max_length=10_000)
    review_hint: str | None = Field(default=None, max_length=1000)


class CompoundUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_workspace_version: int = Field(ge=1)
    compound_label: str | None = Field(default=None, max_length=255)
    display_name: str | None = Field(default=None, max_length=512)
    description: str | None = Field(default=None, max_length=10_000)
    review_hint: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def require_an_update(self) -> Self:
        if not ({"compound_label", "display_name", "description", "review_hint"} & self.model_fields_set):
            raise ValueError("At least one Compound field is required")
        if "compound_label" in self.model_fields_set and self.compound_label is None:
            raise ValueError("compound_label cannot be null")
        return self

    def updates(self) -> dict[str, str | None]:
        return {
            field: getattr(self, field)
            for field in ("compound_label", "display_name", "description", "review_hint")
            if field in self.model_fields_set
        }


class CompoundReorderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_workspace_version: int = Field(ge=1)
    compound_ids: list[UUID]


class CompoundDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_workspace_version: int = Field(ge=1)


class CompoundResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    paper_id: UUID
    workspace_id: UUID
    compound_label: str
    display_name: str | None
    description: str | None
    review_hint: str | None = None
    sort_order: int
    created_by_kind: ChangeActorKind


class CompoundMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    compound: CompoundResponse
    workspace_version: int


class CompoundListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: UUID
    workspace_version: int
    items: list[CompoundResponse]
    total: int


class CompoundDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deleted_compound_id: UUID
    workspace_version: int


__all__ = [
    "CompoundCreateRequest",
    "CompoundDeleteRequest",
    "CompoundDeleteResponse",
    "CompoundListResponse",
    "CompoundMutationResponse",
    "CompoundReorderRequest",
    "CompoundResponse",
    "CompoundUpdateRequest",
]
