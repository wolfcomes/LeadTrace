from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any, TypeVar

from fastapi import Cookie, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.service import AuthenticationError, AuthService
from app.database import get_db_session
from app.security.csrf import validate_csrf_token
from app.security.policies import (
    Action,
    Principal,
    ResourceScope,
    evaluate_access,
)
from app.security.sessions import SESSION_COOKIE_NAME


class RouteAccess(StrEnum):
    PUBLIC = "public"
    AUTHENTICATED = "authenticated"
    PERMISSION = "permission"


Endpoint = TypeVar("Endpoint", bound=Callable[..., Any])


def declare_route_access(
    access: RouteAccess,
    action: Action | None = None,
) -> Callable[[Endpoint], Endpoint]:
    if access == RouteAccess.PERMISSION and action is None:
        raise ValueError("Permission routes must declare an action")
    if access != RouteAccess.PERMISSION and action is not None:
        raise ValueError("Only permission routes may declare an action")

    def decorator(endpoint: Endpoint) -> Endpoint:
        setattr(endpoint, "__leadtrace_route_access__", access)
        setattr(endpoint, "__leadtrace_action__", action)
        return endpoint

    return decorator


def enforce_permission(
    principal: Principal | None,
    action: Action,
    resource: ResourceScope,
) -> None:
    decision = evaluate_access(principal, action, resource)
    if not decision.allowed:
        raise HTTPException(status_code=decision.status_code, detail=decision.reason)


def get_authenticated_principal(
    request: Request,
    session: Session = Depends(get_db_session),
    token: Annotated[
        str | None,
        Cookie(alias=SESSION_COOKIE_NAME),
    ] = None,
) -> Principal:
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    settings = request.app.state.settings
    auth_service = AuthService(settings.session_secret.get_secret_value())
    authenticated = None
    authentication_failed = False
    with session.begin():
        try:
            authenticated = auth_service.authenticate(session, token)
        except AuthenticationError:
            authentication_failed = True
    if authentication_failed or authenticated is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return Principal(
        user_id=authenticated.user.id,
        role=authenticated.user.role,
        must_change_password=authenticated.user.must_change_password,
        csrf_hash=authenticated.session.csrf_hash,
        reauthenticated_at=authenticated.session.reauthenticated_at,
    )


def require_permission(
    action: Action,
) -> Callable[[Principal], Principal]:
    def permission_dependency(
        principal: Principal = Depends(get_authenticated_principal),
    ) -> Principal:
        enforce_permission(principal, action, ResourceScope())
        return principal

    setattr(permission_dependency, "__leadtrace_action__", action)
    return permission_dependency


def require_published_data(
    principal: Principal = Depends(get_authenticated_principal),
) -> Principal:
    enforce_permission(
        principal,
        Action.READ_PUBLISHED_DATA,
        ResourceScope(is_published=True),
    )
    return principal


setattr(require_published_data, "__leadtrace_action__", Action.READ_PUBLISHED_DATA)


def require_request_csrf(
    principal: Principal,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")],
    session_secret: str,
) -> None:
    if (
        not csrf_token
        or not principal.csrf_hash
        or not validate_csrf_token(csrf_token, principal.csrf_hash, session_secret)
    ):
        raise HTTPException(status_code=403, detail="CSRF validation failed")


def require_recent_reauthentication(
    principal: Principal,
    *,
    maximum_age: timedelta,
    now: datetime | None = None,
) -> None:
    checked_at = now or datetime.now(UTC)
    if (
        principal.reauthenticated_at is None
        or checked_at - principal.reauthenticated_at > maximum_age
    ):
        raise HTTPException(
            status_code=403,
            detail="Recent reauthentication required",
        )
