from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.chemistry.validation import SourceComparison
from app.molecule_proposals.models import MoleculeProposalDisposition


class MoleculeProposalUpdateRequest(BaseModel):
    """Reviewer-owned fields for an OCSR proposal decision.

    Machine output is deliberately not represented here.  The server copies
    that output from the predecessor revision and only merges these typed
    fields into a new revision.
    """

    model_config = ConfigDict(extra="forbid")

    changeset_id: UUID
    expected_version: int = Field(ge=1)
    disposition: MoleculeProposalDisposition
    reviewed_smiles: str | None = Field(default=None, max_length=10000)
    selected_component_smiles: str | None = Field(default=None, max_length=10000)
    compound_id: UUID | None = None
    resulting_structure_id: UUID | None = None
    rationale: str | None = Field(default=None, max_length=2000)
    source_comparison: SourceComparison = SourceComparison.NOT_COMPARED
    source_verified: bool = False


class MoleculeProposalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    paper_id: UUID
    visual_object_id: UUID
    proposal_key: str
    model_run_key: str
    revision_id: UUID
    revision_number: int
    changeset_id: UUID | None
    changeset_version: int | None
    disposition: MoleculeProposalDisposition
    machine: dict[str, object]
    review: dict[str, object]
    crop_asset: dict[str, object] | None
    source_region: dict[str, object] | None
