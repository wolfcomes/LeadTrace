from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.users.models import UserRole
from app.users.service import LastAdminError, UserService


ADMIN_PASSWORD = "Initial admin password 2026!"


def test_admin_can_create_each_role_with_one_time_password(
    auth_session_factory: sessionmaker[Session],
) -> None:
    service = UserService()
    now = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)

    with auth_session_factory.begin() as session:
        users = [
            service.create_user(
                session,
                username=f"user.{role.value}",
                display_name=role.value.title(),
                role=role,
                initial_password=ADMIN_PASSWORD,
                now=now,
            )
            for role in UserRole
        ]

    assert [user.role for user in users] == list(UserRole)
    assert all(user.must_change_password for user in users)
    assert all(user.password_hash != ADMIN_PASSWORD for user in users)


def test_usernames_are_unique_case_insensitively(
    auth_session_factory: sessionmaker[Session],
) -> None:
    service = UserService()
    with auth_session_factory.begin() as session:
        service.create_user(
            session,
            username="Reviewer.One",
            display_name="Reviewer One",
            role=UserRole.REVIEWER,
            initial_password=ADMIN_PASSWORD,
        )

    with pytest.raises(IntegrityError):
        with auth_session_factory.begin() as session:
            service.create_user(
                session,
                username="reviewer.one",
                display_name="Duplicate Reviewer",
                role=UserRole.REVIEWER,
                initial_password=ADMIN_PASSWORD,
            )


def test_last_enabled_admin_cannot_be_disabled_or_demoted(
    auth_session_factory: sessionmaker[Session],
) -> None:
    service = UserService()
    with auth_session_factory.begin() as session:
        admin = service.create_user(
            session,
            username="admin.one",
            display_name="Admin One",
            role=UserRole.ADMIN,
            initial_password=ADMIN_PASSWORD,
        )

    with pytest.raises(LastAdminError):
        with auth_session_factory.begin() as session:
            service.set_enabled(session, admin.id, False)

    with pytest.raises(LastAdminError):
        with auth_session_factory.begin() as session:
            service.set_role(session, admin.id, UserRole.REVIEWER)


def test_one_of_two_enabled_admins_can_be_disabled(
    auth_session_factory: sessionmaker[Session],
) -> None:
    service = UserService()
    with auth_session_factory.begin() as session:
        first = service.create_user(
            session,
            username="admin.one",
            display_name="Admin One",
            role=UserRole.ADMIN,
            initial_password=ADMIN_PASSWORD,
        )
        service.create_user(
            session,
            username="admin.two",
            display_name="Admin Two",
            role=UserRole.ADMIN,
            initial_password=ADMIN_PASSWORD,
        )

    with auth_session_factory.begin() as session:
        disabled = service.set_enabled(session, first.id, False)

    assert disabled.is_enabled is False


def test_reset_password_marks_it_one_time_and_forces_session_revocation(
    auth_session_factory: sessionmaker[Session],
) -> None:
    service = UserService()
    with auth_session_factory.begin() as session:
        user = service.create_user(
            session,
            username="visitor.one",
            display_name="Visitor One",
            role=UserRole.VISITOR,
            initial_password=ADMIN_PASSWORD,
        )
        user.must_change_password = False

    with auth_session_factory.begin() as session:
        reset_user = service.reset_password(
            session,
            user.id,
            "Temporary visitor password 2026!",
        )

    assert reset_user.must_change_password is True
    assert reset_user.password_hash != "Temporary visitor password 2026!"

