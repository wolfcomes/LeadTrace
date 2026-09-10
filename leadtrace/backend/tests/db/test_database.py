from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import String, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.orm import Mapped, mapped_column

from app.config import Settings
from app.database import (
    bootstrap_database,
    check_database_connection,
    create_database_engine,
    create_session_factory,
    get_db_session,
    transactional_session,
)
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.main import create_app


BACKEND_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG_PATH = BACKEND_ROOT / "alembic.ini"


class DatabaseTestRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "database_test_records"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_CONFIG_PATH))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="module")
def migrated_database_url(postgresql_database_url: str) -> str:
    command.upgrade(_alembic_config(postgresql_database_url), "head")
    engine = create_database_engine(postgresql_database_url)
    DatabaseTestRecord.__table__.create(engine, checkfirst=True)
    engine.dispose()
    yield postgresql_database_url
    cleanup_engine = create_database_engine(postgresql_database_url)
    DatabaseTestRecord.__table__.drop(cleanup_engine, checkfirst=True)
    cleanup_engine.dispose()


def test_database_engine_rejects_non_postgresql_urls() -> None:
    with pytest.raises(ValueError, match="PostgreSQL"):
        create_database_engine("sqlite+pysqlite:///:memory:")


def test_database_connection_health_uses_postgresql(
    migrated_database_url: str,
) -> None:
    engine = create_database_engine(migrated_database_url)

    try:
        assert engine.dialect.name == "postgresql"
        assert check_database_connection(engine) is True
    finally:
        engine.dispose()


def test_pool_has_a_hard_connection_limit(migrated_database_url: str) -> None:
    engine = create_database_engine(
        migrated_database_url,
        pool_size=1,
        max_overflow=0,
        pool_timeout_seconds=0.05,
    )

    try:
        with engine.connect():
            with pytest.raises(PoolTimeoutError):
                engine.connect()
    finally:
        engine.dispose()


def test_transaction_context_commits_uuid_jsonb_and_utc_timestamp(
    migrated_database_url: str,
) -> None:
    engine = create_database_engine(migrated_database_url)
    session_factory = create_session_factory(engine)

    try:
        with transactional_session(session_factory) as session:
            record = DatabaseTestRecord(
                name="committed",
                payload={"source": "integration", "ordinal": 1},
            )
            session.add(record)
            session.flush()
            record_id = record.id

        with session_factory() as session:
            persisted = session.get(DatabaseTestRecord, record_id)

        assert persisted is not None
        assert isinstance(persisted.id, UUID)
        assert persisted.payload == {"source": "integration", "ordinal": 1}
        assert persisted.created_at.tzinfo is not None
        assert persisted.created_at.utcoffset() == timedelta(0)
    finally:
        with transactional_session(session_factory) as session:
            session.query(DatabaseTestRecord).delete()
        engine.dispose()


def test_transaction_context_rolls_back_the_whole_unit_of_work(
    migrated_database_url: str,
) -> None:
    engine = create_database_engine(migrated_database_url)
    session_factory = create_session_factory(engine)

    try:
        with pytest.raises(RuntimeError, match="abort transaction"):
            with transactional_session(session_factory) as session:
                session.add(
                    DatabaseTestRecord(name="rolled-back", payload={"saved": False})
                )
                session.flush()
                raise RuntimeError("abort transaction")

        with session_factory() as session:
            count = session.scalar(
                select(func.count())
                .select_from(DatabaseTestRecord)
                .where(DatabaseTestRecord.name == "rolled-back")
            )

        assert count == 0
    finally:
        engine.dispose()


def test_request_scoped_session_never_commits_implicitly(
    migrated_database_url: str,
) -> None:
    engine = create_database_engine(migrated_database_url)
    session_factory = create_session_factory(engine)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(session_factory=session_factory))
    )
    dependency = get_db_session(request)

    try:
        request_session = next(dependency)
        request_session.add(
            DatabaseTestRecord(name="request-draft", payload={"saved": False})
        )
        request_session.flush()
        dependency.close()

        with session_factory() as verification_session:
            count = verification_session.scalar(
                select(func.count())
                .select_from(DatabaseTestRecord)
                .where(DatabaseTestRecord.name == "request-draft")
            )

        assert count == 0
        assert not request_session.is_active or request_session.in_transaction() is False
    finally:
        dependency.close()
        engine.dispose()


def test_bootstrap_validates_schema_and_builds_session_factory(
    tmp_path: Path,
    migrated_database_url: str,
) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=migrated_database_url,
        redis_url="redis://127.0.0.1:6379/0",
        session_secret="test-only-session-secret-at-least-32-characters",
        allowed_hosts=["testserver"],
        asset_root=tmp_path,
    )

    resources = bootstrap_database(settings, alembic_config_path=ALEMBIC_CONFIG_PATH)

    try:
        with resources.session_factory() as session:
            assert session.scalar(select(1)) == 1
    finally:
        resources.close()


def test_application_lifespan_bootstraps_and_closes_database_resources(
    tmp_path: Path,
    migrated_database_url: str,
) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=migrated_database_url,
        redis_url="redis://127.0.0.1:6379/0",
        session_secret="test-only-session-secret-at-least-32-characters",
        allowed_hosts=["testserver"],
        asset_root=tmp_path,
    )
    session_factory = object()
    closed: list[bool] = []
    resources = SimpleNamespace(
        engine=object(),
        session_factory=session_factory,
        close=lambda: closed.append(True),
    )
    bootstrapped_with: list[Settings] = []

    def fake_bootstrap(runtime_settings: Settings) -> object:
        bootstrapped_with.append(runtime_settings)
        return resources

    application = create_app(
        settings=settings,
        database_probe=lambda _: True,
        database_bootstrap=fake_bootstrap,
    )

    with TestClient(application) as client:
        assert client.get("/health/live").status_code == 200
        assert application.state.session_factory is session_factory

    assert bootstrapped_with == [settings]
    assert closed == [True]
