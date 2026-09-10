from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.auth.models import AuthSession
from app.auth.service import AuthenticationError, AuthService
from app.security.csrf import validate_csrf_token
from app.users.models import UserRole
from app.users.service import UserService


SESSION_SECRET = "session-test-key-with-more-than-thirty-two-characters"
INITIAL_PASSWORD = "Initial reviewer password 2026!"


def _create_reviewer(
    session_factory: sessionmaker[Session],
    *,
    username: str = "reviewer.one",
):
    with session_factory.begin() as session:
        return UserService().create_user(
            session,
            username=username,
            display_name="Reviewer One",
            role=UserRole.REVIEWER,
            initial_password=INITIAL_PASSWORD,
        )


def test_login_persists_only_keyed_token_and_csrf_hashes(
    auth_session_factory: sessionmaker[Session],
) -> None:
    _create_reviewer(auth_session_factory)
    service = AuthService(SESSION_SECRET)
    now = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)

    with auth_session_factory.begin() as session:
        issued = service.login(
            session,
            username="REVIEWER.ONE",
            password=INITIAL_PASSWORD,
            remote_address="127.0.0.1",
            now=now,
        )

    with auth_session_factory() as session:
        persisted = session.scalar(select(AuthSession))

    assert persisted is not None
    assert issued.session.id == persisted.id
    assert issued.token not in persisted.token_hash
    assert issued.csrf_token not in persisted.csrf_hash
    assert len(persisted.token_hash) == 64
    assert len(persisted.csrf_hash) == 64
    assert persisted.idle_expires_at == now + timedelta(hours=8)
    assert persisted.absolute_expires_at == now + timedelta(hours=24)
    assert validate_csrf_token(
        issued.csrf_token,
        persisted.csrf_hash,
        SESSION_SECRET,
    )


def test_session_idle_timeout_and_absolute_timeout_are_enforced(
    auth_session_factory: sessionmaker[Session],
) -> None:
    _create_reviewer(auth_session_factory)
    service = AuthService(SESSION_SECRET)
    started_at = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)

    with auth_session_factory.begin() as session:
        idle_session = service.login(
            session,
            username="reviewer.one",
            password=INITIAL_PASSWORD,
            now=started_at,
        )
        absolute_session = service.login(
            session,
            username="reviewer.one",
            password=INITIAL_PASSWORD,
            now=started_at,
        )

    with auth_session_factory.begin() as session:
        with pytest.raises(AuthenticationError):
            service.authenticate(
                session,
                idle_session.token,
                now=started_at + timedelta(hours=8, seconds=1),
            )

        service.authenticate(
            session,
            absolute_session.token,
            now=started_at + timedelta(hours=7),
        )
        service.authenticate(
            session,
            absolute_session.token,
            now=started_at + timedelta(hours=14),
        )
        service.authenticate(
            session,
            absolute_session.token,
            now=started_at + timedelta(hours=22),
        )
        service.authenticate(
            session,
            absolute_session.token,
            now=started_at + timedelta(hours=23, minutes=59),
        )
        with pytest.raises(AuthenticationError):
            service.authenticate(
                session,
                absolute_session.token,
                now=started_at + timedelta(hours=24, seconds=1),
            )


def test_login_rotates_an_existing_session(
    auth_session_factory: sessionmaker[Session],
) -> None:
    _create_reviewer(auth_session_factory)
    service = AuthService(SESSION_SECRET)
    now = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)

    with auth_session_factory.begin() as session:
        first = service.login(
            session,
            username="reviewer.one",
            password=INITIAL_PASSWORD,
            now=now,
        )

    with auth_session_factory.begin() as session:
        second = service.login(
            session,
            username="reviewer.one",
            password=INITIAL_PASSWORD,
            previous_session_token=first.token,
            now=now + timedelta(minutes=1),
        )

    assert first.token != second.token
    with auth_session_factory.begin() as session:
        with pytest.raises(AuthenticationError):
            service.authenticate(session, first.token, now=now + timedelta(minutes=2))
        assert (
            service.authenticate(
                session,
                second.token,
                now=now + timedelta(minutes=2),
            ).user.username
            == "reviewer.one"
        )


def test_explicit_logout_revokes_the_server_session(
    auth_session_factory: sessionmaker[Session],
) -> None:
    _create_reviewer(auth_session_factory)
    service = AuthService(SESSION_SECRET)
    now = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)

    with auth_session_factory.begin() as session:
        issued = service.login(
            session,
            username="reviewer.one",
            password=INITIAL_PASSWORD,
            now=now,
        )
    with auth_session_factory.begin() as session:
        service.logout(session, issued.token, now=now + timedelta(minutes=1))
    with auth_session_factory.begin() as session:
        with pytest.raises(AuthenticationError):
            service.authenticate(session, issued.token, now=now + timedelta(minutes=2))


def test_password_reset_disablement_and_role_change_revoke_sessions(
    auth_session_factory: sessionmaker[Session],
) -> None:
    reviewer = _create_reviewer(auth_session_factory)
    auth_service = AuthService(SESSION_SECRET)
    user_service = UserService()
    now = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)

    def issue() -> str:
        with auth_session_factory.begin() as session:
            return auth_service.login(
                session,
                username="reviewer.one",
                password=INITIAL_PASSWORD,
                now=now,
            ).token

    reset_token = issue()
    with auth_session_factory.begin() as session:
        user_service.reset_password(
            session,
            reviewer.id,
            "Reset reviewer password 2026!",
            now=now + timedelta(minutes=1),
        )
    with auth_session_factory.begin() as session:
        with pytest.raises(AuthenticationError):
            auth_service.authenticate(session, reset_token, now=now + timedelta(minutes=2))

    with auth_session_factory.begin() as session:
        user_service.reset_password(
            session,
            reviewer.id,
            INITIAL_PASSWORD,
            now=now + timedelta(minutes=3),
        )
    disabled_token = issue()
    with auth_session_factory.begin() as session:
        user_service.set_enabled(session, reviewer.id, False, now=now + timedelta(minutes=4))
    with auth_session_factory.begin() as session:
        with pytest.raises(AuthenticationError):
            auth_service.authenticate(
                session, disabled_token, now=now + timedelta(minutes=5)
            )

    with auth_session_factory.begin() as session:
        user_service.set_enabled(session, reviewer.id, True, now=now + timedelta(minutes=6))
    role_token = issue()
    with auth_session_factory.begin() as session:
        user_service.set_role(
            session,
            reviewer.id,
            UserRole.VISITOR,
            now=now + timedelta(minutes=7),
        )
    with auth_session_factory.begin() as session:
        with pytest.raises(AuthenticationError):
            auth_service.authenticate(session, role_token, now=now + timedelta(minutes=8))


def test_repeated_failures_are_rate_limited_without_revealing_username(
    auth_session_factory: sessionmaker[Session],
) -> None:
    _create_reviewer(auth_session_factory)
    service = AuthService(SESSION_SECRET, login_attempt_limit=3)
    now = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)

    for attempt in range(3):
        with auth_session_factory.begin() as session:
            with pytest.raises(AuthenticationError, match="Invalid username or password"):
                service.login(
                    session,
                    username="reviewer.one",
                    password="wrong password",
                    remote_address="127.0.0.1",
                    now=now + timedelta(seconds=attempt),
                )

    with auth_session_factory.begin() as session:
        with pytest.raises(AuthenticationError, match="Invalid username or password"):
            service.login(
                session,
                username="reviewer.one",
                password=INITIAL_PASSWORD,
                remote_address="127.0.0.1",
                now=now + timedelta(seconds=4),
            )
