from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

from alembic import command
from alembic.config import Config
import fitz
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import make_url

from app.assets.models import (
    Asset,
    AssetAccessLevel,
    AssetCategory,
    AssetIntegrityState,
)
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
    config.attributes["leadtrace_expected_database_name"] = make_url(database_url).database
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


def _unreferenced_asset() -> Asset:
    return Asset(
        storage_key="unreferenced/review-note.txt",
        original_filename="review-note.txt",
        sha256="f" * 64,
        byte_size=1,
        mime_type="text/plain",
        category=AssetCategory.QUARANTINE,
        access_level=AssetAccessLevel.ADMIN,
        integrity_state=AssetIntegrityState.REGISTERED,
        derivation_metadata={},
        source_metadata={},
    )


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
    ("text", "metadata_subject", "field"),
    [
        ("Cite This: J. Med. Chem. 2025, 67, 100-120", None, "publication_year"),
        ("Cite This: J. Med. Chem. 2024, 68, 100-120", None, "volume"),
        ("", "J. Med. Chem. 2025.67:100-120", "publication_year"),
        ("", "J. Med. Chem. 2024.68:100-120", "volume"),
    ],
)
def test_catalog_extraction_rejects_acs_collection_contradictions(
    tmp_path: Path,
    text: str,
    metadata_subject: str | None,
    field: str,
) -> None:
    pdf = tmp_path / "article.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text or "Paper title")
    metadata = {"title": "ACS paper"}
    if metadata_subject is not None:
        metadata["subject"] = metadata_subject
    document.set_metadata(metadata)
    document.save(pdf)
    document.close()

    with pytest.raises(CatalogExtractionError, match=field):
        extract_catalog_metadata(pdf, COLLECTION)


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
            session.add(_unreferenced_asset())

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


def test_catalog_import_errors_never_expose_the_physical_source_root(
    tmp_path: Path,
) -> None:
    source_root, manifest_path = _pilot_fixture(tmp_path)
    missing = source_root / "volume67 issue5" / "paper-19.pdf"
    missing.unlink()
    service = CatalogImportService(
        manifest_path,
        LocalAssetStore(
            tmp_path / "managed",
            source_roots={"source_pdfs": source_root},
        ),
    )

    with pytest.raises(CatalogImportError) as error:
        service.preview()

    assert str(source_root) not in str(error.value)
    assert "volume67 issue5/paper-19.pdf" in str(error.value)


@pytest.mark.parametrize(
    "mutation",
    [
        "partial_catalog",
        "asset_storage_key",
        "asset_source_asset_id",
        "asset_width",
        "asset_height",
        "source_page_count",
        "paper_title",
    ],
)
def test_catalog_import_rejects_nonexact_existing_catalogs(
    empty_postgresql_database_url: str,
    tmp_path: Path,
    mutation: str,
) -> None:
    command.upgrade(_alembic_config(empty_postgresql_database_url), "head")
    source_root, manifest_path = _pilot_fixture(tmp_path)
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
        with session_factory.begin() as session:
            service.apply(session)
        with session_factory.begin() as session:
            if mutation == "partial_catalog":
                papers = session.scalars(select(Paper).order_by(Paper.paper_key)).all()
                paper_ids = [paper.id for paper in papers[1:]]
                source_ids = [paper.source_id for paper in papers[1:]]
                sources = session.scalars(
                    select(PaperSource).where(PaperSource.id.in_(source_ids))
                ).all()
                asset_ids = [source.asset_id for source in sources]
                session.execute(delete(Paper).where(Paper.id.in_(paper_ids)))
                session.execute(delete(PaperSource).where(PaperSource.id.in_(source_ids)))
                session.execute(delete(Asset).where(Asset.id.in_(asset_ids)))
            elif mutation == "asset_storage_key":
                asset = session.scalars(select(Asset).order_by(Asset.storage_key)).first()
                asset.storage_key = "source/source_pdfs/other.pdf"
            elif mutation == "asset_source_asset_id":
                unrelated = _unreferenced_asset()
                session.add(unrelated)
                session.flush()
                asset = session.scalars(
                    select(Asset)
                    .where(Asset.id != unrelated.id)
                    .order_by(Asset.storage_key)
                ).first()
                asset.source_asset_id = unrelated.id
            elif mutation == "asset_width":
                asset = session.scalars(select(Asset).order_by(Asset.storage_key)).first()
                asset.width = 100
            elif mutation == "asset_height":
                asset = session.scalars(select(Asset).order_by(Asset.storage_key)).first()
                asset.height = 100
            elif mutation == "source_page_count":
                source = session.scalars(select(PaperSource)).first()
                source.page_count += 1
            else:
                paper = session.scalars(select(Paper)).first()
                paper.title = "Changed title"

        with pytest.raises(CatalogImportError, match="exact replay"):
            with session_factory.begin() as session:
                service.apply(session)
        with session_factory() as session:
            expected = 1 if mutation == "partial_catalog" else 20
            assert session.scalar(select(func.count()).select_from(Paper)) == expected
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "manifest_mutation",
    ["outside_directory", "nested_pdf", "bad_order", "duplicate_order"],
)
def test_catalog_import_rejects_invalid_manifest_structure_before_writes(
    empty_postgresql_database_url: str,
    tmp_path: Path,
    manifest_mutation: str,
) -> None:
    command.upgrade(_alembic_config(empty_postgresql_database_url), "head")
    source_root, manifest_path = _pilot_fixture(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = payload["entries"][0]
    if manifest_mutation in {"outside_directory", "nested_pdf"}:
        replacement = (
            "other/article.pdf"
            if manifest_mutation == "outside_directory"
            else "volume67 issue5/nested/article.pdf"
        )
        source = source_root / entry["source_key"]
        target = source_root / replacement
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        entry["source_key"] = replacement
        entry["original_filename"] = "article.pdf"
    elif manifest_mutation == "bad_order":
        entry["manifest_order"] = 0
    else:
        payload["entries"][1]["manifest_order"] = 1
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    store = LocalAssetStore(
        tmp_path / "managed",
        source_roots={"source_pdfs": source_root},
    )
    with pytest.raises(CatalogImportError):
        CatalogImportService(manifest_path, store)


@pytest.mark.parametrize(
    ("manifest_path_parts", "invalid_value"),
    [
        (("schema_version",), True),
        (("entries", 0, "manifest_order"), True),
        (("collection", "publication_year"), True),
    ],
)
def test_catalog_import_requires_strict_manifest_integer_types(
    tmp_path: Path,
    manifest_path_parts: tuple[str | int, ...],
    invalid_value: object,
) -> None:
    source_root, manifest_path = _pilot_fixture(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    target = payload
    for part in manifest_path_parts[:-1]:
        target = target[part]
    target[manifest_path_parts[-1]] = invalid_value
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CatalogImportError):
        CatalogImportService(
            manifest_path,
            LocalAssetStore(
                tmp_path / "managed",
                source_roots={"source_pdfs": source_root},
            ),
        )


@pytest.mark.parametrize(
    ("created_on_present", "created_on"),
    [
        (False, None),
        (True, "not-a-date"),
    ],
)
def test_catalog_import_requires_an_iso_created_on_date(
    tmp_path: Path,
    created_on_present: bool,
    created_on: str | None,
) -> None:
    source_root, manifest_path = _pilot_fixture(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if created_on_present:
        payload["created_on"] = created_on
    else:
        del payload["created_on"]
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CatalogImportError):
        CatalogImportService(
            manifest_path,
            LocalAssetStore(
                tmp_path / "managed",
                source_roots={"source_pdfs": source_root},
            ),
        )


@pytest.mark.parametrize("collection_field", ["journal", "volume", "issue"])
def test_catalog_import_rejects_whitespace_only_required_strings(
    tmp_path: Path,
    collection_field: str,
) -> None:
    source_root, manifest_path = _pilot_fixture(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["collection"][collection_field] = " \t "
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CatalogImportError):
        CatalogImportService(
            manifest_path,
            LocalAssetStore(
                tmp_path / "managed",
                source_roots={"source_pdfs": source_root},
            ),
        )


def test_catalog_import_rolls_back_when_a_late_insert_fails(
    empty_postgresql_database_url: str,
    tmp_path: Path,
) -> None:
    command.upgrade(_alembic_config(empty_postgresql_database_url), "head")
    source_root, manifest_path = _pilot_fixture(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    final_entry = payload["entries"][19]
    final_pdf = source_root / final_entry["source_key"]
    _write_pdf(
        final_pdf,
        title="Conflicting DOI paper",
        text=(
            "Conflicting DOI paper\n"
            "Journal of Medicinal Chemistry\n"
            "2024, Volume 67, Issue 5\n"
            "DOI: 10.1021/acs.jmedchem.4c0000"
        ),
    )
    extracted = extract_catalog_metadata(final_pdf, COLLECTION)
    final_entry["sha256"] = extracted.sha256
    final_entry["byte_size"] = extracted.byte_size
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
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
        with pytest.raises(IntegrityError) as error:
            with session_factory.begin() as session:
                service.apply(session)
        assert "INSERT INTO papers" in str(error.value.statement)
        assert error.value.orig.sqlstate == "23505"
        assert error.value.orig.diag.constraint_name == "uq_papers_doi"
        with session_factory() as session:
            assert session.scalar(select(func.count()).select_from(Asset)) == 0
            assert session.scalar(select(func.count()).select_from(PaperSource)) == 0
            assert session.scalar(select(func.count()).select_from(Paper)) == 0
    finally:
        engine.dispose()
