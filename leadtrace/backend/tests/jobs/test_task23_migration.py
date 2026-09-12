from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from alembic import command
from alembic.config import Config
from sqlalchemy import Enum, MetaData, Table, cast, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.database import create_database_engine, create_session_factory
from app.jobs.models import CropJob, CropJobStatus


class LegacyCropJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


def _alembic_config(database_url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["leadtrace_database_url"] = database_url
    config.attributes["leadtrace_expected_database_name"] = make_url(
        database_url
    ).database
    return config


def _crop_job(input_hash: str) -> CropJob:
    return CropJob(
        input_hash=input_hash,
        source_pdf_sha256="b" * 64,
        page_number=1,
        x0=0.1,
        y0=0.1,
        x1=0.9,
        y1=0.9,
        rotation=0,
        padding=0,
        dpi=200,
        renderer_version="task-23-migration-test",
        status=CropJobStatus.PENDING,
    )


def _legacy_status(session: Session, job_id: UUID) -> LegacyCropJobStatus:
    crop_jobs = Table("crop_jobs", MetaData(), autoload_with=session.bind)
    legacy_enum = Enum(
        LegacyCropJobStatus,
        name="crop_job_status",
        native_enum=False,
        length=16,
        values_callable=lambda values: [value.value for value in values],
    )
    return session.scalar(
        select(cast(crop_jobs.c.status, legacy_enum)).where(crop_jobs.c.id == job_id)
    )


def test_job_recovery_migration_maps_superseded_jobs_before_downgrade(
    empty_postgresql_database_url: str,
) -> None:
    config = _alembic_config(empty_postgresql_database_url)
    command.upgrade(config, "head")
    engine = create_database_engine(empty_postgresql_database_url)
    factory = create_session_factory(engine)
    try:
        with factory.begin() as session:
            replacement = _crop_job("c" * 64)
            session.add(replacement)
            session.flush()
            superseded = _crop_job("d" * 64)
            superseded.status = CropJobStatus.SUPERSEDED
            superseded.superseded_by_id = replacement.id
            superseded.error_message = "Superseded by corrected crop bounds"
            session.add(superseded)
            session.flush()
            superseded_id = superseded.id
    finally:
        engine.dispose()

    command.downgrade(config, "0013_approvals")

    engine = create_database_engine(empty_postgresql_database_url)
    factory = create_session_factory(engine)
    try:
        with factory.begin() as session:
            assert _legacy_status(session, superseded_id) is LegacyCropJobStatus.FAILED
            crop_jobs = Table("crop_jobs", MetaData(), autoload_with=session.bind)
            error_message = session.scalar(
                select(crop_jobs.c.error_message).where(crop_jobs.c.id == superseded_id)
            )
            assert error_message == (
                "Superseded by corrected crop bounds; "
                "mapped to failed during Task 23 rollback"
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_database_engine(empty_postgresql_database_url)
    factory = create_session_factory(engine)
    try:
        with factory.begin() as session:
            recovered = session.get(CropJob, superseded_id)
            assert recovered is not None
            assert recovered.status is CropJobStatus.FAILED
    finally:
        engine.dispose()
