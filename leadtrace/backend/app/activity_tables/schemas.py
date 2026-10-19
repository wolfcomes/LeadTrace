from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TableColumn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=512)
    assay: str = Field(min_length=1, max_length=512)
    metric: str = Field(min_length=1, max_length=128)
    unit: str | None = Field(default=None, max_length=128)
    activity_ids: list[UUID] = Field(max_length=10000)

    @field_validator('id', 'label', 'assay', 'metric')
    @classmethod
    def required(cls, value):
        if not value.strip():
            raise ValueError('Nonblank text is required')
        return value.strip()

    @field_validator('activity_ids')
    @classmethod
    def unique(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('Activity IDs must be unique within a column')
        return value


class TableDefinition(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=512)
    kind: Literal['source', 'custom'] = 'custom'
    source_label: str | None = Field(default=None, max_length=512)
    source_title: str | None = Field(default=None, max_length=10000)
    page_number: int | None = Field(default=None, ge=1)
    review_hint: str | None = Field(default=None, max_length=1000)
    columns: list[TableColumn] = Field(max_length=200)
    mode: Literal['any', 'all'] = 'any'
    sort: Literal['label', 'similarity', 'default'] = 'label'

    @field_validator('name')
    @classmethod
    def required(cls, value):
        if not value.strip():
            raise ValueError('Nonblank name is required')
        return value.strip()

    @field_validator('source_label', 'source_title', 'review_hint')
    @classmethod
    def optional(cls, value):
        return value.strip() or None if value is not None else None

    @model_validator(mode='after')
    def validate_identity(self):
        if self.kind == 'source' and not self.source_label:
            raise ValueError('Original source tables require a source label')
        if len({c.id for c in self.columns}) != len(self.columns):
            raise ValueError('Column IDs must be unique within a table')
        return self


class TableVersion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_workspace_version: int = Field(ge=1)


class TableWrite(TableDefinition, TableVersion):
    pass


class TableConfirm(TableVersion):
    review_status: Literal['reviewer_confirmed', 'unresolved'] = 'reviewer_confirmed'


class TableResponse(TableDefinition):
    id: UUID
    paper_id: UUID
    workspace_id: UUID
    review_status: Literal['draft', 'reviewer_confirmed', 'unresolved']
    created_by_kind: str


class TableListResponse(BaseModel):
    workspace_id: UUID
    workspace_version: int
    tables: list[TableResponse]
    other_activity_ids: list[UUID]


class TableMutationResponse(BaseModel):
    workspace_version: int
    table: TableResponse


class TableDeleteResponse(BaseModel):
    workspace_version: int
    deleted_table_id: UUID
