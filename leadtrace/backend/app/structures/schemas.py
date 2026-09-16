from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.structures.models import StructureInputMethod, StructureStatus


class StructureUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_workspace_version: int = Field(ge=1)
    status: StructureStatus
    input_method: StructureInputMethod
    smiles: str | None = Field(default=None, max_length=20_000)
    molfile: str | None = Field(default=None, max_length=200_000)


class StructureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    paper_id: UUID
    workspace_id: UUID
    compound_id: UUID
    smiles: str | None
    molfile: str | None
    canonical_smiles: str | None
    inchi: str | None
    inchikey: str | None
    depiction_asset_id: UUID | None
    status: StructureStatus
    input_method: StructureInputMethod


class StructureMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    structure: StructureResponse
    workspace_version: int


class StructureReadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    structure: StructureResponse | None
    workspace_version: int


__all__ = [
    "StructureMutationResponse",
    "StructureReadResponse",
    "StructureResponse",
    "StructureUpsertRequest",
]
