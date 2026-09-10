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


@pytest.mark.parametrize(
    "url_prefix",
    ["postgresql+psycopg://", "postgresql://"],
)
def test_alembic_cli_uses_supported_runtime_database_urls(
    empty_postgresql_database_url: str,
    url_prefix: str,
) -> None:
    config = _alembic_config(empty_postgresql_database_url)
    command.upgrade(config, "head")
    expected_head = ScriptDirectory.from_config(config).get_current_head()
    environment = os.environ.copy()
    environment["LEADTRACE_DATABASE_URL"] = empty_postgresql_database_url.replace(
        "postgresql+psycopg://",
        url_prefix,
        1,
    )

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


def test_application_starts_only_after_empty_database_is_migrated(
    tmp_path: Path,
    empty_postgresql_database_url: str,
) -> None:
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app

    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=empty_postgresql_database_url,
        redis_url="redis://127.0.0.1:6379/0",
        session_secret="fresh-deployment-test-secret-over-thirty-two-characters",
        allowed_hosts=["testserver"],
        asset_root=tmp_path,
    )
    application = create_app(settings=settings, database_probe=lambda _: True)

    with pytest.raises(SchemaVersionError):
        with TestClient(application):
            pass

    command.upgrade(_alembic_config(empty_postgresql_database_url), "head")

    with TestClient(application) as client:
        assert client.get("/health/live").status_code == 200


def test_alembic_metadata_matches_the_migrated_schema(
    empty_postgresql_database_url: str,
) -> None:
    config = _alembic_config(empty_postgresql_database_url)
    command.upgrade(config, "head")
    environment = os.environ.copy()
    environment["LEADTRACE_DATABASE_URL"] = empty_postgresql_database_url

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(ALEMBIC_CONFIG_PATH),
            "check",
        ],
        cwd=BACKEND_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "No new upgrade operations detected" in completed.stdout
