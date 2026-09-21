from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.activities.models import ActivityOperator
from app.evidence.models import EvidenceKind, EvidenceRole
from app.lineages.models import LineageEdgeReviewStatus, LineageMemberRole, LineageType
from app.publications.models import AdminDecisionAction
from app.structure_images.models import CropStatus
from app.structures.models import StructureInputMethod, StructureStatus
from app.workspaces.models import (
    ChangeActorKind,
    PaperSection,
    PaperSectionState,
)
from app.workspaces.schemas import BibliographyResponse, SubmissionResponse


class PublicationProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdminDecisionRequest(PublicationProjection):
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    action: AdminDecisionAction
    reason: str = Field(min_length=1, max_length=10_000)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("A decision reason is required")
        return normalized

    @field_validator("idempotency_key")
    @classmethod
    def normalize_idempotency_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("idempotency_key is required")
        return normalized


class AdminDecisionResponse(PublicationProjection):
    id: UUID
    submission_id: UUID
    paper_id: UUID
    content_hash: str
    action: AdminDecisionAction
    reason: str
    decided_by_id: UUID
    idempotency_key: str
    decided_at: datetime


class PublishedPaperVersionResponse(PublicationProjection):
    id: UUID
    paper_id: UUID
    submission_id: UUID
    admin_decision_id: UUID
    version_number: int
    snapshot: dict[str, Any]
    content_hash: str
    decision_action: AdminDecisionAction
    published_by_id: UUID
    published_at: datetime


class DecisionMutationResponse(PublicationProjection):
    decision: AdminDecisionResponse
    published_version: PublishedPaperVersionResponse | None


class AdminSubmissionListItem(PublicationProjection):
    submission_id: UUID
    paper_id: UUID
    workspace_id: UUID
    submission_number: int
    content_hash: str
    submitted_by_id: UUID
    submitted_at: datetime
    paper_key: str
    title: str


class AdminSubmissionListResponse(PublicationProjection):
    items: list[AdminSubmissionListItem]
    total: int


class ChangeEventResponse(PublicationProjection):
    id: UUID
    paper_id: UUID
    workspace_id: UUID
    entity_type: str
    entity_id: UUID
    action: str
    before_value: dict[str, Any] | None
    after_value: dict[str, Any] | None
    actor_kind: ChangeActorKind
    actor_id: UUID | None
    ai_run_id: UUID | None
    occurred_at: datetime


class AdminSubmissionDetailResponse(PublicationProjection):
    submission: SubmissionResponse
    bibliography: BibliographyResponse
    change_events: list[ChangeEventResponse]
    reviewer_diff: list[ChangeEventResponse]


class PublishedPaperListItem(PublicationProjection):
    paper_id: UUID
    paper_key: str
    title: str
    journal: str
    publication_year: int
    volume: str
    issue: str
    doi: str | None
    version_number: int
    content_hash: str
    published_at: datetime


class PublishedPaperListResponse(PublicationProjection):
    items: list[PublishedPaperListItem]
    total: int


class PublishedSnapshotProjection(BaseModel):
    model_config = ConfigDict(extra="ignore")


class PublishedSnapshotBibliography(PublishedSnapshotProjection):
    id: UUID
    paper_key: str
    title: str
    journal: str
    publication_year: int
    volume: str
    issue: str
    doi: str | None


class PublishedSource(PublishedSnapshotProjection):
    sha256: str
    page_count: int


class PublishedSection(PublishedSnapshotProjection):
    section_key: PaperSection
    state: PaperSectionState


class PublishedCompound(PublishedSnapshotProjection):
    id: UUID
    compound_label: str
    display_name: str | None
    description: str | None
    sort_order: int


class PublishedStructure(PublishedSnapshotProjection):
    id: UUID
    compound_id: UUID
    smiles: str | None
    canonical_smiles: str | None
    molfile: str | None
    inchi: str | None
    inchikey: str | None
    depiction_asset_id: UUID | None
    status: StructureStatus
    input_method: StructureInputMethod


class PublishedStructureSourceImage(PublishedSnapshotProjection):
    id: UUID
    compound_id: UUID
    source_sha256: str
    page_number: int
    x0: Decimal
    y0: Decimal
    x1: Decimal
    y1: Decimal
    source_context: str | None
    label: str | None
    crop_status: CropStatus
    crop_asset_id: UUID | None


class PublishedLineage(PublishedSnapshotProjection):
    lineage_type: LineageType = LineageType.UNSPECIFIED
    id: UUID
    lineage_label: str
    description: str | None
    sort_order: int


class PublishedLineageMember(PublishedSnapshotProjection):
    id: UUID
    lineage_id: UUID
    compound_id: UUID
    role: LineageMemberRole
    sort_order: int


class PublishedLineageEdge(PublishedSnapshotProjection):
    id: UUID
    lineage_id: UUID
    parent_compound_id: UUID
    child_compound_id: UUID
    relation_type: str
    modification_summary: str | None
    review_status: LineageEdgeReviewStatus
    sort_order: int


class PublishedEvidence(PublishedSnapshotProjection):
    id: UUID
    kind: EvidenceKind
    source_sha256: str
    page_number: int
    x0: Decimal | None
    y0: Decimal | None
    x1: Decimal | None
    y1: Decimal | None
    quoted_text: str | None
    caption: str | None
    crop_asset_id: UUID | None


class PublishedEdgeEvidenceLink(PublishedSnapshotProjection):
    id: UUID
    edge_id: UUID
    evidence_id: UUID
    role: EvidenceRole


class PublishedActivity(PublishedSnapshotProjection):
    id: UUID
    compound_id: UUID
    evidence_id: UUID | None
    assay_name: str
    metric: str
    operator: ActivityOperator
    value: Decimal
    unit: str | None
    context: str | None
    sort_order: int


class PublishedPaperSnapshotResponse(PublishedSnapshotProjection):
    schema_version: Literal[1]
    paper: PublishedSnapshotBibliography
    source: PublishedSource
    sections: list[PublishedSection]
    compounds: list[PublishedCompound]
    structures: list[PublishedStructure]
    structure_source_images: list[PublishedStructureSourceImage]
    lineages: list[PublishedLineage]
    lineage_members: list[PublishedLineageMember]
    lineage_edges: list[PublishedLineageEdge]
    evidence: list[PublishedEvidence]
    edge_evidence_links: list[PublishedEdgeEvidenceLink]
    activities: list[PublishedActivity]


class PublishedPaperDetailResponse(PublicationProjection):
    paper_id: UUID
    version_id: UUID
    version_number: int
    content_hash: str
    published_at: datetime
    bibliography: BibliographyResponse
    snapshot: PublishedPaperSnapshotResponse


__all__ = [
    "AdminDecisionRequest",
    "AdminDecisionResponse",
    "AdminSubmissionDetailResponse",
    "AdminSubmissionListItem",
    "AdminSubmissionListResponse",
    "ChangeEventResponse",
    "DecisionMutationResponse",
    "PublicationProjection",
    "PublishedPaperDetailResponse",
    "PublishedPaperListItem",
    "PublishedPaperListResponse",
    "PublishedPaperSnapshotResponse",
    "PublishedPaperVersionResponse",
]
