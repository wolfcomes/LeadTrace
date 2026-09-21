from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ai_prefill.assistance_contracts import (
    CandidateEnvelope,
    ValidationReport,
)


class AssistanceRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CandidateCreateRequest(AssistanceRequestModel):
    candidate: CandidateEnvelope = Field(description=(
        "At most 5000 scientific objects: Compounds and their Structures each count once; "
        "locators, Lineages, members, edges, Evidence, links and Activities also count once."
    ))

    @model_validator(mode="after")
    def limit_scientific_objects(self) -> CandidateCreateRequest:
        payload = self.candidate.payload
        count = sum(len(getattr(payload, name)) for name in (
            "compounds", "structure_locators", "lineages", "evidence", "edge_evidence_links", "activities",
        ))
        count += len(payload.compounds)  # One Structure per Compound.
        count += sum(len(lineage.members) + len(lineage.edges) for lineage in payload.lineages)
        if count > 5000:
            raise ValueError("Candidate contains more than 5000 scientific objects")
        return self


class CandidateCreateResponse(BaseModel):
    candidate: CandidateEnvelope
    replayed: bool = False


class ValidationCreateRequest(AssistanceRequestModel):
    page_texts: dict[int, str] = Field(default_factory=dict)


class ValidationCreateResponse(BaseModel):
    report: ValidationReport
    replayed: bool = False


class PreviewApplicationRequest(AssistanceRequestModel):
    validation_report: ValidationReport
    idempotency_key: str = Field(min_length=1, max_length=255)
    paper_id: UUID | None = None
    workspace_id: UUID | None = None
    run_id: UUID | None = None
    reviewer_id: UUID | None = None
    expected_workspace_version: int | None = Field(default=None, gt=0)


class PreviewApplicationResponse(BaseModel):
    reviewer_url: str = Field(description="Relative reviewer page URL for this application Workspace")
    application_id: UUID
    idempotent: bool
    receipt: dict[str, object]


class AssistanceContractResponse(BaseModel):
    envelope_schema: dict[str, object]
    profile_version: str
    validator_version: str
    capabilities: list[str]


__all__ = [
    "AssistanceContractResponse",
    "CandidateCreateRequest",
    "CandidateCreateResponse",
    "PreviewApplicationRequest",
    "PreviewApplicationResponse",
    "ValidationCreateRequest",
    "ValidationCreateResponse",
]
