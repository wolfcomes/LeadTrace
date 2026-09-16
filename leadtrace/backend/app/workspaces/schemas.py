from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class BibliographyResponse(WorkspaceProjection):
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


class BibliographyUpdateRequest(WorkspaceProjection):
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
        editable = {"title", "journal", "publication_year", "volume", "issue", "doi"}
        changed = self.model_fields_set & editable
        if not changed:
            raise ValueError("At least one bibliography field is required")
        nonnullable = changed - {"doi"}
        if any(getattr(self, field) is None for field in nonnullable):
            raise ValueError("Bibliography fields except DOI cannot be null or blank")
        return self

    def updates(self) -> dict[str, str | int | None]:
        return {
            field: getattr(self, field)
            for field in (
                "title",
                "journal",
                "publication_year",
                "volume",
                "issue",
                "doi",
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


__all__ = [
    "AssignmentRequest",
    "AssignmentResponse",
    "BibliographyResponse",
    "BibliographyUpdateRequest",
    "PaperSectionReviewResponse",
    "ReviewTaskListResponse",
    "ReviewTaskResponse",
    "SectionUpdateRequest",
    "WorkspaceResponse",
    "WorkspaceSourceResponse",
]
