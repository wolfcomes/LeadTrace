from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session, sessionmaker

from app.database import create_database_engine, create_session_factory


TEST_DATABASE_ENV = "LEADTRACE_TEST_DATABASE_URL"


def _required_postgresql_url() -> str:
    database_url = os.environ.get(TEST_DATABASE_ENV, "").strip()
    if not database_url:
        pytest.fail(
            f"{TEST_DATABASE_ENV} must point to an isolated PostgreSQL test database",
            pytrace=False,
        )
    if not database_url.startswith(
        ("postgresql://", "postgresql+psycopg://")
    ):
        pytest.fail(f"{TEST_DATABASE_ENV} must use PostgreSQL", pytrace=False)
    return database_url


def _psycopg_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def _reset_isolated_test_database(database_url: str) -> None:
    with psycopg.connect(_psycopg_url(database_url), autocommit=True) as connection:
        database_name = connection.info.dbname or ""
        if not database_name.endswith("_test"):
            pytest.fail(
                "Refusing to reset a database whose name does not end in '_test'",
                pytrace=False,
            )
        with connection.cursor() as cursor:
            cursor.execute("DROP SCHEMA IF EXISTS public CASCADE")
            cursor.execute("CREATE SCHEMA public")


@pytest.fixture(scope="session")
def postgresql_database_url() -> str:
    return _required_postgresql_url()


@pytest.fixture
def empty_postgresql_database_url(
    postgresql_database_url: str,
) -> Iterator[str]:
    _reset_isolated_test_database(postgresql_database_url)
    yield postgresql_database_url
    _reset_isolated_test_database(postgresql_database_url)


@pytest.fixture
def auth_session_factory(
    empty_postgresql_database_url: str,
) -> Iterator[sessionmaker[Session]]:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", empty_postgresql_database_url)
    command.upgrade(config, "head")
    engine = create_database_engine(empty_postgresql_database_url)
    try:
        yield create_session_factory(engine)
    finally:
        engine.dispose()
