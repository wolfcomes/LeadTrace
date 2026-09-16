from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict

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


__all__ = ["AssignmentRequest", "AssignmentResponse", "PaperSectionReviewResponse"]
