from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.assets.models import AssetAccessLevel, AssetCategory
from app.molecule_proposals.models import MoleculeProposalDisposition
from app.revisions.models import ObjectKind, StructureState
from app.reviews.completeness import QueueState
from app.reviews.models import Changeset, ChangesetItem, ReviewTask, ReviewTaskStatus
from app.security.policies import WorkflowState
from app.visual_objects.models import MoleculeObjectType


class ReviewTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    paper_id: UUID
    assigned_reviewer_id: UUID
    created_by_id: UUID
    status: ReviewTaskStatus
    priority: int
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, task: ReviewTask) -> "ReviewTaskResponse":
        return cls.model_validate(task)


class ReviewTaskCreateRequest(BaseModel):
    paper_id: UUID
    assigned_reviewer_id: UUID
    priority: int = Field(default=0, ge=0, le=100)


class ReviewTaskReassignRequest(BaseModel):
    assigned_reviewer_id: UUID
    expected_version: int = Field(ge=1)


class ChangesetCreateRequest(BaseModel):
    review_task_id: UUID
    paper_id: UUID
    base_release_id: UUID
    title: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=4000)
    initialize_from_base: bool = False


class ChangesetUpdateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    reason: str | None = Field(default=None, min_length=1, max_length=4000)
    validation_results: dict[str, object] | None = None


class ChangesetSubmitRequest(BaseModel):
    expected_version: int = Field(ge=1)


class ChangesetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    review_task_id: UUID
    paper_id: UUID
    owner_id: UUID
    base_release_id: UUID
    title: str
    reason: str
    workflow_state: WorkflowState
    version: int
    validation_results: dict[str, object]
    submitted_snapshot: dict[str, object] | None
    submitted_content_hash: str | None
    submitted_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, changeset: Changeset) -> "ChangesetResponse":
        return cls.model_validate(changeset)


class ChangesetTransitionRequest(BaseModel):
    expected_version: int = Field(ge=1)


class ChangesetDecisionRequest(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=4000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("reason is required")
        return clean


class ChangesetItemCreateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    object_id: UUID
    object_kind: ObjectKind
    base_revision_id: UUID | None = None
    proposed_snapshot: dict[str, object]
    sequence: int | None = Field(default=None, ge=1)


class ChangesetItemFromBaseRequest(BaseModel):
    expected_version: int = Field(ge=1)
    object_id: UUID
    object_kind: ObjectKind
    sequence: int | None = Field(default=None, ge=1)


class ChangesetItemUpdateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    proposed_snapshot: dict[str, object]


class ChangesetItemDeleteRequest(BaseModel):
    expected_version: int = Field(ge=1)


class ChangesetItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    changeset_id: UUID
    paper_id: UUID
    object_id: UUID
    object_kind: ObjectKind
    base_revision_id: UUID | None
    proposed_revision_id: UUID | None
    proposed_snapshot: dict[str, object]
    content_hash: str
    sequence: int
    changeset_version: int
    created_at: datetime

    @classmethod
    def from_model(
        cls,
        item: ChangesetItem,
        *,
        changeset_version: int,
    ) -> "ChangesetItemResponse":
        return cls(
            id=item.id,
            changeset_id=item.changeset_id,
            paper_id=item.paper_id,
            object_id=item.object_id,
            object_kind=ObjectKind(item.object_kind),
            base_revision_id=item.base_revision_id,
            proposed_revision_id=item.proposed_revision_id,
            proposed_snapshot=item.proposed_snapshot,
            content_hash=item.content_hash,
            sequence=item.sequence,
            changeset_version=changeset_version,
            created_at=item.created_at,
        )


class ChangesetMutationResponse(BaseModel):
    changeset_id: UUID
    version: int


class _ProjectionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkspaceAssetResponse(_ProjectionModel):
    id: UUID
    url: str
    original_filename: str
    sha256: str = Field(min_length=64, max_length=64)
    byte_size: int = Field(ge=0)
    mime_type: str
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    page_count: int | None = Field(default=None, ge=1)
    category: AssetCategory
    access_level: AssetAccessLevel


class WorkspaceBoundsResponse(_ProjectionModel):
    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)


class WorkspaceProgressKindResponse(_ProjectionModel):
    total: int = Field(ge=0)
    resolved: int = Field(ge=0)
    blockers: int = Field(ge=0)


class WorkspaceProgressSummary(_ProjectionModel):
    scope_count: int = Field(ge=0)
    resolved_count: int = Field(ge=0)
    blocker_count: int = Field(ge=0)


class WorkspaceProgressResponse(WorkspaceProgressSummary):
    by_kind: dict[ObjectKind, WorkspaceProgressKindResponse]


class WorkspaceChangesetResponse(_ProjectionModel):
    id: UUID
    review_task_id: UUID
    paper_id: UUID
    owner_id: UUID
    base_release_id: UUID
    workflow_state: WorkflowState
    version: int = Field(ge=1)
    title: str
    reason: str


class WorkspacePaperResponse(_ProjectionModel):
    id: UUID
    paper_key: str
    title: str | None = None
    base_release_id: UUID


class WorkspaceDocumentResponse(_ProjectionModel):
    url: str
    release_id: UUID


class WorkspacePageResponse(_ProjectionModel):
    page_number: int = Field(ge=1)
    region_count: int = Field(ge=0)
    visual_object_count: int = Field(ge=0)
    proposal_count: int = Field(ge=0)
    blocker_count: int = Field(ge=0)


class WorkspaceRegionResponse(_ProjectionModel):
    id: UUID
    region_key: str
    revision_id: UUID
    page_number: int = Field(ge=1)
    bounds: WorkspaceBoundsResponse
    rotation: int
    asset_id: UUID | None = None
    asset: WorkspaceAssetResponse | None = None


class WorkspaceObjectBindingsResponse(_ProjectionModel):
    regions: list[dict[str, object]]
    assets: list[dict[str, object]]
    compounds: list[dict[str, object]]
    relations: list[dict[str, object]]


class WorkspaceVisualObjectResponse(_ProjectionModel):
    id: UUID
    object_key: str
    object_type: MoleculeObjectType
    revision_id: UUID
    snapshot: dict[str, object]
    queue_state: QueueState
    blocking: bool
    region_id: UUID | None = None
    bindings: WorkspaceObjectBindingsResponse


class WorkspaceProposalMachineResponse(_ProjectionModel):
    raw_values: dict[str, object]
    normalized_values: dict[str, object]


class WorkspaceMoleculeProposalResponse(_ProjectionModel):
    id: UUID
    paper_id: UUID
    visual_object_id: UUID
    proposal_key: str
    model_run_key: str
    revision_id: UUID
    disposition: MoleculeProposalDisposition
    machine: WorkspaceProposalMachineResponse
    review: dict[str, object]
    crop_asset: WorkspaceAssetResponse | None = None
    source_region_id: UUID | None = None


class WorkspaceStructureResponse(_ProjectionModel):
    id: UUID
    compound_id: UUID
    structure_key: str
    revision_id: UUID
    state: StructureState | None = None
    canonical_smiles: str | None = None
    snapshot: dict[str, object]


class WorkspaceSourceLocatorResponse(_ProjectionModel):
    visual_object_id: UUID
    region_id: UUID
    page_number: int = Field(ge=1)
    bounds: WorkspaceBoundsResponse
    source_asset_id: UUID | None = None
    crop_asset_id: UUID | None = None


class WorkspaceAttestationResponse(_ProjectionModel):
    id: UUID
    changeset_version: int = Field(ge=1)
    scope_hash: str = Field(min_length=64, max_length=64)
    item_count: int = Field(ge=0)
    resolved_count: int = Field(ge=0)
    blocker_count: int = Field(ge=0)
    statement: str


class WorkspaceScopeResponse(_ProjectionModel):
    id: UUID
    scope_hash: str = Field(min_length=64, max_length=64)
    item_count: int = Field(ge=0)


class WorkspaceResponse(_ProjectionModel):
    workspace_version: int = Field(ge=1)
    changeset: WorkspaceChangesetResponse
    paper: WorkspacePaperResponse
    progress: WorkspaceProgressResponse
    document: WorkspaceDocumentResponse
    pages: list[WorkspacePageResponse]
    regions: list[WorkspaceRegionResponse]
    visual_objects: list[WorkspaceVisualObjectResponse]
    molecule_proposals: list[WorkspaceMoleculeProposalResponse]
    structures: list[WorkspaceStructureResponse]
    evidence: list[dict[str, object]]
    assets: list[WorkspaceAssetResponse]
    source_locators: list[WorkspaceSourceLocatorResponse]
    attestation: WorkspaceAttestationResponse | None = None
    scope: WorkspaceScopeResponse


class MoleculeQueueVisualObjectResponse(_ProjectionModel):
    id: UUID
    object_key: str
    object_type: MoleculeObjectType
    region_id: UUID


class MoleculeQueueProposalResponse(_ProjectionModel):
    id: UUID
    proposal_key: str
    disposition: MoleculeProposalDisposition
    revision_id: UUID | None = None


class MoleculeQueueDeepLinkResponse(_ProjectionModel):
    view: str
    page: int = Field(ge=1)
    object: UUID
    proposal: UUID | None = None


class MoleculeObjectQueueItemResponse(_ProjectionModel):
    paper_id: UUID
    paper_key: str
    base_release_id: UUID
    review_task_id: UUID
    changeset_id: UUID | None = None
    changeset_version: int | None = Field(default=None, ge=1)
    visual_object: MoleculeQueueVisualObjectResponse
    proposal: MoleculeQueueProposalResponse | None = None
    crop_asset: WorkspaceAssetResponse | None = None
    page: int = Field(ge=1)
    state: QueueState
    blocking: bool
    reasons: list[str]
    paper_progress: WorkspaceProgressSummary
    deep_link: MoleculeQueueDeepLinkResponse
    priority: int = Field(ge=0)


class MoleculeQueueStatusCounts(_ProjectionModel):
    localization_or_split: int = Field(ge=0)
    needs_ocsr: int = Field(ge=0)
    proposal_review: int = Field(ge=0)
    source_or_attachment: int = Field(ge=0)
    structure_assembly: int = Field(ge=0)
    complete: int = Field(ge=0)


class MoleculeQueuePaginationResponse(_ProjectionModel):
    limit: int = Field(ge=1, le=100)
    returned: int = Field(ge=0)


class MoleculeObjectQueueResponse(_ProjectionModel):
    items: list[MoleculeObjectQueueItemResponse]
    next_cursor: str | None = None
    status_counts: MoleculeQueueStatusCounts
    pagination: MoleculeQueuePaginationResponse
