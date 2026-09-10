from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from app.database import (
    SchemaVersionError,
    create_database_engine,
    validate_schema_version,
)


BACKEND_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG_PATH = BACKEND_ROOT / "alembic.ini"


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_CONFIG_PATH))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _database_revision(database_url: str) -> str | None:
    engine = create_database_engine(database_url)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def test_empty_database_is_rejected_until_migrated(
    empty_postgresql_database_url: str,
) -> None:
    engine = create_database_engine(empty_postgresql_database_url)
    try:
        with pytest.raises(SchemaVersionError, match="Alembic head"):
            validate_schema_version(engine, ALEMBIC_CONFIG_PATH)
    finally:
        engine.dispose()


def test_empty_postgresql_database_upgrades_to_single_alembic_head(
    empty_postgresql_database_url: str,
) -> None:
    config = _alembic_config(empty_postgresql_database_url)

    command.upgrade(config, "head")

    script_head = ScriptDirectory.from_config(config).get_current_head()
    assert script_head is not None
    assert _database_revision(empty_postgresql_database_url) == script_head

    engine = create_database_engine(empty_postgresql_database_url)
    try:
        assert inspect(engine).has_table("alembic_version")
        validate_schema_version(engine, ALEMBIC_CONFIG_PATH)
    finally:
        engine.dispose()


def test_foundation_migration_safely_downgrades_to_base(
    empty_postgresql_database_url: str,
) -> None:
    config = _alembic_config(empty_postgresql_database_url)
    command.upgrade(config, "head")

    command.downgrade(config, "base")

    assert _database_revision(empty_postgresql_database_url) is None


def test_alembic_cli_uses_runtime_database_url(
    empty_postgresql_database_url: str,
) -> None:
    config = _alembic_config(empty_postgresql_database_url)
    command.upgrade(config, "head")
    expected_head = ScriptDirectory.from_config(config).get_current_head()
    environment = os.environ.copy()
    environment["LEADTRACE_DATABASE_URL"] = empty_postgresql_database_url

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(ALEMBIC_CONFIG_PATH),
            "current",
        ],
        cwd=BACKEND_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert expected_head in completed.stdout
