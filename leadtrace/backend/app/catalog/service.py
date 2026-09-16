from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assets.models import Asset, AssetAccessLevel, AssetCategory, AssetIntegrityState
from app.assets.storage import AssetPathError, LocalAssetStore
from app.catalog.extraction import (
    CatalogCollection,
    CatalogExtractionError,
    ExtractedCatalogMetadata,
    extract_catalog_metadata,
)
from app.catalog.models import PaperSource, PaperSourceIntegrityState
from app.db.model_registry import load_model_registry
from app.papers.models import Paper, PaperCatalogState


class CatalogImportError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CatalogImportResult:
    verified_count: int
    created_count: int
    unchanged_count: int


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ROOT_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _required_string(payload: dict[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise CatalogImportError(f"manifest {name} must be a nonempty string")
    return value


def _relative_posix(value: str, *, label: str) -> PurePosixPath:
    if "\\" in value or value.endswith("/"):
        raise CatalogImportError(f"manifest {label} must be relative POSIX")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise CatalogImportError(f"manifest {label} must be relative POSIX")
    if path.as_posix() != value:
        raise CatalogImportError(f"manifest {label} must be relative POSIX")
    return path


def _journal_code(journal: str) -> str:
    if journal.casefold() == "journal of medicinal chemistry":
        return "JMC"
    words = re.findall(r"[A-Za-z0-9]+", journal)
    return "".join(word[0] for word in words).upper()[:12] or "JRN"


class CatalogImportService:
    def __init__(self, manifest_path: Path, asset_store: LocalAssetStore) -> None:
        load_model_registry()
        self.manifest_path = Path(manifest_path).resolve(strict=True)
        self.asset_store = asset_store
        try:
            self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CatalogImportError("manifest is not valid JSON") from error
        if not isinstance(self.manifest, dict):
            raise CatalogImportError("manifest must be an object")
        schema_version = self.manifest.get("schema_version")
        if type(schema_version) is not int or schema_version != 1:
            raise CatalogImportError("unsupported manifest schema")
        self.root_key = _required_string(self.manifest, "source_root_key")
        if not _ROOT_KEY.fullmatch(self.root_key) or self.root_key in {".", ".."}:
            raise CatalogImportError("manifest source_root_key must be logical")
        self.source_directory = _relative_posix(
            _required_string(self.manifest, "source_directory"),
            label="source_directory",
        )
        created_on = _required_string(self.manifest, "created_on")
        try:
            self.created_on = date.fromisoformat(created_on)
        except ValueError as error:
            raise CatalogImportError("manifest created_on must be an ISO date") from error
        self.entries = self.manifest.get("entries")
        if not isinstance(self.entries, list) or len(self.entries) != 20:
            raise CatalogImportError("manifest must contain exactly 20 entries")
        collection = self.manifest.get("collection")
        if not isinstance(collection, dict):
            raise CatalogImportError("manifest collection is required")
        try:
            journal = _required_string(collection, "journal")
            publication_year = collection["publication_year"]
            volume = _required_string(collection, "volume")
            issue = _required_string(collection, "issue")
        except (KeyError, TypeError) as error:
            raise CatalogImportError("manifest collection is incomplete") from error
        if type(publication_year) is not int or not 1000 <= publication_year <= 9999:
            raise CatalogImportError("manifest publication_year is invalid")
        self.collection = CatalogCollection(journal, publication_year, volume, issue)
        self._validate_entries()

    def _validate_entries(self) -> None:
        orders: list[int] = []
        source_keys: set[str] = set()
        hashes: set[str] = set()
        for raw_entry in self.entries:
            if not isinstance(raw_entry, dict):
                raise CatalogImportError("manifest entry must be an object")
            order = raw_entry.get("manifest_order")
            if type(order) is not int:
                raise CatalogImportError("manifest_order must be an integer")
            orders.append(order)
            source_key = _required_string(raw_entry, "source_key")
            source_path = _relative_posix(source_key, label="source_key")
            filename = _required_string(raw_entry, "original_filename")
            if (
                source_path.parent != self.source_directory
                or source_path.name != filename
                or source_path.suffix != ".pdf"
            ):
                raise CatalogImportError(
                    "manifest source_key must be a direct lowercase .pdf child of source_directory"
                )
            digest = _required_string(raw_entry, "sha256")
            byte_size = raw_entry.get("byte_size")
            if not _SHA256.fullmatch(digest):
                raise CatalogImportError("manifest SHA-256 is invalid")
            if not isinstance(byte_size, int) or byte_size <= 0:
                raise CatalogImportError("manifest byte_size is invalid")
            if source_key in source_keys or digest in hashes:
                raise CatalogImportError("manifest contains duplicate source or SHA-256")
            source_keys.add(source_key)
            hashes.add(digest)
        if orders != list(range(1, 21)):
            raise CatalogImportError("manifest_order must be exactly 1..20")

    def _preflight(self) -> list[tuple[dict[str, Any], ExtractedCatalogMetadata, str]]:
        root_key = self.root_key
        verified: list[tuple[dict[str, Any], ExtractedCatalogMetadata, str]] = []
        seen_hashes: set[str] = set()
        for raw_entry in self.entries:
            source_key = str(raw_entry["source_key"])
            try:
                storage_key = self.asset_store.source_storage_key(root_key, source_key)
                extracted = extract_catalog_metadata(
                    self.asset_store.path_for(storage_key),
                    self.collection,
                )
            except CatalogExtractionError as error:
                raise CatalogImportError(
                    f"cannot verify {source_key}: {error}"
                ) from error
            except (AssetPathError, OSError) as error:
                raise CatalogImportError(
                    f"cannot verify source PDF: {source_key}"
                ) from error
            expected_hash = str(raw_entry["sha256"])
            if str(raw_entry.get("original_filename")) != Path(source_key).name:
                raise CatalogImportError(f"filename mismatch for {source_key}")
            if extracted.sha256 != expected_hash:
                raise CatalogImportError(f"SHA-256 mismatch for {source_key}")
            if extracted.byte_size != int(raw_entry["byte_size"]):
                raise CatalogImportError(f"byte size mismatch for {source_key}")
            if extracted.sha256 in seen_hashes:
                raise CatalogImportError("duplicate SHA-256 in manifest")
            seen_hashes.add(extracted.sha256)
            verified.append((raw_entry, extracted, storage_key))
        return verified

    def preview(self) -> CatalogImportResult:
        verified = self._preflight()
        return CatalogImportResult(verified_count=len(verified), created_count=0, unchanged_count=0)

    def _paper_key(self, order: int) -> str:
        return (
            f"LT-{_journal_code(self.collection.journal)}-"
            f"{self.collection.publication_year}-{self.collection.volume}-"
            f"{self.collection.issue.zfill(2)}-{order:03d}"
        )

    @staticmethod
    def _asset_matches(
        asset: Asset,
        *,
        raw_entry: dict[str, Any],
        extracted: ExtractedCatalogMetadata,
        storage_key: str,
        root_key: str,
        source_key: str,
    ) -> bool:
        return (
            asset.storage_key == storage_key
            and asset.original_filename == raw_entry["original_filename"]
            and asset.sha256 == extracted.sha256
            and asset.byte_size == extracted.byte_size
            and asset.mime_type == "application/pdf"
            and asset.width is None
            and asset.height is None
            and asset.page_count == extracted.page_count
            and asset.category == AssetCategory.ARTICLE_PDF
            and asset.access_level == AssetAccessLevel.REVIEWER
            and asset.integrity_state == AssetIntegrityState.VERIFIED
            and asset.source_asset_id is None
            and asset.derivation_metadata == {}
            and asset.source_metadata
            == {"source_root_key": root_key, "source_key": source_key}
        )

    def _paper_matches(
        self,
        paper: Paper,
        *,
        source_id: object,
        extracted: ExtractedCatalogMetadata,
        order: int,
    ) -> bool:
        return (
            paper.source_id == source_id
            and paper.paper_key == self._paper_key(order)
            and paper.title == extracted.title
            and paper.journal == extracted.journal
            and paper.publication_year == extracted.publication_year
            and paper.volume == extracted.volume
            and paper.issue == extracted.issue
            and paper.doi == extracted.doi
            and paper.catalog_state == PaperCatalogState.EXTRACTED
        )

    def _verify_exact_replay(
        self,
        session: Session,
        verified: list[tuple[dict[str, Any], ExtractedCatalogMetadata, str]],
    ) -> bool:
        sources = session.scalars(select(PaperSource)).all()
        papers = session.scalars(select(Paper)).all()
        if not sources and not papers:
            return False
        if len(sources) != 20 or len(papers) != 20:
            raise CatalogImportError("nonempty catalog is not an exact replay")
        sources_by_key = {(source.source_root_key, source.source_key): source for source in sources}
        papers_by_source = {paper.source_id: paper for paper in papers}
        for raw_entry, extracted, storage_key in verified:
            source_key = str(raw_entry["source_key"])
            source = sources_by_key.get((self.root_key, source_key))
            if source is None:
                raise CatalogImportError("nonempty catalog is not an exact replay")
            asset = session.get(Asset, source.asset_id)
            paper = papers_by_source.get(source.id)
            if (
                asset is None
                or paper is None
                or source.sha256 != extracted.sha256
                or source.byte_size != extracted.byte_size
                or source.page_count != extracted.page_count
                or source.integrity_state != PaperSourceIntegrityState.VERIFIED
                or not self._asset_matches(
                    asset,
                    raw_entry=raw_entry,
                    extracted=extracted,
                    storage_key=storage_key,
                    root_key=self.root_key,
                    source_key=source_key,
                )
                or not self._paper_matches(
                    paper,
                    source_id=source.id,
                    extracted=extracted,
                    order=int(raw_entry["manifest_order"]),
                )
            ):
                raise CatalogImportError("nonempty catalog is not an exact replay")
        return True

    def apply(self, session: Session) -> CatalogImportResult:
        verified = self._preflight()
        if self._verify_exact_replay(session, verified):
            return CatalogImportResult(len(verified), 0, len(verified))
        created = unchanged = 0
        for raw_entry, extracted, storage_key in verified:
            source_key = str(raw_entry["source_key"])
            asset = session.scalar(
                select(Asset).where(
                    Asset.storage_key == storage_key,
                    Asset.sha256 == extracted.sha256,
                )
            )
            if asset is None:
                asset = Asset(
                    storage_key=storage_key,
                    original_filename=str(raw_entry["original_filename"]),
                    sha256=extracted.sha256,
                    byte_size=extracted.byte_size,
                    mime_type="application/pdf",
                    page_count=extracted.page_count,
                    category=AssetCategory.ARTICLE_PDF,
                    access_level=AssetAccessLevel.REVIEWER,
                    integrity_state=AssetIntegrityState.VERIFIED,
                    derivation_metadata={},
                    source_metadata={
                        "source_root_key": self.root_key,
                        "source_key": source_key,
                    },
                )
                session.add(asset)
                session.flush()
            elif not self._asset_matches(
                asset,
                raw_entry=raw_entry,
                extracted=extracted,
                storage_key=storage_key,
                root_key=self.root_key,
                source_key=source_key,
            ):
                raise CatalogImportError(f"existing Asset differs for {source_key}")
            source = PaperSource(
                asset_id=asset.id,
                source_root_key=self.root_key,
                source_key=source_key,
                sha256=extracted.sha256,
                byte_size=extracted.byte_size,
                page_count=extracted.page_count,
                integrity_state=PaperSourceIntegrityState.VERIFIED,
            )
            session.add(source)
            session.flush()
            order = int(raw_entry["manifest_order"])
            paper = Paper(
                paper_key=self._paper_key(order),
                source_id=source.id,
                title=extracted.title,
                journal=extracted.journal,
                publication_year=extracted.publication_year,
                volume=extracted.volume,
                issue=extracted.issue,
                doi=extracted.doi,
                catalog_state=PaperCatalogState.EXTRACTED,
            )
            session.add(paper)
            created += 1
        return CatalogImportResult(len(verified), created, unchanged)
