from __future__ import annotations

from fastapi.routing import APIRoute

from app.config import Settings
from app.main import create_app
from app.security.permissions import RouteAccess
from app.security.policies import Action


def test_single_structure_route_replaces_retired_candidate_routes(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url="postgresql+psycopg://leadtrace:test@database/leadtrace_test",
        redis_url="redis://redis:6379/0",
        session_secret="structure-route-secret-more-than-thirty-two-characters",
        allowed_hosts=["testserver"],
        asset_root=tmp_path,
    )
    application = create_app(
        settings=settings,
        database_probe=lambda _: True,
        database_bootstrap=lambda _: None,
    )
    routes = [route for route in application.routes if isinstance(route, APIRoute)]

    assert not any(route.path.startswith("/api/v1/papers/") for route in routes)
    route = next(
        route
        for route in routes
        if route.path == "/api/v2/compounds/{compound_id}/structure"
    )
    assert route.methods == {"PUT"}
    assert getattr(route.endpoint, "__leadtrace_route_access__") is RouteAccess.PERMISSION
    assert getattr(route.endpoint, "__leadtrace_action__") is Action.EDIT_DRAFT
