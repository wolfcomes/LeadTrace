from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.engine import make_url

from app.database import create_database_engine

BACKEND_ROOT = Path(__file__).resolve().parents[2]
CONSTRAINT_NAME = "uq_structure_source_images_compound_occurrence"


def _config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["leadtrace_database_url"] = database_url
    config.attributes["leadtrace_expected_database_name"] = make_url(database_url).database
    return config


def _unique_constraint_names(database_url: str) -> set[str]:
    engine = create_database_engine(database_url)
    try:
        return {
            constraint["name"]
            for constraint in inspect(engine).get_unique_constraints(
                "structure_source_images", schema="public"
            )
        }
    finally:
        engine.dispose()


def test_occurrence_uniqueness_migration_remains_reversible_from_head(
    empty_postgresql_database_url: str,
) -> None:
    config = _config(empty_postgresql_database_url)
    command.upgrade(config, "head")
    expected_head = ScriptDirectory.from_config(config).get_current_head()
    assert expected_head is not None
    assert CONSTRAINT_NAME in _unique_constraint_names(empty_postgresql_database_url)

    command.downgrade(config, "0020_paper_science_records")
    assert CONSTRAINT_NAME not in _unique_constraint_names(empty_postgresql_database_url)

    command.upgrade(config, "head")
    engine = create_database_engine(empty_postgresql_database_url)
    try:
        with engine.connect() as connection:
            revision = MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()
    assert revision == expected_head
