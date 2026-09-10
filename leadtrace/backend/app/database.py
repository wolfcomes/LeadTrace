from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import Request
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine, URL, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings


DEFAULT_ALEMBIC_CONFIG_PATH = Path(__file__).resolve().parents[1] / "alembic.ini"
SessionFactory = sessionmaker[Session]


class SchemaVersionError(RuntimeError):
    """Raised when a database has not been migrated to the application head."""


@dataclass(frozen=True, slots=True)
class DatabaseResources:
    engine: Engine
    session_factory: SessionFactory

    def close(self) -> None:
        self.engine.dispose()


def _postgresql_url(database_url: str) -> URL:
    parsed_url = make_url(database_url)
    if parsed_url.get_backend_name() != "postgresql":
        raise ValueError("LeadTrace database_url must use PostgreSQL")
    if parsed_url.drivername == "postgresql":
        parsed_url = parsed_url.set(drivername="postgresql+psycopg")
    if parsed_url.get_driver_name() != "psycopg":
        raise ValueError("LeadTrace PostgreSQL connections must use Psycopg 3")
    return parsed_url


def create_database_engine(
    database_url: str,
    *,
    pool_size: int = 5,
    max_overflow: int = 5,
    pool_timeout_seconds: float = 5.0,
    connect_timeout_seconds: int = 3,
) -> Engine:
    """Create a bounded PostgreSQL engine with UTC connections."""

    engine = create_engine(
        _postgresql_url(database_url),
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout_seconds,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={"connect_timeout": connect_timeout_seconds},
    )

    @event.listens_for(engine, "connect")
    def _set_connection_timezone(dbapi_connection: Any, _: Any) -> None:
        with dbapi_connection.cursor() as cursor:
            cursor.execute("SET TIME ZONE 'UTC'")

    return engine


def create_session_factory(engine: Engine) -> SessionFactory:
    return sessionmaker(
        bind=engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )


@contextmanager
def transactional_session(
    session_factory: SessionFactory,
) -> Iterator[Session]:
    """Run a unit of work atomically and always close its session."""

    with session_factory() as session:
        with session.begin():
            yield session


def get_db_session(request: Request) -> Generator[Session, None, None]:
    """Yield one non-committing session for a FastAPI request."""

    session_factory: SessionFactory = request.app.state.session_factory
    with session_factory() as session:
        try:
            yield session
        finally:
            if session.in_transaction():
                session.rollback()


def check_database_connection(engine: Engine) -> bool:
    try:
        with engine.connect() as connection:
            return connection.scalar(text("SELECT 1")) == 1
    except SQLAlchemyError:
        return False


def _alembic_config(config_path: Path) -> Config:
    if not config_path.is_file():
        raise SchemaVersionError(f"Alembic configuration not found: {config_path}")
    return Config(str(config_path))


def validate_schema_version(
    engine: Engine,
    alembic_config_path: Path = DEFAULT_ALEMBIC_CONFIG_PATH,
) -> None:
    """Require the connected schema to match the single Alembic head."""

    config = _alembic_config(alembic_config_path)
    script = ScriptDirectory.from_config(config)
    expected_revision = script.get_current_head()
    if expected_revision is None:
        raise SchemaVersionError("Alembic head is not defined")

    with engine.connect() as connection:
        actual_revision = MigrationContext.configure(connection).get_current_revision()

    if actual_revision != expected_revision:
        raise SchemaVersionError(
            "Database schema revision "
            f"{actual_revision or '<unversioned>'} does not match Alembic head "
            f"{expected_revision}"
        )


def bootstrap_database(
    settings: Settings,
    *,
    alembic_config_path: Path = DEFAULT_ALEMBIC_CONFIG_PATH,
) -> DatabaseResources:
    """Build database resources only after verifying the deployed schema."""

    engine = create_database_engine(
        settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout_seconds=settings.database_pool_timeout_seconds,
        connect_timeout_seconds=settings.database_connect_timeout_seconds,
    )
    try:
        validate_schema_version(engine, alembic_config_path)
    except Exception:
        engine.dispose()
        raise
    return DatabaseResources(
        engine=engine,
        session_factory=create_session_factory(engine),
    )

