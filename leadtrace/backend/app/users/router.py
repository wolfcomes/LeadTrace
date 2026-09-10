from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.router import SESSION_COOKIE_NAME
from app.auth.service import AuthenticatedSession, AuthenticationError, AuthService
from app.config import Settings
from app.database import get_db_session
from app.security.csrf import validate_csrf_token
from app.users.models import UserRole
from app.users.schemas import (
    EnabledUpdateRequest,
    PasswordResetRequest,
    RoleUpdateRequest,
    UserCreateRequest,
    UserResponse,
)
from app.users.service import LastAdminError, UserNotFoundError, UserService


def create_users_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1/users", tags=["users"])
    auth_service = AuthService(settings.session_secret.get_secret_value())
    user_service = UserService()

    def require_admin(
        session: Session,
        token: str | None,
        csrf_token: str | None = None,
        *,
        state_change: bool,
    ) -> AuthenticatedSession:
        if not token:
            raise HTTPException(status_code=401, detail="Authentication required")
        try:
            authenticated = auth_service.authenticate(session, token)
        except AuthenticationError as error:
            raise HTTPException(
                status_code=401,
                detail="Authentication required",
            ) from error
        if authenticated.user.must_change_password:
            raise HTTPException(status_code=403, detail="Password change required")
        if authenticated.user.role != UserRole.ADMIN:
            raise HTTPException(status_code=403, detail="Admin access required")
        if state_change and (
            not csrf_token
            or not validate_csrf_token(
                csrf_token,
                authenticated.session.csrf_hash,
                settings.session_secret.get_secret_value(),
            )
        ):
            raise HTTPException(status_code=403, detail="CSRF validation failed")
        return authenticated

    @router.get("", response_model=list[UserResponse])
    def list_users(
        session: Session = Depends(get_db_session),
        token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ) -> list[UserResponse]:
        with session.begin():
            require_admin(session, token, state_change=False)
            users = user_service.list_users(session)
        return [UserResponse.from_user(user) for user in users]

    @router.post("", status_code=201, response_model=UserResponse)
    def create_user(
        payload: UserCreateRequest,
        session: Session = Depends(get_db_session),
        token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> UserResponse:
        try:
            with session.begin():
                admin = require_admin(
                    session,
                    token,
                    csrf_token,
                    state_change=True,
                )
                user = user_service.create_user(
                    session,
                    username=payload.username,
                    display_name=payload.display_name,
                    role=payload.role,
                    initial_password=payload.initial_password,
                    created_by_id=admin.user.id,
                )
        except IntegrityError as error:
            raise HTTPException(status_code=409, detail="Username already exists") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return UserResponse.from_user(user)

    @router.patch("/{user_id}/password", response_model=UserResponse)
    def reset_password(
        user_id: UUID,
        payload: PasswordResetRequest,
        session: Session = Depends(get_db_session),
        token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> UserResponse:
        try:
            with session.begin():
                require_admin(session, token, csrf_token, state_change=True)
                user = user_service.reset_password(
                    session,
                    user_id,
                    payload.one_time_password,
                )
        except UserNotFoundError as error:
            raise HTTPException(status_code=404, detail="User not found") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return UserResponse.from_user(user)

    @router.patch("/{user_id}/enabled", response_model=UserResponse)
    def set_enabled(
        user_id: UUID,
        payload: EnabledUpdateRequest,
        session: Session = Depends(get_db_session),
        token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> UserResponse:
        try:
            with session.begin():
                require_admin(session, token, csrf_token, state_change=True)
                user = user_service.set_enabled(session, user_id, payload.is_enabled)
        except UserNotFoundError as error:
            raise HTTPException(status_code=404, detail="User not found") from error
        except LastAdminError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return UserResponse.from_user(user)

    @router.patch("/{user_id}/role", response_model=UserResponse)
    def set_role(
        user_id: UUID,
        payload: RoleUpdateRequest,
        session: Session = Depends(get_db_session),
        token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> UserResponse:
        try:
            with session.begin():
                require_admin(session, token, csrf_token, state_change=True)
                user = user_service.set_role(session, user_id, payload.role)
        except UserNotFoundError as error:
            raise HTTPException(status_code=404, detail="User not found") from error
        except LastAdminError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return UserResponse.from_user(user)

    @router.post("/{user_id}/sessions/revoke", status_code=204, response_model=None)
    def revoke_sessions(
        user_id: UUID,
        session: Session = Depends(get_db_session),
        token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> None:
        with session.begin():
            require_admin(session, token, csrf_token, state_change=True)
            user_service.revoke_sessions(session, user_id)

    return router
