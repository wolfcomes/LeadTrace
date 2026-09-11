from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

from app.config import Settings
from app.database import (
    DatabaseResources,
    SchemaVersionError,
    create_database_engine,
    create_session_factory,
    validate_schema_version,
)
from app.main import create_app
from app.security.passwords import hash_password
from app.security.sessions import keyed_token_hash


BACKEND_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG_PATH = BACKEND_ROOT / "alembic.ini"


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_CONFIG_PATH))
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["leadtrace_database_url"] = database_url
    config.attributes["leadtrace_expected_database_name"] = make_url(
        database_url
    ).database
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


def test_existing_identity_schema_upgrades_through_security_hardening(
    tmp_path: Path,
    empty_postgresql_database_url: str,
) -> None:
    config = _alembic_config(empty_postgresql_database_url)
    script = ScriptDirectory.from_config(config)

    identity_hardening = script.get_revision("0002_identity_hardening")
    assert identity_hardening is not None
    assert identity_hardening.down_revision == "0001_identity"
    command.upgrade(config, "0001_identity")

    engine = create_database_engine(empty_postgresql_database_url)
    legacy_token = "legacy-session-token-that-must-be-revoked"
    session_secret = "migration-test-session-secret-over-thirty-two-characters"
    password = "Existing admin password 2026!"
    created_at = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)
    user_id = uuid4()
    session_id = uuid4()
    try:
        legacy_schema = inspect(engine)
        assert "reauthenticated_at" not in {
            column["name"] for column in legacy_schema.get_columns("auth_sessions")
        }
        assert "source_hash" not in {
            column["name"] for column in legacy_schema.get_columns("login_attempts")
        }
        with pytest.raises(SchemaVersionError, match="does not match Alembic head"):
            validate_schema_version(engine, ALEMBIC_CONFIG_PATH)

        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO users (
                        id, username, normalized_username, display_name, role,
                        is_enabled, password_hash, must_change_password,
                        password_changed_at, last_login_at, created_by_id,
                        created_at, updated_at
                    ) VALUES (
                        :id, 'admin.existing', 'admin.existing', 'Existing Admin',
                        'admin', true, :password_hash, false, :created_at, NULL,
                        NULL, :created_at, :created_at
                    )
                    """
                ),
                {
                    "id": user_id,
                    "password_hash": hash_password(password),
                    "created_at": created_at,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO auth_sessions (
                        id, user_id, token_hash, csrf_hash, created_at,
                        last_seen_at, idle_expires_at, absolute_expires_at,
                        revoked_at, revocation_reason
                    ) VALUES (
                        :id, :user_id, :token_hash, :csrf_hash, :created_at,
                        :created_at, :idle_expires_at, :absolute_expires_at,
                        NULL, NULL
                    )
                    """
                ),
                {
                    "id": session_id,
                    "user_id": user_id,
                    "token_hash": keyed_token_hash(
                        legacy_token,
                        session_secret,
                        purpose="session",
                    ),
                    "csrf_hash": "f" * 64,
                    "created_at": created_at,
                    "idle_expires_at": datetime(2026, 9, 10, 16, 0, tzinfo=UTC),
                    "absolute_expires_at": datetime(2026, 9, 11, 8, 0, tzinfo=UTC),
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO login_attempts (
                        id, identity_hash, remote_address, was_successful,
                        attempted_at
                    ) VALUES (
                        :id, :identity_hash, '127.0.0.1', false, :attempted_at
                    )
                    """
                ),
                {
                    "id": uuid4(),
                    "identity_hash": "e" * 64,
                    "attempted_at": created_at,
                },
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")

    engine = create_database_engine(empty_postgresql_database_url)
    session_factory = create_session_factory(engine)
    try:
        hardened_schema = inspect(engine)
        session_columns = {
            column["name"]: column
            for column in hardened_schema.get_columns("auth_sessions")
        }
        attempt_columns = {
            column["name"]: column
            for column in hardened_schema.get_columns("login_attempts")
        }
        assert session_columns["reauthenticated_at"]["nullable"] is False
        assert attempt_columns["source_hash"]["nullable"] is False
        assert {
            index["name"] for index in hardened_schema.get_indexes("login_attempts")
        } >= {
            "ix_login_attempts_identity_time",
            "ix_login_attempts_source_time",
        }

        with engine.connect() as connection:
            migrated_session = connection.execute(
                text(
                    """
                    SELECT reauthenticated_at, revoked_at, revocation_reason
                    FROM auth_sessions
                    WHERE id = :id
                    """
                ),
                {"id": session_id},
            ).one()
            assert migrated_session.reauthenticated_at == created_at
            assert migrated_session.revoked_at is not None
            assert migrated_session.revocation_reason == "identity_hardening"
            assert connection.scalar(text("SELECT count(*) FROM login_attempts")) == 0

        resources = DatabaseResources(engine=engine, session_factory=session_factory)
        settings = Settings(
            _env_file=None,
            environment="test",
            database_url=empty_postgresql_database_url,
            redis_url="redis://127.0.0.1:6379/0",
            session_secret=session_secret,
            allowed_hosts=["testserver"],
            asset_root=tmp_path,
        )
        application = create_app(
            settings=settings,
            database_probe=lambda _: True,
            database_bootstrap=lambda _: resources,
        )
        with TestClient(application) as client:
            client.cookies.set("leadtrace_session", legacy_token)
            assert client.get("/api/v1/auth/session").status_code == 401
            client.cookies.clear()

            login = client.post(
                "/api/v1/auth/login",
                json={"username": "admin.existing", "password": password},
            )
            assert login.status_code == 200
            restored = client.get("/api/v1/auth/session")
            assert restored.status_code == 200
            assert restored.json()["csrf_token"] == login.json()["csrf_token"]

            rejected_csrf = client.post(
                "/api/v1/auth/reauthenticate",
                headers={"X-CSRF-Token": "invalid"},
                json={"password": password},
            )
            reauthenticated = client.post(
                "/api/v1/auth/reauthenticate",
                headers={"X-CSRF-Token": login.json()["csrf_token"]},
                json={"password": password},
            )
            assert rejected_csrf.status_code == 403
            assert reauthenticated.status_code == 204

            for attempt in range(5):
                failed = client.post(
                    "/api/v1/auth/login",
                    json={
                        "username": f"unknown.user.{attempt}",
                        "password": "wrong password",
                    },
                )
                assert failed.status_code == 401
            throttled = client.post(
                "/api/v1/auth/login",
                json={"username": "admin.existing", "password": password},
            )
            assert throttled.status_code == 401
    finally:
        engine.dispose()


def test_explicit_test_migration_target_wins_over_ambient_runtime_url(
    monkeypatch: pytest.MonkeyPatch,
    empty_postgresql_database_url: str,
) -> None:
    missing_database_url = make_url(empty_postgresql_database_url).set(
        database="leadtrace_database_that_must_not_be_used"
    )
    monkeypatch.setenv(
        "LEADTRACE_DATABASE_URL",
        missing_database_url.render_as_string(hide_password=False),
    )
    config = _alembic_config(empty_postgresql_database_url)

    command.upgrade(config, "head")

    assert _database_revision(empty_postgresql_database_url) == (
        ScriptDirectory.from_config(config).get_current_head()
    )


def test_guarded_migration_rejects_a_different_connected_database(
    empty_postgresql_database_url: str,
) -> None:
    config = _alembic_config(empty_postgresql_database_url)
    config.attributes["leadtrace_expected_database_name"] = "different_test"

    with pytest.raises(RuntimeError, match="expected database"):
        command.upgrade(config, "head")
