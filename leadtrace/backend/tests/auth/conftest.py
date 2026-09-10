from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session, sessionmaker

from app.database import create_database_engine, create_session_factory


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

