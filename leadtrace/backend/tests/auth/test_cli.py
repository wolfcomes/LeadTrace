from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

import app.cli.users as users_cli
from app.audit.models import AuditEvent
from app.cli.users import _parser
from app.config import Settings
from app.database import DatabaseResources
from app.users.models import User, UserRole


BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_account_creation_uses_configured_default_without_password_arguments() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "app.cli.users", "create", "--help"],
        cwd=BACKEND_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "--password-file" not in completed.stdout
    assert "--password " not in completed.stdout


def test_cli_create_requires_an_admin_actor_or_explicit_bootstrap() -> None:
    parser = _parser()

    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "create",
                "reviewer.one",
                "--display-name",
                "Reviewer One",
                "--role",
                "reviewer",
            ]
        )

    bootstrap = parser.parse_args(
        [
            "create",
            "admin.one",
            "--display-name",
            "Admin One",
            "--role",
            "admin",
            "--bootstrap",
        ]
    )
    managed = parser.parse_args(
        [
            "create",
            "reviewer.one",
            "--display-name",
            "Reviewer One",
            "--role",
            "reviewer",
            "--actor-id",
            "30000000-0000-4000-8000-000000000001",
        ]
    )

    assert bootstrap.bootstrap is True
    assert bootstrap.actor_id is None
    assert managed.bootstrap is False
    assert managed.actor_id == UUID("30000000-0000-4000-8000-000000000001")


def test_cli_individual_reset_requires_an_admin_actor() -> None:
    parser = _parser()
    user_id = "40000000-0000-4000-8000-000000000001"

    with pytest.raises(SystemExit):
        parser.parse_args(["reset", user_id])

    parsed = parser.parse_args(
        [
            "reset",
            user_id,
            "--actor-id",
            "30000000-0000-4000-8000-000000000001",
        ]
    )

    assert parsed.actor_id == UUID("30000000-0000-4000-8000-000000000001")


def test_cli_requires_default_configuration_before_bootstrapping_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url="postgresql+psycopg://unused/leadtrace_test",
        session_secret="cli-test-session-secret-more-than-thirty-two-characters",
        default_account_password=None,
        allowed_hosts=["testserver"],
        asset_root=tmp_path,
    )
    bootstrap_called = False

    def unexpected_bootstrap(_settings: Settings) -> DatabaseResources:
        nonlocal bootstrap_called
        bootstrap_called = True
        raise AssertionError("database bootstrap must not run")

    monkeypatch.setattr(users_cli, "get_settings", lambda: settings)
    monkeypatch.setattr(users_cli, "bootstrap_database", unexpected_bootstrap)

    with pytest.raises(RuntimeError, match="LEADTRACE_DEFAULT_ACCOUNT_PASSWORD"):
        users_cli.main(
            [
                "reset",
                "40000000-0000-4000-8000-000000000001",
                "--actor-id",
                "30000000-0000-4000-8000-000000000001",
            ]
        )

    assert bootstrap_called is False


def test_bulk_default_reset_is_dry_run_unless_apply_is_explicit() -> None:
    parser = _parser()
    dry_run = parser.parse_args(
        ["reset-non-admin-default", "--actor-id", "30000000-0000-4000-8000-000000000001"]
    )
    applied = parser.parse_args(
        [
            "reset-non-admin-default",
            "--actor-id",
            "30000000-0000-4000-8000-000000000001",
            "--apply",
        ]
    )

    assert dry_run.apply is False
    assert applied.apply is True


def test_cli_bootstrap_create_and_reset_append_credential_free_audit_events(
    tmp_path: Path,
    auth_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    default_password = "cli-managed-default-test-value"
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url="postgresql+psycopg://unused/leadtrace_test",
        session_secret="cli-test-session-secret-more-than-thirty-two-characters",
        default_account_password=default_password,
        allowed_hosts=["testserver"],
        asset_root=tmp_path,
    )
    engine = auth_session_factory.kw["bind"]

    monkeypatch.setattr(users_cli, "get_settings", lambda: settings)
    monkeypatch.setattr(
        users_cli,
        "bootstrap_database",
        lambda _settings: DatabaseResources(
            engine=engine,
            session_factory=auth_session_factory,
        ),
    )

    assert users_cli.main(
        [
            "create",
            "admin.one",
            "--display-name",
            "Admin One",
            "--role",
            "admin",
            "--bootstrap",
        ]
    ) == 0
    with auth_session_factory.begin() as session:
        admin = session.scalar(select(User).where(User.role == UserRole.ADMIN))
        assert admin is not None

    assert users_cli.main(
        [
            "create",
            "reviewer.one",
            "--display-name",
            "Reviewer One",
            "--role",
            "reviewer",
            "--actor-id",
            str(admin.id),
        ]
    ) == 0
    with auth_session_factory.begin() as session:
        reviewer = session.scalar(
            select(User).where(User.role == UserRole.REVIEWER)
        )
        assert reviewer is not None

    assert users_cli.main(
        ["reset", str(reviewer.id), "--actor-id", str(admin.id)]
    ) == 0
    captured = capsys.readouterr()
    assert users_cli.main(
        ["reset-non-admin-default", "--actor-id", str(admin.id)]
    ) == 0
    bulk_capture = capsys.readouterr()
    with auth_session_factory.begin() as session:
        events = list(
            session.scalars(select(AuditEvent).order_by(AuditEvent.sequence_number))
        )

    assert [event.action for event in events] == [
        "account.bootstrap_created",
        "account.created",
        "account.password_reset",
    ]
    assert all("password" not in str(event.details).casefold() for event in events)
    assert default_password not in captured.out
    assert default_password not in captured.err
    assert bulk_capture.out == "mode=dry-run reviewer_count=1 visitor_count=0\n"
    assert bulk_capture.err == ""
    assert default_password not in bulk_capture.out
