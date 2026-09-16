from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

from alembic import command
from alembic.config import Config
import fitz
import pytest
from sqlalchemy import func, select

from app.assets.models import Asset
from app.assets.storage import LocalAssetStore
from app.catalog.extraction import (
    CatalogCollection,
    CatalogExtractionError,
    extract_catalog_metadata,
)
from app.catalog.models import PaperSource
from app.catalog.service import CatalogImportError, CatalogImportService
from app.database import create_database_engine, create_session_factory
from app.papers.models import Paper
from leadtrace.ops.pilot.build_manifest import build_manifest


COLLECTION = CatalogCollection(
    journal="Journal of Medicinal Chemistry",
    publication_year=2024,
    volume="67",
    issue="5",
)


def _write_pdf(
    path: Path,
    *,
    title: str | None = None,
    text: str = "",
    pages: int = 1,
) -> None:
    document = fitz.open()
    for page_index in range(pages):
        page = document.new_page()
        page.insert_text((72, 72), text if page_index == 0 else f"Page {page_index + 1}")
    if title is not None:
        document.set_metadata({"title": title})
    document.save(path)
    document.close()


def _alembic_config(database_url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["leadtrace_database_url"] = database_url
    config.attributes["leadtrace_expected_database_name"] = database_url.rsplit("/", 1)[-1]
    return config


def _pilot_fixture(tmp_path: Path) -> tuple[Path, Path]:
    source_root = tmp_path / "source_pdfs"
    source_directory = source_root / "volume67 issue5"
    source_directory.mkdir(parents=True)
    for index in range(20):
        _write_pdf(
            source_directory / f"paper-{index:02d}.pdf",
            title=f"Pilot paper {index + 1}",
            text=(
                f"Pilot paper {index + 1}\n"
                "Journal of Medicinal Chemistry\n"
                "2024, Volume 67, Issue 5\n"
                f"DOI: 10.1021/acs.jmedchem.4c{index:04d}"
            ),
            pages=(index % 2) + 1,
        )
    manifest_path = tmp_path / "manifest.json"
    build_manifest(
        source_root,
        manifest_path,
        source_directory="volume67 issue5",
        source_root_key="source_pdfs",
        collection={
            "journal": COLLECTION.journal,
            "publication_year": COLLECTION.publication_year,
            "volume": COLLECTION.volume,
            "issue": COLLECTION.issue,
        },
        created_on="2026-09-15",
    )
    return source_root, manifest_path


def test_catalog_extraction_prefers_metadata_and_extracts_strict_doi(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "article.pdf"
    _write_pdf(
        pdf,
        title="  Metadata title  ",
        text=(
            "First-page fallback title\n"
            "Journal of Medicinal Chemistry\n"
            "2024, Volume 67, Issue 5\n"
            "https://doi.org/10.1021/acs.jmedchem.4c01234."
        ),
        pages=2,
    )

    extracted = extract_catalog_metadata(pdf, COLLECTION)

    assert extracted.title == "Metadata title"
    assert extracted.doi == "10.1021/acs.jmedchem.4c01234"
    assert extracted.page_count == 2
    assert extracted.byte_size == pdf.stat().st_size
    assert len(extracted.sha256) == 64
    assert not hasattr(extracted, "path")


def test_catalog_extraction_uses_first_page_then_filename_for_title(
    tmp_path: Path,
) -> None:
    first_page = tmp_path / "first-page.pdf"
    filename = tmp_path / "filename-fallback-title.pdf"
    _write_pdf(first_page, text="First page title\nSupporting details")
    _write_pdf(filename, text="")

    assert extract_catalog_metadata(first_page, COLLECTION).title == "First page title"
    assert (
        extract_catalog_metadata(filename, COLLECTION).title
        == "Filename fallback title"
    )


def test_catalog_extraction_ignores_non_strict_doi(tmp_path: Path) -> None:
    pdf = tmp_path / "article.pdf"
    _write_pdf(pdf, title="No DOI paper", text="DOI: 10.12/not-valid")

    assert extract_catalog_metadata(pdf, COLLECTION).doi is None


@pytest.mark.parametrize(
    ("collection", "text", "field"),
    [
        (replace(COLLECTION, journal="Expected Journal"), "Journal: Other Journal", "journal"),
        (COLLECTION, "Publication Year: 2025", "publication_year"),
        (COLLECTION, "Volume: 68", "volume"),
        (COLLECTION, "Issue: 6", "issue"),
    ],
)
def test_catalog_extraction_rejects_unambiguous_collection_contradictions(
    tmp_path: Path,
    collection: CatalogCollection,
    text: str,
    field: str,
) -> None:
    pdf = tmp_path / "article.pdf"
    _write_pdf(pdf, title="Contradictory paper", text=text)

    with pytest.raises(CatalogExtractionError, match=field):
        extract_catalog_metadata(pdf, collection)


def test_catalog_import_is_transactional_safe_and_exactly_idempotent(
    empty_postgresql_database_url: str,
    tmp_path: Path,
) -> None:
    command.upgrade(_alembic_config(empty_postgresql_database_url), "head")
    source_root, manifest_path = _pilot_fixture(tmp_path)
    store = LocalAssetStore(
        tmp_path / "managed",
        source_roots={"source_pdfs": source_root},
    )
    service = CatalogImportService(manifest_path, store)
    engine = create_database_engine(empty_postgresql_database_url)
    session_factory = create_session_factory(engine)
    try:
        with session_factory.begin() as session:
            result = service.apply(session)
        assert result.verified_count == 20
        assert result.created_count == 20
        assert result.unchanged_count == 0

        with session_factory() as session:
            assert session.scalar(select(func.count()).select_from(Asset)) == 20
            assert session.scalar(select(func.count()).select_from(PaperSource)) == 20
            assert session.scalar(select(func.count()).select_from(Paper)) == 20
            papers = session.scalars(select(Paper).order_by(Paper.paper_key)).all()
            sources = session.scalars(select(PaperSource).order_by(PaperSource.source_key)).all()
            assets = session.scalars(select(Asset).order_by(Asset.storage_key)).all()
            assert [paper.paper_key for paper in papers] == [
                f"LT-JMC-2024-67-05-{index:03d}" for index in range(1, 21)
            ]
            serialized = json.dumps(
                [
                    {
                        "storage_key": asset.storage_key,
                        "source_metadata": asset.source_metadata,
                    }
                    for asset in assets
                ]
                + [
                    {
                        "source_root_key": source.source_root_key,
                        "source_key": source.source_key,
                    }
                    for source in sources
                ],
                sort_keys=True,
            )
            assert str(source_root) not in serialized
            assert all(
                asset.storage_key.startswith("source/source_pdfs/volume67 issue5/")
                for asset in assets
            )

        with session_factory.begin() as session:
            replay = service.apply(session)
        assert replay.verified_count == 20
        assert replay.created_count == 0
        assert replay.unchanged_count == 20
    finally:
        engine.dispose()


def test_catalog_import_verifies_all_hashes_before_writing(
    empty_postgresql_database_url: str,
    tmp_path: Path,
) -> None:
    command.upgrade(_alembic_config(empty_postgresql_database_url), "head")
    source_root, manifest_path = _pilot_fixture(tmp_path)
    changed = source_root / "volume67 issue5" / "paper-19.pdf"
    _write_pdf(changed, title="Changed after manifest", text="different bytes")
    service = CatalogImportService(
        manifest_path,
        LocalAssetStore(
            tmp_path / "managed",
            source_roots={"source_pdfs": source_root},
        ),
    )
    engine = create_database_engine(empty_postgresql_database_url)
    session_factory = create_session_factory(engine)
    try:
        with pytest.raises(CatalogImportError, match="SHA-256"):
            with session_factory.begin() as session:
                service.apply(session)
        with session_factory() as session:
            assert session.scalar(select(func.count()).select_from(Asset)) == 0
            assert session.scalar(select(func.count()).select_from(PaperSource)) == 0
            assert session.scalar(select(func.count()).select_from(Paper)) == 0
    finally:
        engine.dispose()
