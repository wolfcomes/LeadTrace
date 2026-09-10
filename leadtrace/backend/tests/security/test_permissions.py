from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest
from fastapi.routing import APIRoute

from app.config import Settings
from app.main import create_app
from app.security.permissions import RouteAccess
from app.security.policies import Action, Principal, ResourceScope, evaluate_access
from app.users.models import UserRole


VISITOR_ID = UUID("10000000-0000-0000-0000-000000000001")
REVIEWER_ID = UUID("20000000-0000-0000-0000-000000000001")
OTHER_REVIEWER_ID = UUID("20000000-0000-0000-0000-000000000002")
ADMIN_ID = UUID("30000000-0000-0000-0000-000000000001")


PRINCIPALS = {
    "anonymous": None,
    "visitor": Principal(VISITOR_ID, UserRole.VISITOR),
    "reviewer": Principal(REVIEWER_ID, UserRole.REVIEWER),
    "other_reviewer": Principal(OTHER_REVIEWER_ID, UserRole.REVIEWER),
    "admin": Principal(ADMIN_ID, UserRole.ADMIN),
}

PUBLISHED = ResourceScope(is_published=True)
APPROVED_EVIDENCE = ResourceScope(is_published=True, is_approved=True)
ASSIGNED = ResourceScope(assigned_reviewer_ids=frozenset({REVIEWER_ID}))
OWN_ASSIGNED_DRAFT = replace(ASSIGNED, owner_id=REVIEWER_ID)
OTHER_REVIEWER_DRAFT = replace(ASSIGNED, owner_id=OTHER_REVIEWER_ID)


CAPABILITY_MATRIX = [
    (
        Action.READ_PUBLISHED_DATA,
        PUBLISHED,
        frozenset({"visitor", "reviewer", "admin"}),
    ),
    (
        Action.READ_APPROVED_EVIDENCE,
        APPROVED_EVIDENCE,
        frozenset({"visitor", "reviewer", "admin"}),
    ),
    (Action.READ_FULL_PDF, ASSIGNED, frozenset({"reviewer", "admin"})),
    (Action.READ_DRAFT, OWN_ASSIGNED_DRAFT, frozenset({"reviewer", "admin"})),
    (Action.CREATE_DRAFT, ASSIGNED, frozenset({"reviewer", "admin"})),
    (Action.EDIT_DRAFT, OWN_ASSIGNED_DRAFT, frozenset({"reviewer", "admin"})),
    (
        Action.SUBMIT_CHANGESET,
        OWN_ASSIGNED_DRAFT,
        frozenset({"reviewer", "admin"}),
    ),
    (Action.APPROVE_CHANGESET, OWN_ASSIGNED_DRAFT, frozenset({"admin"})),
    (Action.PUBLISH_RELEASE, OWN_ASSIGNED_DRAFT, frozenset({"admin"})),
    (Action.ROLLBACK_RELEASE, PUBLISHED, frozenset({"admin"})),
    (Action.MANAGE_ACCOUNTS, ResourceScope(), frozenset({"admin"})),
    (
        Action.EXPORT_UNPUBLISHED,
        OWN_ASSIGNED_DRAFT,
        frozenset({"reviewer", "admin"}),
    ),
    (Action.READ_AUDIT, OWN_ASSIGNED_DRAFT, frozenset({"reviewer", "admin"})),
]


@pytest.mark.parametrize(
    ("principal_name", "action", "resource", "allowed"),
    [
        (principal_name, action, resource, principal_name in allowed_principals)
        for action, resource, allowed_principals in CAPABILITY_MATRIX
        for principal_name in ("anonymous", "visitor", "reviewer", "admin")
    ],
)
def test_approved_role_and_resource_permission_matrix(
    principal_name: str,
    action: Action,
    resource: ResourceScope,
    allowed: bool,
) -> None:
    decision = evaluate_access(PRINCIPALS[principal_name], action, resource)

    assert decision.allowed is allowed


@pytest.mark.parametrize(
    "action",
    [
        Action.READ_FULL_PDF,
        Action.READ_DRAFT,
        Action.CREATE_DRAFT,
        Action.EDIT_DRAFT,
        Action.SUBMIT_CHANGESET,
        Action.EXPORT_UNPUBLISHED,
        Action.READ_AUDIT,
    ],
)
def test_other_reviewer_cannot_cross_assignment_or_ownership_boundaries(
    action: Action,
) -> None:
    if action in {Action.READ_FULL_PDF, Action.CREATE_DRAFT}:
        principal = PRINCIPALS["other_reviewer"]
        resource = ASSIGNED
    else:
        principal = PRINCIPALS["reviewer"]
        resource = OTHER_REVIEWER_DRAFT

    decision = evaluate_access(principal, action, resource)

    assert decision.allowed is False


def test_first_login_principal_is_limited_until_password_change() -> None:
    principal = Principal(
        ADMIN_ID,
        UserRole.ADMIN,
        must_change_password=True,
    )

    decision = evaluate_access(principal, Action.MANAGE_ACCOUNTS, ResourceScope())

    assert decision.allowed is False
    assert decision.status_code == 403
    assert decision.reason == "Password change required"


def test_every_api_v1_route_declares_its_access_policy(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url="postgresql+psycopg://leadtrace:test@database/leadtrace_test",
        redis_url="redis://redis:6379/0",
        session_secret="route-matrix-secret-with-more-than-thirty-two-characters",
        allowed_hosts=["testserver"],
        asset_root=tmp_path,
    )
    application = create_app(
        settings=settings,
        database_probe=lambda _: True,
        database_bootstrap=lambda _: None,
    )
    api_routes = [
        route
        for route in application.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/v1")
    ]

    assert api_routes
    assert all(
        isinstance(getattr(route.endpoint, "__leadtrace_route_access__", None), RouteAccess)
        for route in api_routes
    )
    assert all(
        getattr(route.endpoint, "__leadtrace_action__", None)
        == Action.MANAGE_ACCOUNTS
        for route in api_routes
        if route.path.startswith("/api/v1/users")
    )
