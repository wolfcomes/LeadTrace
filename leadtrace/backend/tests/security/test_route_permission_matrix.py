from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.database import DatabaseResources
from app.main import create_app
from app.users.models import UserRole
from app.users.service import UserService


INITIAL_PASSWORD = "Initial route matrix password 2026!"
UPDATED_PASSWORD = "Updated route matrix password 2026!"


@pytest.fixture
def role_matrix_client(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> Iterator[tuple[TestClient, UUID]]:
    with auth_session_factory.begin() as session:
        for role in UserRole:
            UserService().create_user(
                session,
                username=f"matrix.{role.value}",
                display_name=f"Matrix {role.value.title()}",
                role=role,
                initial_password=INITIAL_PASSWORD,
            )
        target = UserService().create_user(
            session,
            username="matrix.target",
            display_name="Matrix Target",
            role=UserRole.VISITOR,
            initial_password=INITIAL_PASSWORD,
        )
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=empty_postgresql_database_url,
        redis_url="redis://127.0.0.1:6379/0",
        session_secret="route-http-matrix-secret-more-than-thirty-two-characters",
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
        yield client, target.id


def _login_and_finish_first_login(client: TestClient, role: UserRole) -> str:
    login = client.post(
        "/api/v1/auth/login",
        json={
            "username": f"matrix.{role.value}",
            "password": INITIAL_PASSWORD,
        },
    )
    assert login.status_code == 200
    password_change = client.post(
        "/api/v1/auth/password",
        headers={"X-CSRF-Token": login.json()["csrf_token"]},
        json={
            "current_password": INITIAL_PASSWORD,
            "new_password": UPDATED_PASSWORD,
        },
    )
    assert password_change.status_code == 200
    return str(password_change.json()["csrf_token"])


def _exercise_all_user_routes(
    client: TestClient,
    target_id: UUID,
    *,
    csrf_token: str | None,
    username_suffix: str,
) -> dict[tuple[str, str], int]:
    headers = {"X-CSRF-Token": csrf_token} if csrf_token else {}
    requests = [
        ("GET", "/api/v1/users", None),
        (
            "POST",
            "/api/v1/users",
            {
                "username": f"created.{username_suffix}",
                "display_name": "Created by Matrix",
                "role": "visitor",
                "initial_password": "Initial created password 2026!",
            },
        ),
        (
            "PATCH",
            f"/api/v1/users/{target_id}/password",
            {"one_time_password": "Reset target password 2026!"},
        ),
        (
            "PATCH",
            f"/api/v1/users/{target_id}/enabled",
            {"is_enabled": True},
        ),
        (
            "PATCH",
            f"/api/v1/users/{target_id}/role",
            {"role": "visitor"},
        ),
        ("POST", f"/api/v1/users/{target_id}/sessions/revoke", None),
    ]
    responses: dict[tuple[str, str], int] = {}
    for method, path, payload in requests:
        response = client.request(method, path, headers=headers, json=payload)
        route_template = path.replace(str(target_id), "{user_id}")
        responses[(method, route_template)] = response.status_code
    return responses


@pytest.mark.parametrize(
    ("principal_role", "expected_statuses"),
    [
        (None, {401}),
        (UserRole.VISITOR, {403}),
        (UserRole.REVIEWER, {403}),
        (UserRole.ADMIN, {200, 201, 204}),
    ],
)
def test_every_user_route_enforces_the_role_matrix_over_http(
    role_matrix_client: tuple[TestClient, UUID],
    principal_role: UserRole | None,
    expected_statuses: set[int],
) -> None:
    client, target_id = role_matrix_client
    csrf_token = (
        _login_and_finish_first_login(client, principal_role)
        if principal_role is not None
        else None
    )

    responses = _exercise_all_user_routes(
        client,
        target_id,
        csrf_token=csrf_token,
        username_suffix=principal_role.value if principal_role else "anonymous",
    )

    assert set(responses) == {
        ("GET", "/api/v1/users"),
        ("POST", "/api/v1/users"),
        ("PATCH", "/api/v1/users/{user_id}/password"),
        ("PATCH", "/api/v1/users/{user_id}/enabled"),
        ("PATCH", "/api/v1/users/{user_id}/role"),
        ("POST", "/api/v1/users/{user_id}/sessions/revoke"),
    }
    assert set(responses.values()).issubset(expected_statuses)
    if principal_role is UserRole.ADMIN:
        assert responses[("GET", "/api/v1/users")] == 200
        assert responses[("POST", "/api/v1/users")] == 201
        assert responses[("POST", "/api/v1/users/{user_id}/sessions/revoke")] == 204
