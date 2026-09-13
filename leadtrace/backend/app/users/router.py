from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.errors import request_id_for
from app.auth.router import resolve_remote_address
from app.config import Settings
from app.database import get_db_session
from app.security.permissions import (
    RouteAccess,
    declare_route_access,
    require_permission,
    require_recent_reauthentication,
    require_request_csrf,
)
from app.security.policies import Action, Principal
from app.users.schemas import (
    EnabledUpdateRequest,
    RoleUpdateRequest,
    UserCreateRequest,
    UserResponse,
)
from app.users.service import (
    AccountManagementForbidden,
    LastAdminError,
    UserNotFoundError,
    UserService,
)


def create_users_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1/users", tags=["users"])
    user_service = UserService()
    require_account_management = require_permission(Action.MANAGE_ACCOUNTS)

    def managed_default_password() -> str:
        configured = settings.default_account_password
        if configured is None:
            raise HTTPException(
                status_code=503,
                detail="Managed account provisioning is unavailable",
            )
        return configured.get_secret_value()

    def verify_csrf(principal: Principal, csrf_token: str | None) -> None:
        require_request_csrf(
            principal,
            csrf_token,
            settings.session_secret.get_secret_value(),
        )

    def verify_critical_action(
        principal: Principal,
        csrf_token: str | None,
    ) -> None:
        verify_csrf(principal, csrf_token)
        require_recent_reauthentication(
            principal,
            maximum_age=timedelta(
                minutes=settings.admin_reauthentication_minutes
            ),
        )

    @router.get("", response_model=list[UserResponse])
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_ACCOUNTS)
    def list_users(
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_account_management),
    ) -> list[UserResponse]:
        with session.begin():
            users = user_service.list_users(session)
        return [UserResponse.from_user(user) for user in users]

    @router.post("", status_code=201, response_model=UserResponse)
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_ACCOUNTS)
    def create_user(
        payload: UserCreateRequest,
        request: Request,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_account_management),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> UserResponse:
        try:
            with session.begin():
                verify_critical_action(principal, csrf_token)
                user = user_service.create_managed_user(
                    session,
                    actor_id=principal.user_id,
                    username=payload.username,
                    display_name=payload.display_name,
                    role=payload.role,
                    default_password=managed_default_password(),
                    request_id=request_id_for(request),
                    ip_address=resolve_remote_address(request, settings),
                )
        except IntegrityError as error:
            raise HTTPException(status_code=409, detail="Username already exists") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except AccountManagementForbidden as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        return UserResponse.from_user(user)

    @router.patch("/{user_id}/password", response_model=UserResponse)
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_ACCOUNTS)
    def reset_password(
        user_id: UUID,
        request: Request,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_account_management),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> UserResponse:
        try:
            with session.begin():
                verify_critical_action(principal, csrf_token)
                result = user_service.reset_managed_password(
                    session,
                    actor_id=principal.user_id,
                    user_id=user_id,
                    default_password=managed_default_password(),
                    request_id=request_id_for(request),
                    ip_address=resolve_remote_address(request, settings),
                )
                user = result.user
        except UserNotFoundError as error:
            raise HTTPException(status_code=404, detail="User not found") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except AccountManagementForbidden as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        return UserResponse.from_user(user)

    @router.patch("/{user_id}/enabled", response_model=UserResponse)
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_ACCOUNTS)
    def set_enabled(
        user_id: UUID,
        payload: EnabledUpdateRequest,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_account_management),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> UserResponse:
        try:
            with session.begin():
                verify_critical_action(principal, csrf_token)
                user = user_service.set_enabled(session, user_id, payload.is_enabled)
        except UserNotFoundError as error:
            raise HTTPException(status_code=404, detail="User not found") from error
        except LastAdminError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return UserResponse.from_user(user)

    @router.patch("/{user_id}/role", response_model=UserResponse)
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_ACCOUNTS)
    def set_role(
        user_id: UUID,
        payload: RoleUpdateRequest,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_account_management),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> UserResponse:
        try:
            with session.begin():
                verify_critical_action(principal, csrf_token)
                user = user_service.set_role(session, user_id, payload.role)
        except UserNotFoundError as error:
            raise HTTPException(status_code=404, detail="User not found") from error
        except LastAdminError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return UserResponse.from_user(user)

    @router.post("/{user_id}/sessions/revoke", status_code=204, response_model=None)
    @declare_route_access(RouteAccess.PERMISSION, Action.MANAGE_ACCOUNTS)
    def revoke_sessions(
        user_id: UUID,
        session: Session = Depends(get_db_session),
        principal: Principal = Depends(require_account_management),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> None:
        with session.begin():
            verify_critical_action(principal, csrf_token)
            user_service.revoke_sessions(session, user_id)

    return router
