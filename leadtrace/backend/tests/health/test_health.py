from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app


def _settings(asset_root: Path, **updates: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "database_url": "postgresql+psycopg://leadtrace:test@database/leadtrace",
        "session_secret": "test-only-session-secret-at-least-32-characters",
        "allowed_hosts": ["testserver"],
        "asset_root": asset_root,
        "redis_url": "redis://redis:6379/0",
    }
    values.update(updates)
    return Settings(_env_file=None, **values)


def test_liveness_does_not_depend_on_database_or_asset_storage(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "missing")

    with TestClient(create_app(settings=settings, database_probe=lambda _: False)) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "live"}


def test_readiness_is_unavailable_when_asset_root_is_missing(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "missing")

    with TestClient(create_app(settings=settings, database_probe=lambda _: True)) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {
            "asset_root": {"status": "unavailable"},
            "database": {"status": "ok"},
        },
    }


def test_readiness_is_unavailable_when_database_probe_fails(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    with TestClient(create_app(settings=settings, database_probe=lambda _: False)) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["checks"]["database"] == {"status": "unavailable"}


def test_readiness_does_not_disclose_database_probe_errors(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    def failing_probe(_: str) -> bool:
        raise RuntimeError("postgresql://user:secret@database/leadtrace")

    with TestClient(create_app(settings=settings, database_probe=failing_probe)) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert "secret" not in response.text
    assert response.json()["checks"]["database"] == {"status": "unavailable"}


def test_readiness_reports_ready_when_required_dependencies_are_available(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)

    with TestClient(create_app(settings=settings, database_probe=lambda _: True)) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {
            "asset_root": {"status": "ok"},
            "database": {"status": "ok"},
        },
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("database_url", "sqlite:///leadtrace.db"),
        ("session_secret", "change-me"),
        ("allowed_hosts", ["*"]),
        ("asset_root", Path("relative/data")),
        ("asset_root", Path("/")),
    ],
)
def test_production_configuration_rejects_unsafe_values(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    values: dict[str, object] = {
        "environment": "production",
        "database_url": "postgresql+psycopg://leadtrace:password@postgres/leadtrace",
        "session_secret": "replace-with-a-random-secret-at-least-32-characters",
        "allowed_hosts": ["leadtrace.lan"],
        "asset_root": tmp_path,
        "redis_url": "redis://redis:6379/0",
    }
    values[field] = value

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_production_configuration_accepts_explicit_safe_values(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        environment="production",
        allowed_hosts=["leadtrace.lan", "10.0.0.20"],
        session_secret="Q7!vZ3#kL9@rT2$xN8%pC4&mW6*eS1^hB",
    )

    assert settings.environment == "production"


def test_production_configuration_requires_explicit_asset_root() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            environment="production",
            database_url="postgresql+psycopg://leadtrace:safe-secret@postgres/leadtrace",
            session_secret="Q7!vZ3#kL9@rT2$xN8%pC4&mW6*eS1^hB",
            allowed_hosts=["leadtrace.lan"],
            redis_url="redis://redis:6379/0",
        )


def test_production_configuration_rejects_example_secret(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _settings(
            tmp_path,
            environment="production",
            allowed_hosts=["leadtrace.lan"],
            session_secret="replace-with-at-least-32-random-characters",
        )
