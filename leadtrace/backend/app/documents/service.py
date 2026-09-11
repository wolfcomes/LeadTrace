from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assets.models import (
    Asset,
    AssetAccessLevel,
    AssetCategory,
    AssetIntegrityState,
)
from app.assets.storage import (
    AssetMimeMismatchError,
    AssetPathError,
    InspectedFile,
    LocalAssetStore,
)
from app.imports.models import ImportAssetLink
from app.papers.models import Paper
from app.reviews.models import ReviewTask, ReviewTaskStatus
from app.security.permissions import enforce_permission
from app.security.policies import Action, Principal, ResourceScope
from app.users.models import UserRole


class DocumentKind(StrEnum):
    ARTICLE = "article"
    SI = "si"

    @property
    def asset_category(self) -> AssetCategory:
        return (
            AssetCategory.ARTICLE_PDF
            if self is DocumentKind.ARTICLE
            else AssetCategory.SI_PDF
        )

    @property
    def link_role(self) -> str:
        return f"{self.value}_pdf"


class DocumentNotFound(LookupError):
    """The document is not available to the application."""


class RangeNotSatisfiable(ValueError):
    """The requested byte range cannot be served."""

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
    """Parse one RFC 9110 byte range, rejecting multi-range requests."""

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
    """Authorize and resolve immutable registered source PDFs."""

    def resolve(
        self,
        session: Session,
        *,
        paper_id: UUID,
        kind: DocumentKind,
        principal: Principal,
        store: LocalAssetStore,
        range_header: str | None,
    ) -> ProtectedDocument:
        paper = session.get(Paper, paper_id)
        if paper is None:
            raise DocumentNotFound

        assigned_reviewer_ids = frozenset(
            session.scalars(
                select(ReviewTask.assigned_reviewer_id).where(
                    ReviewTask.paper_id == paper.id,
                    ReviewTask.status != ReviewTaskStatus.COMPLETED,
                )
            )
        )
        enforce_permission(
            principal,
            Action.READ_FULL_PDF,
            ResourceScope(
                is_published=True,
                assigned_reviewer_ids=assigned_reviewer_ids,
            ),
        )

        asset = session.scalar(
            select(Asset)
            .join(ImportAssetLink, ImportAssetLink.asset_id == Asset.id)
            .where(
                ImportAssetLink.record_type == "paper",
                ImportAssetLink.original_id == paper.paper_key,
                ImportAssetLink.link_role == kind.link_role,
                Asset.category == kind.asset_category,
                Asset.integrity_state == AssetIntegrityState.VERIFIED,
            )
            .order_by(Asset.created_at.desc(), ImportAssetLink.id.desc())
            .limit(1)
        )
        if asset is None:
            raise DocumentNotFound
        if (
            asset.integrity_state is not AssetIntegrityState.VERIFIED
            or asset.mime_type != "application/pdf"
            or (
                principal.role is not UserRole.ADMIN
                and asset.access_level is not AssetAccessLevel.REVIEWER
            )
        ):
            raise DocumentNotFound

        try:
            inspected = store.inspect(
                asset.storage_key,
                validate_extension=False,
                validate_content=False,
            )
        except (AssetPathError, AssetMimeMismatchError, FileNotFoundError, OSError):
            asset.integrity_state = AssetIntegrityState.MISSING
            raise DocumentNotFound from None
        if not self._matches_registered_asset(asset, inspected):
            asset.integrity_state = AssetIntegrityState.CORRUPT
            raise DocumentNotFound

        byte_range = parse_range_header(range_header, asset.byte_size)
        return ProtectedDocument(
            paper=paper,
            asset=asset,
            path=inspected.path,
            byte_range=byte_range,
            full_size=asset.byte_size,
        )

    @staticmethod
    def _matches_registered_asset(asset: Asset, inspected: InspectedFile) -> bool:
        return (
            inspected.sha256 == asset.sha256
            and inspected.byte_size == asset.byte_size
            and inspected.mime_type == "application/pdf"
        )


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
