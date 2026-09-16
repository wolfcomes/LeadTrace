from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.database import DatabaseResources
from app.main import create_app
from app.security.permissions import RouteAccess
from app.security.policies import Action
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
        default_account_password=UPDATED_PASSWORD,
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
            },
        ),
        (
            "PATCH",
            f"/api/v1/users/{target_id}/password",
            None,
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


def test_retired_scientific_v1_routes_are_not_registered(
    role_matrix_client: tuple[TestClient, UUID],
) -> None:
    client, _ = role_matrix_client
    paths = {route.path for route in client.app.routes}

    assert {
        "/health/live",
        "/health/ready",
        "/internal/metrics",
        "/api/v1/auth/login",
        "/api/v1/users",
        "/api/v1/assets/{asset_id}",
        "/api/v1/audit/events",
        "/api/v2/admin/papers",
        "/api/v2/admin/papers/{paper_id}",
        "/api/v2/admin/papers/{paper_id}/assign",
        "/api/v2/review/tasks",
        "/api/v2/workspaces/{workspace_id}",
        "/api/v2/workspaces/{workspace_id}/bibliography",
        "/api/v2/workspaces/{workspace_id}/sections/{section}",
        "/api/v2/workspaces/{workspace_id}/compounds",
        "/api/v2/workspaces/{workspace_id}/compounds/order",
        "/api/v2/workspaces/{workspace_id}/lineages",
        "/api/v2/workspaces/{workspace_id}/lineages/order",
        "/api/v2/workspaces/{workspace_id}/evidence",
        "/api/v2/compounds/{compound_id}",
        "/api/v2/compounds/{compound_id}/structure",
        "/api/v2/compounds/{compound_id}/structure/depiction",
        "/api/v2/compounds/{compound_id}/source-images",
        "/api/v2/compounds/{compound_id}/activities",
        "/api/v2/compounds/{compound_id}/activities/order",
        "/api/v2/lineages/{lineage_id}",
        "/api/v2/lineages/{lineage_id}/members",
        "/api/v2/lineages/{lineage_id}/members/order",
        "/api/v2/lineages/{lineage_id}/edges",
        "/api/v2/lineages/{lineage_id}/edges/order",
        "/api/v2/lineage-members/{member_id}",
        "/api/v2/lineage-edges/{edge_id}",
        "/api/v2/lineage-edges/{edge_id}/evidence-links",
        "/api/v2/evidence/{evidence_id}",
        "/api/v2/edge-evidence-links/{link_id}",
        "/api/v2/activities/{activity_id}",
        "/api/v2/structure-source-images/{source_image_id}",
        "/api/v2/structure-source-images/{source_image_id}/content",
        "/api/v2/structure-source-images/{source_image_id}/retry",
        "/api/v2/papers/{paper_id}/source-pdf",
    } <= paths
    assert not any(
        path.startswith(prefix)
        for path in paths
        for prefix in (
            "/api/v1/admin",
            "/api/v1/approvals",
            "/api/v1/crop-jobs",
            "/api/v1/papers",
            "/api/v1/published",
            "/api/v1/releases",
            "/api/v1/review",
        )
    )

    catalog_routes = [
        route
        for route in client.app.routes
        if isinstance(route, APIRoute)
        and route.path.startswith("/api/v2/admin/papers")
    ]
    assert len(catalog_routes) == 3
    assert all(
        getattr(route.endpoint, "__leadtrace_route_access__", None)
        is RouteAccess.PERMISSION
        for route in catalog_routes
    )
    assert all(
        getattr(route.endpoint, "__leadtrace_action__", None)
        is Action.MANAGE_PAPER_CATALOG
        for route in catalog_routes
    )

    workspace_routes = [
        route
        for route in client.app.routes
        if isinstance(route, APIRoute)
        and (
            route.path == "/api/v2/review/tasks"
            or route.path.startswith("/api/v2/workspaces/")
        )
    ]
    assert len(workspace_routes) == 12
    assert all(
        getattr(route.endpoint, "__leadtrace_route_access__", None)
        is RouteAccess.PERMISSION
        for route in workspace_routes
    )
    actions = {
        (next(iter(route.methods)), route.path): getattr(
            route.endpoint, "__leadtrace_action__", None
        )
        for route in workspace_routes
    }
    assert actions == {
        ("GET", "/api/v2/review/tasks"): Action.READ_DRAFT,
        ("GET", "/api/v2/workspaces/{workspace_id}"): Action.READ_DRAFT,
        (
            "PATCH",
            "/api/v2/workspaces/{workspace_id}/bibliography",
        ): Action.EDIT_DRAFT,
        (
            "PUT",
            "/api/v2/workspaces/{workspace_id}/sections/{section}",
        ): Action.EDIT_DRAFT,
        (
            "GET",
            "/api/v2/workspaces/{workspace_id}/compounds",
        ): Action.READ_DRAFT,
        (
            "POST",
            "/api/v2/workspaces/{workspace_id}/compounds",
        ): Action.EDIT_DRAFT,
        (
            "PUT",
            "/api/v2/workspaces/{workspace_id}/compounds/order",
        ): Action.EDIT_DRAFT,
        (
            "GET",
            "/api/v2/workspaces/{workspace_id}/lineages",
        ): Action.READ_DRAFT,
        (
            "POST",
            "/api/v2/workspaces/{workspace_id}/lineages",
        ): Action.EDIT_DRAFT,
        (
            "PUT",
            "/api/v2/workspaces/{workspace_id}/lineages/order",
        ): Action.EDIT_DRAFT,
        (
            "GET",
            "/api/v2/workspaces/{workspace_id}/evidence",
        ): Action.READ_DRAFT,
        (
            "POST",
            "/api/v2/workspaces/{workspace_id}/evidence",
        ): Action.EDIT_DRAFT,
    }

    compound_routes = [
        route
        for route in client.app.routes
        if isinstance(route, APIRoute)
        and route.path.startswith("/api/v2/compounds/")
        and not route.path.endswith("/source-images")
    ]
    assert len(compound_routes) == 8
    assert all(
        getattr(route.endpoint, "__leadtrace_route_access__", None)
        is RouteAccess.PERMISSION
        for route in compound_routes
    )
    assert {
        (next(iter(route.methods)), route.path): getattr(
            route.endpoint, "__leadtrace_action__", None
        )
        for route in compound_routes
    } == {
        ("PATCH", "/api/v2/compounds/{compound_id}"): Action.EDIT_DRAFT,
        ("DELETE", "/api/v2/compounds/{compound_id}"): Action.EDIT_DRAFT,
        (
            "GET",
            "/api/v2/compounds/{compound_id}/structure",
        ): Action.READ_DRAFT,
        (
            "PUT",
            "/api/v2/compounds/{compound_id}/structure",
        ): Action.EDIT_DRAFT,
        (
            "GET",
            "/api/v2/compounds/{compound_id}/structure/depiction",
        ): Action.READ_DRAFT,
        (
            "GET",
            "/api/v2/compounds/{compound_id}/activities",
        ): Action.READ_DRAFT,
        (
            "POST",
            "/api/v2/compounds/{compound_id}/activities",
        ): Action.EDIT_DRAFT,
        (
            "PUT",
            "/api/v2/compounds/{compound_id}/activities/order",
        ): Action.EDIT_DRAFT,
    }

    science_record_routes = [
        route
        for route in client.app.routes
        if isinstance(route, APIRoute)
        and route.path.startswith(
            (
                "/api/v2/lineages/",
                "/api/v2/lineage-members/",
                "/api/v2/lineage-edges/",
                "/api/v2/evidence/",
                "/api/v2/edge-evidence-links/",
                "/api/v2/activities/",
            )
        )
    ]
    assert len(science_record_routes) == 20
    assert all(
        getattr(route.endpoint, "__leadtrace_route_access__", None)
        is RouteAccess.PERMISSION
        for route in science_record_routes
    )
    assert {
        (next(iter(route.methods)), route.path): getattr(
            route.endpoint, "__leadtrace_action__", None
        )
        for route in science_record_routes
    } == {
        ("PATCH", "/api/v2/lineages/{lineage_id}"): Action.EDIT_DRAFT,
        ("DELETE", "/api/v2/lineages/{lineage_id}"): Action.EDIT_DRAFT,
        ("GET", "/api/v2/lineages/{lineage_id}/members"): Action.READ_DRAFT,
        ("POST", "/api/v2/lineages/{lineage_id}/members"): Action.EDIT_DRAFT,
        (
            "PUT",
            "/api/v2/lineages/{lineage_id}/members/order",
        ): Action.EDIT_DRAFT,
        ("GET", "/api/v2/lineages/{lineage_id}/edges"): Action.READ_DRAFT,
        ("POST", "/api/v2/lineages/{lineage_id}/edges"): Action.EDIT_DRAFT,
        (
            "PUT",
            "/api/v2/lineages/{lineage_id}/edges/order",
        ): Action.EDIT_DRAFT,
        ("PATCH", "/api/v2/lineage-members/{member_id}"): Action.EDIT_DRAFT,
        ("DELETE", "/api/v2/lineage-members/{member_id}"): Action.EDIT_DRAFT,
        ("PATCH", "/api/v2/lineage-edges/{edge_id}"): Action.EDIT_DRAFT,
        ("DELETE", "/api/v2/lineage-edges/{edge_id}"): Action.EDIT_DRAFT,
        (
            "GET",
            "/api/v2/lineage-edges/{edge_id}/evidence-links",
        ): Action.READ_DRAFT,
        (
            "POST",
            "/api/v2/lineage-edges/{edge_id}/evidence-links",
        ): Action.EDIT_DRAFT,
        ("PATCH", "/api/v2/evidence/{evidence_id}"): Action.EDIT_DRAFT,
        ("DELETE", "/api/v2/evidence/{evidence_id}"): Action.EDIT_DRAFT,
        (
            "PATCH",
            "/api/v2/edge-evidence-links/{link_id}",
        ): Action.EDIT_DRAFT,
        (
            "DELETE",
            "/api/v2/edge-evidence-links/{link_id}",
        ): Action.EDIT_DRAFT,
        ("PATCH", "/api/v2/activities/{activity_id}"): Action.EDIT_DRAFT,
        ("DELETE", "/api/v2/activities/{activity_id}"): Action.EDIT_DRAFT,
    }

    source_image_routes = [
        route
        for route in client.app.routes
        if isinstance(route, APIRoute)
        and (
            route.path.endswith("/source-images")
            or route.path.startswith("/api/v2/structure-source-images/")
        )
    ]
    assert len(source_image_routes) == 7
    assert all(
        getattr(route.endpoint, "__leadtrace_route_access__", None)
        is RouteAccess.PERMISSION
        for route in source_image_routes
    )
    assert {
        (next(iter(route.methods)), route.path): getattr(
            route.endpoint, "__leadtrace_action__", None
        )
        for route in source_image_routes
    } == {
        ("GET", "/api/v2/compounds/{compound_id}/source-images"): Action.READ_DRAFT,
        ("POST", "/api/v2/compounds/{compound_id}/source-images"): Action.EDIT_DRAFT,
        ("GET", "/api/v2/structure-source-images/{source_image_id}"): Action.READ_DRAFT,
        ("GET", "/api/v2/structure-source-images/{source_image_id}/content"): Action.READ_DRAFT,
        ("PATCH", "/api/v2/structure-source-images/{source_image_id}"): Action.EDIT_DRAFT,
        ("DELETE", "/api/v2/structure-source-images/{source_image_id}"): Action.EDIT_DRAFT,
        ("POST", "/api/v2/structure-source-images/{source_image_id}/retry"): Action.EDIT_DRAFT,
    }

    document_routes = [
        route
        for route in client.app.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/v2/papers/{paper_id}/source-pdf"
    ]
    assert len(document_routes) == 1
    assert getattr(
        document_routes[0].endpoint, "__leadtrace_route_access__", None
    ) is RouteAccess.PERMISSION
    assert getattr(
        document_routes[0].endpoint, "__leadtrace_action__", None
    ) is Action.READ_FULL_PDF
