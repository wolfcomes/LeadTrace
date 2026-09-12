from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.database import DatabaseResources
from app.main import create_app
from app.users.models import UserRole
from app.users.service import UserService


PASSWORD = "Release route password 2026!"


@pytest.fixture
def release_api_client(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> Iterator[TestClient]:
    with auth_session_factory.begin() as session:
        for role in UserRole:
            user = UserService().create_user(
                session,
                username=f"release.{role.value}",
                display_name=f"Release {role.value}",
                role=role,
                initial_password=PASSWORD,
            )
            user.must_change_password = False
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=empty_postgresql_database_url,
        redis_url="redis://127.0.0.1:6379/0",
        session_secret="release-route-secret-more-than-thirty-two-characters",
        allowed_hosts=["testserver"],
        asset_root=tmp_path,
    )
    resources = DatabaseResources(
        engine=auth_session_factory.kw["bind"],
        session_factory=auth_session_factory,
    )
    application = create_app(
        settings=settings,
        database_probe=lambda _: True,
        database_bootstrap=lambda _: resources,
    )
    with TestClient(application) as client:
        yield client


def _login(client: TestClient, role: UserRole) -> str:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/login",
        json={"username": f"release.{role.value}", "password": PASSWORD},
    )
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (None, 401),
        (UserRole.VISITOR, 403),
        (UserRole.REVIEWER, 403),
        (UserRole.ADMIN, 409),
    ],
)
def test_release_routes_enforce_admin_role_over_http(
    release_api_client: TestClient,
    role: UserRole | None,
    expected: int,
) -> None:
    client = release_api_client
    client.cookies.clear()
    csrf = _login(client, role) if role is not None else None
    headers = {
        "X-CSRF-Token": csrf or "anonymous",
        "Idempotency-Key": f"route-{role or 'anonymous'}",
    }
    target_id = uuid4()

    listing = client.get("/api/v1/releases")
    scientific_evidence = client.get(
        f"/api/v1/approvals/{target_id}/scientific-evidence"
    )
    preview = client.get(f"/api/v1/releases/preview/{target_id}")
    publish = client.post(
        "/api/v1/releases/publish",
        headers=headers,
        json={"changeset_id": str(target_id), "notes": "Route test"},
    )
    rollback = client.post(
        "/api/v1/releases/rollback",
        headers=headers,
        json={
            "target_release_id": str(target_id),
            "reason": "Route test rollback",
        },
    )

    if role is UserRole.ADMIN:
        assert listing.status_code == 200
    else:
        assert listing.status_code == expected
    assert preview.status_code == expected
    assert scientific_evidence.status_code == (404 if role is UserRole.ADMIN else expected)
    assert publish.status_code == expected
    assert rollback.status_code == expected


def test_release_mutations_require_csrf_and_idempotency_key(
    release_api_client: TestClient,
) -> None:
    client = release_api_client
    csrf = _login(client, UserRole.ADMIN)
    target_id = str(uuid4())
    payload = {
        "target_release_id": target_id,
        "reason": "Verify mutation protection",
    }

    missing_csrf = client.post(
        "/api/v1/releases/rollback",
        headers={"Idempotency-Key": "missing-csrf"},
        json=payload,
    )
    missing_idempotency = client.post(
        "/api/v1/releases/rollback",
        headers={"X-CSRF-Token": csrf},
        json=payload,
    )

    assert missing_csrf.status_code == 403
    assert missing_idempotency.status_code == 400
