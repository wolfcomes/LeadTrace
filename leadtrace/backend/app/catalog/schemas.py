from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.ai_prefill.schemas import AiPrefillStatusResponse
from app.catalog.models import PaperSource, PaperSourceIntegrityState
from app.papers.models import Paper, PaperCatalogState
from app.workspaces.models import ReviewTaskState, WorkspaceState


class CatalogProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PaperSourceResponse(CatalogProjection):
    id: UUID
    asset_id: UUID
    source_root_key: str
    source_key: str
    sha256: str = Field(min_length=64, max_length=64)
    byte_size: int = Field(gt=0)
    page_count: int = Field(gt=0)
    integrity_state: PaperSourceIntegrityState

    @classmethod
    def from_source(cls, source: PaperSource) -> "PaperSourceResponse":
        return cls(
            id=source.id,
            asset_id=source.asset_id,
            source_root_key=source.source_root_key,
            source_key=source.source_key,
            sha256=source.sha256,
            byte_size=source.byte_size,
            page_count=source.page_count,
            integrity_state=source.integrity_state,
        )


class CatalogReviewResponse(CatalogProjection):
    review_task_id: UUID
    workspace_id: UUID
    assigned_reviewer_id: UUID | None
    assignee_display_name: str | None
    task_status: ReviewTaskState
    workspace_state: WorkspaceState
    sections_resolved: int = Field(ge=0, le=6)
    sections_total: int = Field(ge=0, le=6)
    submission_state: Literal[
        "not_submitted",
        "submitted",
        "changes_requested",
        "approved",
    ]


class PaperCatalogResponse(CatalogProjection):
    id: UUID
    paper_key: str
    title: str
    journal: str
    publication_year: int
    volume: str
    issue: str
    doi: str | None
    catalog_state: PaperCatalogState
    source: PaperSourceResponse
    review: CatalogReviewResponse | None
    ai_prefill: AiPrefillStatusResponse

    @classmethod
    def from_models(
        cls,
        paper: Paper,
        source: PaperSource,
        review: CatalogReviewResponse | None = None,
        ai_prefill: AiPrefillStatusResponse | None = None,
    ) -> "PaperCatalogResponse":
        return cls(
            id=paper.id,
            paper_key=paper.paper_key,
            title=paper.title,
            journal=paper.journal,
            publication_year=paper.publication_year,
            volume=paper.volume,
            issue=paper.issue,
            doi=paper.doi,
            catalog_state=paper.catalog_state,
            source=PaperSourceResponse.from_source(source),
            review=review,
            ai_prefill=ai_prefill or AiPrefillStatusResponse(
                run=None,
                can_start=False,
                blocked_reason="Assign a Reviewer before AI prefill",
            ),
        )


class PaperCatalogPage(CatalogProjection):
    items: list[PaperCatalogResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)


__all__ = [
    "CatalogReviewResponse",
    "PaperCatalogPage",
    "PaperCatalogResponse",
    "PaperSourceResponse",
]
