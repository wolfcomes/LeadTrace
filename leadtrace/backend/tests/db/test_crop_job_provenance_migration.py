from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.engine import Engine, make_url

from app.assets.models import (
    Asset,
    AssetAccessLevel,
    AssetCategory,
    AssetIntegrityState,
)
from app.database import create_database_engine, create_session_factory
from app.jobs.models import CropJob, CropJobStatus


BACKEND_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG_PATH = BACKEND_ROOT / "alembic.ini"
OLD_REVISION = "0021_structure_source_image_occurrence_unique"
NEW_REVISION = "0022_crop_job_source_provenance"
OLD_CONSTRAINT = "uq_crop_jobs_input_hash"
NEW_CONSTRAINT = "uq_crop_jobs_input_source_asset"


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_CONFIG_PATH))
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["leadtrace_database_url"] = database_url
    config.attributes["leadtrace_expected_database_name"] = make_url(
        database_url
    ).database
    return config


def _constraints(engine: Engine) -> dict[str, dict[str, object]]:
    return {
        str(constraint["name"]): constraint
        for constraint in inspect(engine).get_unique_constraints("crop_jobs")
    }


def _source_asset(storage_key: str) -> Asset:
    return Asset(
        storage_key=storage_key,
        original_filename=Path(storage_key).name,
        sha256="a" * 64,
        byte_size=100,
        mime_type="application/pdf",
        category=AssetCategory.ARTICLE_PDF,
        access_level=AssetAccessLevel.REVIEWER,
        integrity_state=AssetIntegrityState.VERIFIED,
        derivation_metadata={},
        source_metadata={},
    )


def _crop_job(source_asset_id, *, asset_id=None) -> CropJob:
    return CropJob(
        input_hash="b" * 64,
        source_pdf_sha256="a" * 64,
        source_asset_id=source_asset_id,
        page_number=1,
        x0=0.1,
        y0=0.1,
        x1=0.4,
        y1=0.4,
        rotation=0,
        padding=0,
        dpi=144,
        renderer_version="test-renderer",
        status=CropJobStatus.PENDING,
        asset_id=asset_id,
    )


def test_applied_0021_database_upgrades_crop_job_provenance_constraint(
    empty_postgresql_database_url: str,
) -> None:
    config = _alembic_config(empty_postgresql_database_url)
    command.upgrade(config, OLD_REVISION)
    engine = create_database_engine(empty_postgresql_database_url)
    factory = create_session_factory(engine)
    try:
        before = _constraints(engine)
        assert OLD_CONSTRAINT in before
        assert NEW_CONSTRAINT not in before
        with factory.begin() as session:
            source_asset = _source_asset("source/source_pdfs/legacy.pdf")
            crop_asset = Asset(
                storage_key="managed/objects/aa/legacy.png",
                original_filename="legacy.png",
                sha256="c" * 64,
                byte_size=50,
                mime_type="image/png",
                category=AssetCategory.EVIDENCE_CROP,
                access_level=AssetAccessLevel.REVIEWER,
                integrity_state=AssetIntegrityState.VERIFIED,
                source_asset_id=None,
                derivation_metadata={},
                source_metadata={},
            )
            session.add_all([source_asset, crop_asset])
            session.flush()
            crop_asset.source_asset_id = source_asset.id
            legacy_job = _crop_job(None, asset_id=crop_asset.id)
            legacy_job.status = CropJobStatus.COMPLETED
            session.add(legacy_job)
            session.flush()
            source_asset_id = source_asset.id
            legacy_job_id = legacy_job.id
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_database_engine(empty_postgresql_database_url)
    try:
        after = _constraints(engine)
        assert OLD_CONSTRAINT not in after
        assert after[NEW_CONSTRAINT]["column_names"] == [
            "input_hash",
            "source_asset_id",
        ]
        assert after[NEW_CONSTRAINT]["dialect_options"][
            "postgresql_nulls_not_distinct"
        ] is True
        factory = create_session_factory(engine)
        with factory() as session:
            legacy_job = session.get(CropJob, legacy_job_id)
            assert legacy_job is not None
            assert legacy_job.source_asset_id == source_asset_id
        with engine.connect() as connection:
            revision = MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()

    assert revision == NEW_REVISION

    command.downgrade(config, OLD_REVISION)
    engine = create_database_engine(empty_postgresql_database_url)
    try:
        downgraded = _constraints(engine)
        assert OLD_CONSTRAINT in downgraded
        assert NEW_CONSTRAINT not in downgraded
    finally:
        engine.dispose()


def test_crop_job_provenance_downgrade_rejects_duplicate_input_hashes(
    empty_postgresql_database_url: str,
) -> None:
    config = _alembic_config(empty_postgresql_database_url)
    command.upgrade(config, "head")
    engine = create_database_engine(empty_postgresql_database_url)
    factory = create_session_factory(engine)
    try:
        with factory.begin() as session:
            first_source = _source_asset("source/source_pdfs/first.pdf")
            second_source = _source_asset("source/source_pdfs/second.pdf")
            session.add_all([first_source, second_source])
            session.flush()
            session.add_all(
                [_crop_job(first_source.id), _crop_job(second_source.id)]
            )
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="source-specific duplicate"):
        command.downgrade(config, OLD_REVISION)

    engine = create_database_engine(empty_postgresql_database_url)
    try:
        with engine.connect() as connection:
            revision = MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()
    assert revision == NEW_REVISION
