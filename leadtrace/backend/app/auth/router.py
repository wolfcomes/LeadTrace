from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.auth.schemas import (
    AuthenticatedUser,
    AuthenticationResponse,
    LoginRequest,
    PasswordChangeRequest,
)
from app.auth.service import AuthenticationError, AuthService, CurrentPasswordError
from app.config import Settings
from app.database import get_db_session
from app.security.csrf import validate_csrf_token
from app.security.permissions import RouteAccess, declare_route_access
from app.security.sessions import SESSION_COOKIE_NAME


def _set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=24 * 60 * 60,
        httponly=True,
        secure=settings.https_enabled,
        samesite="strict",
        path="/",
    )


def _clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=settings.https_enabled,
        samesite="strict",
        path="/",
    )


def create_auth_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
    auth_service = AuthService(settings.session_secret.get_secret_value())

    @router.post("/login", response_model=AuthenticationResponse)
    @declare_route_access(RouteAccess.PUBLIC)
    def login(
        payload: LoginRequest,
        request: Request,
        response: Response,
        session: Session = Depends(get_db_session),
        previous_token: str | None = Cookie(
            default=None,
            alias=SESSION_COOKIE_NAME,
        ),
    ) -> AuthenticationResponse:
        remote_address = request.client.host if request.client else "unknown"
        issued = None
        authentication_error = None
        with session.begin():
            try:
                issued = auth_service.login(
                    session,
                    username=payload.username,
                    password=payload.password,
                    remote_address=remote_address,
                    previous_session_token=previous_token,
                )
            except AuthenticationError as error:
                authentication_error = error
        if authentication_error is not None:
            raise HTTPException(status_code=401, detail=str(authentication_error))
        if issued is None:
            raise RuntimeError("Login completed without a session")
        _set_session_cookie(response, issued.token, settings)
        return AuthenticationResponse(
            user=AuthenticatedUser.from_user(issued.user),
            csrf_token=issued.csrf_token,
        )

    @router.get("/session", response_model=AuthenticationResponse)
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def restore_session(
        session: Session = Depends(get_db_session),
        token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    ) -> AuthenticationResponse:
        if not token:
            raise HTTPException(status_code=401, detail="Authentication required")
        authenticated = None
        with session.begin():
            try:
                authenticated = auth_service.authenticate(session, token)
            except AuthenticationError as error:
                raise HTTPException(
                    status_code=401,
                    detail="Authentication required",
                ) from error
            csrf_token = auth_service.rotate_csrf_token(authenticated.session)
        return AuthenticationResponse(
            user=AuthenticatedUser.from_user(authenticated.user),
            csrf_token=csrf_token,
        )

    @router.post("/logout", status_code=204, response_model=None)
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def logout(
        response: Response,
        session: Session = Depends(get_db_session),
        token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> None:
        if not token:
            raise HTTPException(status_code=401, detail="Authentication required")
        error: HTTPException | None = None
        with session.begin():
            try:
                authenticated = auth_service.authenticate(session, token)
                if not csrf_token or not validate_csrf_token(
                    csrf_token,
                    authenticated.session.csrf_hash,
                    settings.session_secret.get_secret_value(),
                ):
                    error = HTTPException(status_code=403, detail="CSRF validation failed")
                else:
                    auth_service.logout(session, token)
            except AuthenticationError:
                error = HTTPException(status_code=401, detail="Authentication required")
        if error is not None:
            raise error
        _clear_session_cookie(response, settings)

    @router.post("/password", response_model=AuthenticationResponse)
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def change_password(
        payload: PasswordChangeRequest,
        response: Response,
        session: Session = Depends(get_db_session),
        token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> AuthenticationResponse:
        if not token:
            raise HTTPException(status_code=401, detail="Authentication required")
        issued = None
        error: HTTPException | None = None
        with session.begin():
            try:
                authenticated = auth_service.authenticate(session, token)
                if not csrf_token or not validate_csrf_token(
                    csrf_token,
                    authenticated.session.csrf_hash,
                    settings.session_secret.get_secret_value(),
                ):
                    error = HTTPException(status_code=403, detail="CSRF validation failed")
                else:
                    issued = auth_service.change_password(
                        session,
                        token,
                        payload.current_password,
                        payload.new_password,
                    )
            except CurrentPasswordError as current_password_error:
                error = HTTPException(status_code=400, detail=str(current_password_error))
            except AuthenticationError:
                error = HTTPException(status_code=401, detail="Authentication required")
            except ValueError as password_error:
                error = HTTPException(status_code=422, detail=str(password_error))
        if error is not None:
            raise error
        if issued is None:
            raise RuntimeError("Password change completed without a session")
        _set_session_cookie(response, issued.token, settings)
        return AuthenticationResponse(
            user=AuthenticatedUser.from_user(issued.user),
            csrf_token=issued.csrf_token,
        )

    return router
