from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.catalog.models import PaperSource, PaperSourceIntegrityState
from app.papers.models import Paper, PaperCatalogState


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

    @classmethod
    def from_models(
        cls,
        paper: Paper,
        source: PaperSource,
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
        )


class PaperCatalogPage(CatalogProjection):
    items: list[PaperCatalogResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)


__all__ = [
    "PaperCatalogPage",
    "PaperCatalogResponse",
    "PaperSourceResponse",
]
