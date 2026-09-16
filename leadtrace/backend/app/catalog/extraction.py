from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re

import pymupdf


class CatalogExtractionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CatalogCollection:
    journal: str
    publication_year: int
    volume: str
    issue: str


@dataclass(frozen=True, slots=True)
class ExtractedCatalogMetadata:
    title: str
    journal: str
    publication_year: int
    volume: str
    issue: str
    doi: str | None
    sha256: str
    byte_size: int
    page_count: int


_DOI = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)
_YEAR = re.compile(r"\bpublication\s+year\s*[:=-]?\s*(20\d{2})\b", re.IGNORECASE)
_VOLUME = re.compile(r"\bvolume\s*[:=-]?\s*([0-9A-Za-z.-]+)", re.IGNORECASE)
_ISSUE = re.compile(r"\bissue\s*[:=-]?\s*([0-9A-Za-z.-]+)", re.IGNORECASE)
_JOURNAL = re.compile(r"^journal\s*[:=-]\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_ACS_CITATION = re.compile(
    r"(?:cite\s+this:\s*)?J\.\s*Med\.\s*Chem\.\s*(20\d{2})\s*,\s*(\d+)",
    re.IGNORECASE,
)
_ACS_SUBJECT = re.compile(
    r"J\.\s*Med\.\s*Chem\.\s*(20\d{2})\.(\d+)\s*:",
    re.IGNORECASE,
)


def _clean_doi(value: str) -> str:
    return value.rstrip(".,;:)")


def _first_usable_line(text: str) -> str | None:
    for line in text.splitlines():
        value = " ".join(line.split()).strip()
        if value and not value.lower().startswith(("journal", "doi", "volume", "issue")):
            return value
    return None


def _contradiction(
    text: str,
    collection: CatalogCollection,
    *,
    metadata_subject: str = "",
) -> str | None:
    match = _JOURNAL.search(text)
    if match and match.group(1).strip() != collection.journal:
        return "journal"
    year_match = _YEAR.search(text)
    if year_match and int(year_match.group(1)) != collection.publication_year:
        return "publication_year"
    volume_match = _VOLUME.search(text)
    if volume_match and volume_match.group(1) != collection.volume:
        return "volume"
    issue_match = _ISSUE.search(text)
    if issue_match and issue_match.group(1) != collection.issue:
        return "issue"
    for value, pattern in ((text, _ACS_CITATION), (metadata_subject, _ACS_SUBJECT)):
        acs_match = pattern.search(value)
        if not acs_match:
            continue
        if int(acs_match.group(1)) != collection.publication_year:
            return "publication_year"
        if acs_match.group(2) != collection.volume:
            return "volume"
    return None


def extract_catalog_metadata(path: Path, collection: CatalogCollection) -> ExtractedCatalogMetadata:
    path = Path(path).resolve(strict=True)
    raw = path.read_bytes()
    try:
        document = pymupdf.open(stream=raw, filetype="pdf")
    except Exception as error:
        raise CatalogExtractionError(f"invalid PDF: {path.name}") from error
    try:
        page_count = document.page_count
        first_page = document[0].get_text() if page_count else ""
        metadata_title = (document.metadata.get("title") or "").strip()
        metadata_subject = (document.metadata.get("subject") or "").strip()
    finally:
        document.close()
    contradiction = _contradiction(
        first_page,
        collection,
        metadata_subject=metadata_subject,
    )
    if contradiction:
        raise CatalogExtractionError(f"{contradiction} contradicts controlled collection")
    title = metadata_title or _first_usable_line(first_page)
    if not title:
        fallback = path.stem.replace("_", " ").replace("-", " ").strip()
        title = fallback[:1].upper() + fallback[1:]
    doi_match = _DOI.search(first_page)
    return ExtractedCatalogMetadata(
        title=title,
        journal=collection.journal,
        publication_year=collection.publication_year,
        volume=collection.volume,
        issue=collection.issue,
        doi=_clean_doi(doi_match.group(0)) if doi_match else None,
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_size=len(raw),
        page_count=page_count,
    )
