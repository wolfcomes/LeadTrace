from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.models import AuthSession, LoginAttempt
from app.security.csrf import hash_csrf_token
from app.security.passwords import hash_password, verify_password
from app.security.sessions import (
    generate_csrf_token,
    generate_session_token,
    keyed_token_hash,
)
from app.users.models import User
from app.users.service import UserService, normalize_username


class AuthenticationError(RuntimeError):
    pass


class CurrentPasswordError(AuthenticationError):
    pass


GENERIC_LOGIN_ERROR = "Invalid username or password"
_DUMMY_PASSWORD_HASH = hash_password("Dummy timing password 2026!")


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class IssuedSession:
    token: str
    csrf_token: str
    session: AuthSession
    user: User


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    session: AuthSession
    user: User


class AuthService:
    def __init__(
        self,
        session_secret: str,
        *,
        idle_lifetime: timedelta = timedelta(hours=8),
        absolute_lifetime: timedelta = timedelta(hours=24),
        login_attempt_limit: int = 5,
        login_attempt_window: timedelta = timedelta(minutes=15),
    ) -> None:
        if len(session_secret) < 32:
            raise ValueError("Session secret must contain at least 32 characters")
        self._secret = session_secret
        self._idle_lifetime = idle_lifetime
        self._absolute_lifetime = absolute_lifetime
        self._login_attempt_limit = login_attempt_limit
        self._login_attempt_window = login_attempt_window

    def login(
        self,
        session: Session,
        *,
        username: str,
        password: str,
        remote_address: str = "unknown",
        previous_session_token: str | None = None,
        now: datetime | None = None,
    ) -> IssuedSession:
        login_time = now or _now()
        try:
            normalized_username = normalize_username(username)
        except ValueError:
            normalized_username = username.strip().casefold()
        identity_hash = keyed_token_hash(
            normalized_username,
            self._secret,
            purpose="login-identity",
        )
        failed_attempts = session.scalar(
            select(func.count())
            .select_from(LoginAttempt)
            .where(
                LoginAttempt.identity_hash == identity_hash,
                LoginAttempt.remote_address == remote_address,
                LoginAttempt.was_successful.is_(False),
                LoginAttempt.attempted_at >= login_time - self._login_attempt_window,
            )
        )
        if int(failed_attempts or 0) >= self._login_attempt_limit:
            self._record_attempt(
                session, identity_hash, remote_address, False, login_time
            )
            raise AuthenticationError(GENERIC_LOGIN_ERROR)

        user = session.scalar(
            select(User).where(User.normalized_username == normalized_username)
        )
        password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
        password_matches = verify_password(password_hash, password)
        if user is None or not password_matches or not user.is_enabled:
            self._record_attempt(
                session, identity_hash, remote_address, False, login_time
            )
            raise AuthenticationError(GENERIC_LOGIN_ERROR)

        if previous_session_token:
            self.logout(
                session,
                previous_session_token,
                reason="login_rotation",
                now=login_time,
            )
        self._record_attempt(session, identity_hash, remote_address, True, login_time)
        user.last_login_at = login_time
        return self._issue_session(session, user, login_time)

    def authenticate(
        self,
        session: Session,
        token: str,
        *,
        now: datetime | None = None,
    ) -> AuthenticatedSession:
        checked_at = now or _now()
        token_hash = keyed_token_hash(token, self._secret, purpose="session")
        auth_session = session.scalar(
            select(AuthSession).where(AuthSession.token_hash == token_hash).with_for_update()
        )
        if auth_session is None:
            raise AuthenticationError("Authentication required")
        user = session.get(User, auth_session.user_id)
        expired = (
            checked_at > auth_session.idle_expires_at
            or checked_at > auth_session.absolute_expires_at
        )
        if auth_session.revoked_at is not None or expired or user is None or not user.is_enabled:
            if auth_session.revoked_at is None:
                auth_session.revoked_at = checked_at
                auth_session.revocation_reason = "expired" if expired else "account_disabled"
            raise AuthenticationError("Authentication required")

        auth_session.last_seen_at = checked_at
        auth_session.idle_expires_at = min(
            checked_at + self._idle_lifetime,
            auth_session.absolute_expires_at,
        )
        return AuthenticatedSession(session=auth_session, user=user)

    def logout(
        self,
        session: Session,
        token: str,
        *,
        reason: str = "logout",
        now: datetime | None = None,
    ) -> None:
        token_hash = keyed_token_hash(token, self._secret, purpose="session")
        auth_session = session.scalar(
            select(AuthSession).where(AuthSession.token_hash == token_hash).with_for_update()
        )
        if auth_session is not None and auth_session.revoked_at is None:
            auth_session.revoked_at = now or _now()
            auth_session.revocation_reason = reason

    def rotate_csrf_token(self, auth_session: AuthSession) -> str:
        csrf_token = generate_csrf_token()
        auth_session.csrf_hash = hash_csrf_token(csrf_token, self._secret)
        return csrf_token

    def change_password(
        self,
        session: Session,
        token: str,
        current_password: str,
        new_password: str,
        *,
        now: datetime | None = None,
    ) -> IssuedSession:
        changed_at = now or _now()
        authenticated = self.authenticate(session, token, now=changed_at)
        if not verify_password(authenticated.user.password_hash, current_password):
            raise CurrentPasswordError("Current password is incorrect")
        UserService().change_password(
            session,
            authenticated.user,
            new_password,
            now=changed_at,
        )
        return self._issue_session(session, authenticated.user, changed_at)

    def _issue_session(
        self,
        session: Session,
        user: User,
        issued_at: datetime,
    ) -> IssuedSession:
        token = generate_session_token()
        csrf_token = generate_csrf_token()
        auth_session = AuthSession(
            user_id=user.id,
            token_hash=keyed_token_hash(token, self._secret, purpose="session"),
            csrf_hash=hash_csrf_token(csrf_token, self._secret),
            created_at=issued_at,
            last_seen_at=issued_at,
            idle_expires_at=issued_at + self._idle_lifetime,
            absolute_expires_at=issued_at + self._absolute_lifetime,
        )
        session.add(auth_session)
        session.flush()
        return IssuedSession(
            token=token,
            csrf_token=csrf_token,
            session=auth_session,
            user=user,
        )

    @staticmethod
    def _record_attempt(
        session: Session,
        identity_hash: str,
        remote_address: str,
        successful: bool,
        attempted_at: datetime,
    ) -> None:
        session.add(
            LoginAttempt(
                identity_hash=identity_hash,
                remote_address=remote_address[:64] or "unknown",
                was_successful=successful,
                attempted_at=attempted_at,
            )
        )
