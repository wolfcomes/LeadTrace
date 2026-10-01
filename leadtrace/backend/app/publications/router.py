from __future__ import annotations

from collections.abc import Iterator
from typing import Any, BinaryIO
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.errors import APIError
from app.assets.models import Asset, AssetCategory, AssetIntegrityState
from app.assets.responses import SnapshotStreamingResponse
from app.assets.service import AssetService
from app.assets.storage import LocalAssetStore
from app.database import get_db_session
from app.publications.schemas import (
    PublishedPaperDetailResponse,
    PublishedPaperListItem,
    PublishedPaperListResponse,
    PublishedPaperSnapshotResponse,
)
from app.publications.service import (
    DecisionNotFoundError,
    PublicationService,
    PublishedPaper,
)
from app.security.permissions import (
    RouteAccess,
    declare_route_access,
    require_published_data,
)
from app.security.policies import Action, Principal
from app.workspaces.schemas import BibliographyResponse


_PUBLISHED_ASSET_CATEGORIES = frozenset(
    {
        AssetCategory.RDKIT_STRUCTURE,
        AssetCategory.EVIDENCE_CROP,
        AssetCategory.REVIEWED_CROP,
    }
)


def _stream_snapshot(snapshot: BinaryIO) -> Iterator[bytes]:
    try:
        while chunk := snapshot.read(1024 * 1024):
            yield chunk
    finally:
        snapshot.close()


def _referenced_asset_ids(snapshot: dict[str, Any]) -> frozenset[UUID]:
    references: set[UUID] = set()
    for section, field in (
        ("structures", "depiction_asset_id"),
        ("structure_source_images", "crop_asset_id"),
        ("evidence", "crop_asset_id"),
    ):
        rows = snapshot.get(section, [])
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            value = row.get(field)
            if isinstance(value, str):
                try:
                    references.add(UUID(value))
                except ValueError:
                    continue
    return frozenset(references)


def _paper_snapshot(version: PublishedPaper) -> dict[str, Any]:
    snapshot = version.version.snapshot
    paper = snapshot.get("paper")
    if not isinstance(paper, dict):
        raise RuntimeError("Published snapshot bibliography is invalid")
    return paper


def _bibliography(version: PublishedPaper) -> BibliographyResponse:
    paper = _paper_snapshot(version)
    return BibliographyResponse.model_validate(
        {
            "paper_id": paper["id"],
            "paper_key": paper["paper_key"],
            "title": paper["title"],
            "journal": paper["journal"],
            "publication_year": paper["publication_year"],
            "volume": paper["volume"],
            "issue": paper["issue"],
            "doi": paper.get("doi"),
            **{k: paper[k] for k in ("abstract", "abstract_source", "pdb_references") if k in paper},
        }
    )


def _list_item(version: PublishedPaper) -> PublishedPaperListItem:
    bibliography = _bibliography(version)
    return PublishedPaperListItem(
        paper_id=bibliography.paper_id,
        paper_key=bibliography.paper_key,
        title=bibliography.title,
        journal=bibliography.journal,
        publication_year=bibliography.publication_year,
        volume=bibliography.volume,
        issue=bibliography.issue,
        doi=bibliography.doi,
        version_number=version.version.version_number,
        content_hash=version.version.content_hash,
        published_at=version.version.published_at,
    )


def create_publications_router() -> APIRouter:
    router = APIRouter(prefix="/api/v2/papers", tags=["published papers"])
    service = PublicationService()

    @router.get("", response_model=PublishedPaperListResponse)
    @declare_route_access(RouteAccess.PERMISSION, Action.READ_PUBLISHED_DATA)
    def list_published_papers(
        session: Session = Depends(get_db_session),
        _: Principal = Depends(require_published_data),
    ) -> PublishedPaperListResponse:
        with session.begin():
            published = service.list_published_papers(session)
            items = [_list_item(version) for version in published]
        return PublishedPaperListResponse(items=items, total=len(items))

    @router.get("/{paper_id}", response_model=PublishedPaperDetailResponse)
    @declare_route_access(RouteAccess.PERMISSION, Action.READ_PUBLISHED_DATA)
    def get_published_paper(
        paper_id: UUID,
        session: Session = Depends(get_db_session),
        _: Principal = Depends(require_published_data),
    ) -> PublishedPaperDetailResponse:
        try:
            with session.begin():
                published = service.get_published_paper(session, paper_id=paper_id)
                return PublishedPaperDetailResponse(
                    paper_id=published.paper.id,
                    version_id=published.version.id,
                    version_number=published.version.version_number,
                    content_hash=published.version.content_hash,
                    published_at=published.version.published_at,
                    bibliography=_bibliography(published),
                    snapshot=PublishedPaperSnapshotResponse.model_validate(
                        published.version.snapshot
                    ),
                )
        except DecisionNotFoundError as error:
            raise APIError(404, "RESOURCE_NOT_FOUND", "Resource not found") from error

    @router.get("/{paper_id}/assets/{asset_id}")
    @declare_route_access(RouteAccess.PERMISSION, Action.READ_PUBLISHED_DATA)
    def get_published_asset(
        paper_id: UUID,
        asset_id: UUID,
        request: Request,
        session: Session = Depends(get_db_session),
        _: Principal = Depends(require_published_data),
    ) -> StreamingResponse:
        snapshot_file: BinaryIO | None = None
        try:
            with session.begin():
                published = service.get_published_paper(session, paper_id=paper_id)
                if asset_id not in _referenced_asset_ids(published.version.snapshot):
                    raise HTTPException(status_code=404, detail="Resource not found")
                asset = session.get(Asset, asset_id)
                if (
                    asset is None
                    or asset.integrity_state is not AssetIntegrityState.VERIFIED
                    or asset.category not in _PUBLISHED_ASSET_CATEGORIES
                    or not asset.storage_key.startswith("managed/")
                ):
                    raise HTTPException(status_code=404, detail="Resource not found")
                settings = request.app.state.settings
                store = LocalAssetStore(
                    settings.asset_root,
                    source_roots=settings.source_roots,
                )
                snapshot_file = AssetService.open_verified_content(asset, store)
                if snapshot_file is None:
                    raise HTTPException(status_code=404, detail="Resource not found")
                media_type = asset.mime_type
                content_length = asset.byte_size
                filename = asset.original_filename.replace("\r", "").replace("\n", "")
        except DecisionNotFoundError as error:
            if snapshot_file is not None:
                snapshot_file.close()
            raise APIError(404, "RESOURCE_NOT_FOUND", "Resource not found") from error
        except BaseException:
            if snapshot_file is not None:
                snapshot_file.close()
            raise
        if snapshot_file is None:
            raise APIError(404, "RESOURCE_NOT_FOUND", "Resource not found")
        encoded_filename = quote(filename)
        disposition = (
            f'inline; filename="{filename}"'
            if encoded_filename == filename
            else f"inline; filename*=utf-8''{encoded_filename}"
        )
        return SnapshotStreamingResponse(
            snapshot=snapshot_file,
            content=_stream_snapshot(snapshot_file),
            media_type=media_type,
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": disposition,
                "Content-Length": str(content_length),
            },
        )

    return router


__all__ = ["create_publications_router"]
