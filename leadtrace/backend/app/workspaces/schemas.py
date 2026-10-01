from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.papers.metadata import ArticleMetadata, PdbReference

from app.workspaces.models import (
    PaperSection,
    PaperSectionReview,
    PaperSectionState,
    PaperWorkspace,
    ReviewTask,
    ReviewTaskState,
    WorkspaceState,
)


class WorkspaceProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssignmentRequest(WorkspaceProjection):
    reviewer_id: UUID


class PaperSectionReviewResponse(WorkspaceProjection):
    section_key: PaperSection
    state: PaperSectionState
    note: str | None

    @classmethod
    def from_model(
        cls,
        section: PaperSectionReview,
    ) -> "PaperSectionReviewResponse":
        return cls(
            section_key=section.section_key,
            state=section.state,
            note=section.note,
        )


class AssignmentResponse(WorkspaceProjection):
    review_task_id: UUID
    workspace_id: UUID
    paper_id: UUID
    assigned_reviewer_id: UUID
    task_status: ReviewTaskState
    task_version: int
    workspace_state: WorkspaceState
    workspace_version: int
    sections: list[PaperSectionReviewResponse]

    @classmethod
    def from_models(
        cls,
        task: ReviewTask,
        workspace: PaperWorkspace,
        sections: list[PaperSectionReview],
    ) -> "AssignmentResponse":
        return cls(
            review_task_id=task.id,
            workspace_id=workspace.id,
            paper_id=task.paper_id,
            assigned_reviewer_id=task.assigned_reviewer_id,
            task_status=task.status,
            task_version=task.version,
            workspace_state=workspace.state,
            workspace_version=workspace.version,
            sections=[
                PaperSectionReviewResponse.from_model(section)
                for section in sections
            ],
        )


class WorkspaceSourceResponse(WorkspaceProjection):
    asset_id: UUID
    source_root_key: str
    source_key: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_count: int = Field(ge=1)


class BibliographyResponse(ArticleMetadata, WorkspaceProjection):
    paper_id: UUID
    paper_key: str
    title: str
    journal: str
    publication_year: int
    volume: str
    issue: str
    doi: str | None


class ReviewTaskResponse(WorkspaceProjection):
    review_task_id: UUID
    workspace_id: UUID
    paper_id: UUID
    paper_key: str
    title: str
    task_status: ReviewTaskState
    task_version: int
    workspace_state: WorkspaceState
    workspace_version: int


class ReviewTaskListResponse(WorkspaceProjection):
    items: list[ReviewTaskResponse]
    total: int


class WorkspaceResponse(WorkspaceProjection):
    id: UUID
    review_task_id: UUID
    assigned_reviewer_id: UUID
    state: WorkspaceState
    version: int
    task_status: ReviewTaskState
    bibliography: BibliographyResponse
    source: WorkspaceSourceResponse
    sections: list[PaperSectionReviewResponse]


class BibliographyUpdateRequest(ArticleMetadata, WorkspaceProjection):
    expected_workspace_version: int = Field(ge=1)
    title: str | None = Field(default=None, max_length=1024)
    journal: str | None = Field(default=None, max_length=255)
    publication_year: int | None = Field(default=None, ge=1000, le=9999)
    volume: str | None = Field(default=None, max_length=64)
    issue: str | None = Field(default=None, max_length=64)
    doi: str | None = Field(default=None, max_length=255)

    @field_validator("title", "journal", "volume", "issue", "doi")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_updates(self) -> "BibliographyUpdateRequest":
        editable = {"title", "journal", "publication_year", "volume", "issue", "doi", "abstract", "abstract_source", "pdb_references"}
        changed = self.model_fields_set & editable
        if not changed:
            raise ValueError("At least one bibliography field is required")
        nonnullable = changed - {"doi", "abstract", "abstract_source"}
        if any(getattr(self, field) is None for field in nonnullable):
            raise ValueError("Bibliography fields except DOI cannot be null or blank")
        return self

    def updates(self) -> dict[str, str | int | None]:
        return {
            field: ([x.model_dump(mode="json") for x in self.pdb_references] if field == "pdb_references" else getattr(self, field))
            for field in (
                "title",
                "journal",
                "publication_year",
                "volume",
                "issue",
                "doi", "abstract", "abstract_source", "pdb_references",
            )
            if field in self.model_fields_set
        }


class SectionUpdateRequest(WorkspaceProjection):
    expected_workspace_version: int = Field(ge=1)
    state: PaperSectionState
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SubmissionRequest(WorkspaceProjection):
    expected_workspace_version: int = Field(ge=1)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)
    reviewer_note: str | None = Field(default=None, max_length=10_000)

    @field_validator("idempotency_key", "reviewer_note")
    @classmethod
    def normalize_submission_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SubmissionBlockerResponse(WorkspaceProjection):
    code: str
    message: str
    entity_type: str
    entity_id: UUID | None
    section_key: PaperSection | None


class SubmissionResponse(WorkspaceProjection):
    id: UUID
    paper_id: UUID
    workspace_id: UUID
    review_task_id: UUID
    submission_number: int
    idempotency_key: str
    snapshot: dict[str, object]
    content_hash: str
    workspace_version: int
    submitted_by_id: UUID
    reviewer_note: str | None
    submitted_at: datetime


class SubmissionMutationResponse(WorkspaceProjection):
    submission: SubmissionResponse
    workspace_version: int


class SubmissionValidationResponse(WorkspaceProjection):
    valid: bool
    blockers: list[SubmissionBlockerResponse]


__all__ = [
    "AssignmentRequest",
    "AssignmentResponse",
    "BibliographyResponse",
    "BibliographyUpdateRequest",
    "PaperSectionReviewResponse",
    "ReviewTaskListResponse",
    "ReviewTaskResponse",
    "SectionUpdateRequest",
    "SubmissionBlockerResponse",
    "SubmissionMutationResponse",
    "SubmissionRequest",
    "SubmissionResponse",
    "SubmissionValidationResponse",
    "WorkspaceResponse",
    "WorkspaceSourceResponse",
]
