from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assets.models import Asset, AssetAccessLevel, AssetCategory, AssetIntegrityState
from app.assets.storage import LocalAssetStore
from app.catalog.extraction import CatalogCollection, ExtractedCatalogMetadata, extract_catalog_metadata
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
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if self.manifest.get("schema_version") != 1:
            raise CatalogImportError("unsupported manifest schema")
        self.entries = self.manifest.get("entries")
        if not isinstance(self.entries, list) or len(self.entries) != 20:
            raise CatalogImportError("manifest must contain exactly 20 entries")
        collection = self.manifest.get("collection")
        if not isinstance(collection, dict):
            raise CatalogImportError("manifest collection is required")
        self.collection = CatalogCollection(
            journal=str(collection["journal"]),
            publication_year=int(collection["publication_year"]),
            volume=str(collection["volume"]),
            issue=str(collection["issue"]),
        )

    def _preflight(self) -> list[tuple[dict[str, Any], ExtractedCatalogMetadata, str]]:
        root_key = str(self.manifest["source_root_key"])
        verified: list[tuple[dict[str, Any], ExtractedCatalogMetadata, str]] = []
        seen_hashes: set[str] = set()
        for raw_entry in self.entries:
            if not isinstance(raw_entry, dict):
                raise CatalogImportError("manifest entry must be an object")
            source_key = str(raw_entry["source_key"])
            storage_key = self.asset_store.source_storage_key(root_key, source_key)
            extracted = extract_catalog_metadata(self.asset_store.path_for(storage_key), self.collection)
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

    def apply(self, session: Session) -> CatalogImportResult:
        verified = self._preflight()
        existing_papers = session.scalar(select(Paper.id).limit(1))
        existing_sources = session.scalar(select(PaperSource.id).limit(1))
        existing_assets = session.scalar(select(Asset.id).limit(1))
        if any(value is not None for value in (existing_papers, existing_sources, existing_assets)):
            # Exact replays are allowed; any catalog row outside this manifest is not.
            source_rows = session.scalars(select(PaperSource)).all()
            expected_keys = {str(entry[0]["source_key"]) for entry in verified}
            if any(source.source_key not in expected_keys for source in source_rows):
                raise CatalogImportError("Paper catalog is nonempty and does not match this manifest")
        created = unchanged = 0
        journal_code = _journal_code(self.collection.journal)
        for raw_entry, extracted, storage_key in verified:
            source_key = str(raw_entry["source_key"])
            source = session.scalar(
                select(PaperSource).where(
                    PaperSource.source_root_key == self.manifest["source_root_key"],
                    PaperSource.source_key == source_key,
                )
            )
            if source is not None:
                paper = session.scalar(select(Paper).where(Paper.source_id == source.id))
                if paper is None or source.sha256 != extracted.sha256:
                    raise CatalogImportError(f"existing catalog row differs for {source_key}")
                unchanged += 1
                continue
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
                    "source_root_key": self.manifest["source_root_key"],
                    "source_key": source_key,
                },
            )
            session.add(asset)
            session.flush()
            source = PaperSource(
                asset_id=asset.id,
                source_root_key=str(self.manifest["source_root_key"]),
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
                paper_key=(
                    f"LT-{journal_code}-{self.collection.publication_year}-"
                    f"{self.collection.volume}-{self.collection.issue.zfill(2)}-{order:03d}"
                ),
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
