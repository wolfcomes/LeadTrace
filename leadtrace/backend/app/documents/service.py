from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assets.models import Asset, AssetCategory, AssetIntegrityState
from app.assets.storage import AssetMimeMismatchError, AssetPathError, InspectedFile, LocalAssetStore
from app.catalog.models import PaperSource, PaperSourceIntegrityState
from app.papers.models import Paper
from app.security.permissions import enforce_permission
from app.security.policies import Action, Principal, ResourceScope
from app.workspaces.models import ReviewTask, ReviewTaskState


class DocumentNotFound(LookupError):
    pass


class RangeNotSatisfiable(ValueError):
    def __init__(self, message: str, size: int) -> None:
        super().__init__(message)
        self.size = size


@dataclass(frozen=True, slots=True)
class ByteRange:
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


@dataclass(frozen=True, slots=True)
class ProtectedDocument:
    paper: Paper
    asset: Asset
    path: Path
    byte_range: ByteRange
    full_size: int


def parse_range_header(value: str | None, size: int) -> ByteRange:
    if size <= 0:
        raise RangeNotSatisfiable("Empty document", size)
    if value is None:
        return ByteRange(0, size - 1)
    if not value.startswith("bytes="):
        raise RangeNotSatisfiable("Unsupported range unit", size)
    expression = value[6:].strip()
    if not expression or "," in expression or expression.count("-") != 1:
        raise RangeNotSatisfiable("Only one byte range is supported", size)
    start_text, end_text = expression.split("-", 1)
    if start_text and not start_text.isdigit():
        raise RangeNotSatisfiable("Invalid range start", size)
    if end_text and not end_text.isdigit():
        raise RangeNotSatisfiable("Invalid range end", size)
    if not start_text and not end_text:
        raise RangeNotSatisfiable("Empty range", size)
    if not start_text:
        suffix_length = int(end_text)
        if suffix_length <= 0:
            raise RangeNotSatisfiable("Invalid suffix range", size)
        return ByteRange(max(size - suffix_length, 0), size - 1)
    start = int(start_text)
    if start >= size:
        raise RangeNotSatisfiable("Range starts beyond document", size)
    end = size - 1 if not end_text else min(int(end_text), size - 1)
    if end < start:
        raise RangeNotSatisfiable("Range ends before it starts", size)
    return ByteRange(start, end)


class DocumentService:
    def resolve(self, session: Session, *, paper_id: UUID, principal: Principal, store: LocalAssetStore, range_header: str | None) -> ProtectedDocument:
        row = session.execute(
            select(Paper, PaperSource, Asset)
            .join(PaperSource, PaperSource.id == Paper.source_id)
            .join(Asset, Asset.id == PaperSource.asset_id)
            .where(Paper.id == paper_id)
        ).one_or_none()
        if row is None:
            raise DocumentNotFound
        paper, source, asset = row
        assigned_reviewer_ids = frozenset(session.scalars(select(ReviewTask.assigned_reviewer_id).where(ReviewTask.paper_id == paper.id, ReviewTask.status != ReviewTaskState.APPROVED)))
        enforce_permission(principal, Action.READ_FULL_PDF, ResourceScope(assigned_reviewer_ids=assigned_reviewer_ids))
        if (
            source.integrity_state is not PaperSourceIntegrityState.VERIFIED
            or asset.integrity_state is not AssetIntegrityState.VERIFIED
            or source.sha256 != asset.sha256
            or source.byte_size != asset.byte_size
            or asset.category is not AssetCategory.ARTICLE_PDF
            or asset.mime_type != "application/pdf"
        ):
            raise DocumentNotFound
        try:
            inspected = store.inspect(asset.storage_key, validate_extension=False, validate_content=False)
        except (AssetPathError, AssetMimeMismatchError, FileNotFoundError, OSError):
            asset.integrity_state = AssetIntegrityState.MISSING
            source.integrity_state = PaperSourceIntegrityState.MISSING
            raise DocumentNotFound from None
        if not self._matches_registered_source(source, asset, inspected):
            asset.integrity_state = AssetIntegrityState.CORRUPT
            source.integrity_state = PaperSourceIntegrityState.CORRUPT
            raise DocumentNotFound
        byte_range = parse_range_header(range_header, asset.byte_size)
        return ProtectedDocument(paper, asset, inspected.path, byte_range, asset.byte_size)

    @staticmethod
    def _matches_registered_source(source: PaperSource, asset: Asset, inspected: InspectedFile) -> bool:
        return inspected.sha256 == source.sha256 == asset.sha256 and inspected.byte_size == source.byte_size == asset.byte_size and inspected.mime_type == "application/pdf"


def iter_file_range(path: Path, byte_range: ByteRange):
    with path.open("rb") as handle:
        handle.seek(byte_range.start)
        remaining = byte_range.length
        while remaining > 0:
            chunk = handle.read(min(1024 * 1024, remaining))
            if not chunk:
                return
            remaining -= len(chunk)
            yield chunk
