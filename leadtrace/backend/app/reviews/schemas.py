from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.revisions.models import ObjectKind
from app.reviews.models import Changeset, ChangesetItem, ReviewTask, ReviewTaskStatus
from app.security.policies import WorkflowState


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
    submitted_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, changeset: Changeset) -> "ChangesetResponse":
        return cls.model_validate(changeset)


class ChangesetTransitionRequest(BaseModel):
    expected_version: int = Field(ge=1)


class ChangesetItemCreateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    object_id: UUID
    object_kind: ObjectKind
    base_revision_id: UUID | None = None
    proposed_snapshot: dict[str, object]
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
