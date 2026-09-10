from __future__ import annotations

from ipaddress import ip_address

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.auth.schemas import (
    AuthenticatedUser,
    AuthenticationResponse,
    LoginRequest,
    PasswordChangeRequest,
    ReauthenticationRequest,
)
from app.auth.service import AuthenticationError, AuthService, CurrentPasswordError
from app.config import Settings
from app.database import get_db_session
from app.security.permissions import (
    RouteAccess,
    declare_route_access,
    get_authenticated_principal,
    require_request_csrf,
)
from app.security.policies import Principal
from app.security.sessions import SESSION_COOKIE_NAME
from app.users.models import User


def resolve_remote_address(request: Request, settings: Settings) -> str:
    """Resolve a login source without trusting client-supplied proxy chains."""

    peer_address = request.client.host if request.client else "unknown"
    if peer_address not in settings.trusted_proxy_addresses:
        return peer_address
    claimed_address = request.headers.get("X-Real-IP", "").strip()
    try:
        return str(ip_address(claimed_address))
    except ValueError:
        return peer_address


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
        remote_address = resolve_remote_address(request, settings)
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
        principal: Principal = Depends(get_authenticated_principal),
    ) -> AuthenticationResponse:
        with session.begin():
            user = session.get(User, principal.user_id)
            if user is None or token is None:
                raise HTTPException(status_code=401, detail="Authentication required")
            csrf_token = auth_service.csrf_token_for_session_token(token)
        return AuthenticationResponse(
            user=AuthenticatedUser.from_user(user),
            csrf_token=csrf_token,
        )

    @router.post("/logout", status_code=204, response_model=None)
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def logout(
        response: Response,
        session: Session = Depends(get_db_session),
        token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> None:
        if token is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        require_request_csrf(
            principal,
            csrf_token,
            settings.session_secret.get_secret_value(),
        )
        with session.begin():
            auth_service.logout(session, token)
        _clear_session_cookie(response, settings)

    @router.post("/reauthenticate", status_code=204, response_model=None)
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def reauthenticate(
        payload: ReauthenticationRequest,
        session: Session = Depends(get_db_session),
        token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> None:
        if token is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        require_request_csrf(
            principal,
            csrf_token,
            settings.session_secret.get_secret_value(),
        )
        with session.begin():
            try:
                auth_service.reauthenticate(session, token, payload.password)
            except CurrentPasswordError as error:
                raise HTTPException(status_code=401, detail=str(error)) from error

    @router.post("/password", response_model=AuthenticationResponse)
    @declare_route_access(RouteAccess.AUTHENTICATED)
    def change_password(
        payload: PasswordChangeRequest,
        response: Response,
        session: Session = Depends(get_db_session),
        token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        principal: Principal = Depends(get_authenticated_principal),
    ) -> AuthenticationResponse:
        if token is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        require_request_csrf(
            principal,
            csrf_token,
            settings.session_secret.get_secret_value(),
        )
        issued = None
        error: HTTPException | None = None
        with session.begin():
            try:
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
