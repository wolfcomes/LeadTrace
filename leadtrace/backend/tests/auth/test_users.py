from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.audit.models import AuditEvent
from app.auth.models import AuthSession
from app.auth.service import AuthService
from app.security.passwords import verify_password
from app.users.models import User, UserRole
from app.users.service import (
    AccountManagementForbidden,
    LastAdminError,
    UserService,
)


ADMIN_PASSWORD = "Initial admin password 2026!"
DEFAULT_PASSWORD = "managed-default-test-password"
SESSION_SECRET = "user-service-session-secret-more-than-thirty-two-characters"


def test_admin_can_create_each_role_without_mandatory_password_change(
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
    assert all(user.must_change_password is False for user in users)
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


def test_reset_password_remains_optional_and_forces_session_revocation(
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

    assert reset_user.must_change_password is False
    assert reset_user.password_hash != "Temporary visitor password 2026!"


def test_managed_account_creation_is_attributed_to_an_enabled_admin(
    auth_session_factory: sessionmaker[Session],
) -> None:
    users = UserService()
    with auth_session_factory.begin() as session:
        admin = users.create_user(
            session,
            username="admin.one",
            display_name="Admin One",
            role=UserRole.ADMIN,
            initial_password=ADMIN_PASSWORD,
        )
        created = users.create_managed_user(
            session,
            actor_id=admin.id,
            username="reviewer.one",
            display_name="Reviewer One",
            role=UserRole.REVIEWER,
            default_password=DEFAULT_PASSWORD,
            request_id="managed-create",
        )

    with auth_session_factory.begin() as session:
        event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "account.created",
                AuditEvent.target_id == created.id,
            )
        )

    assert created.created_by_id == admin.id
    assert event is not None
    assert event.actor_id == admin.id
    assert event.before_hash != event.after_hash
    assert event.details == {"role": "reviewer"}


def test_bootstrap_admin_is_self_attributed_and_only_allowed_on_an_empty_database(
    auth_session_factory: sessionmaker[Session],
) -> None:
    users = UserService()
    with auth_session_factory.begin() as session:
        admin = users.bootstrap_admin(
            session,
            username="admin.one",
            display_name="Admin One",
            default_password=DEFAULT_PASSWORD,
            request_id="bootstrap-admin",
        )

    with auth_session_factory.begin() as session:
        event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "account.bootstrap_created",
                AuditEvent.target_id == admin.id,
            )
        )
        with pytest.raises(AccountManagementForbidden):
            users.bootstrap_admin(
                session,
                username="admin.two",
                display_name="Admin Two",
                default_password=DEFAULT_PASSWORD,
                request_id="second-bootstrap",
            )

    assert event is not None
    assert event.actor_id == admin.id
    assert event.details == {"bootstrap": True, "role": "admin"}


def test_managed_password_reset_refreshes_locked_state_and_audits_real_changes(
    auth_session_factory: sessionmaker[Session],
) -> None:
    users = UserService()
    auth = AuthService(SESSION_SECRET)
    changed_at = datetime(2026, 9, 13, 7, 0, tzinfo=UTC)
    with auth_session_factory.begin() as session:
        admin = users.create_user(
            session,
            username="admin.one",
            display_name="Admin One",
            role=UserRole.ADMIN,
            initial_password=ADMIN_PASSWORD,
        )
        target = users.create_user(
            session,
            username="reviewer.one",
            display_name="Reviewer One",
            role=UserRole.REVIEWER,
            initial_password=ADMIN_PASSWORD,
        )

    with auth_session_factory.begin() as session:
        auth.login(session, username=target.username, password=ADMIN_PASSWORD)
        auth.login(session, username=target.username, password=ADMIN_PASSWORD)

    session = auth_session_factory()
    try:
        cached = session.get(User, target.id)
        assert cached is not None
        assert cached.role is UserRole.REVIEWER
        with auth_session_factory.begin() as concurrent_session:
            concurrent_target = concurrent_session.get(User, target.id)
            assert concurrent_target is not None
            concurrent_target.role = UserRole.VISITOR

        result = users.reset_managed_password(
            session,
            actor_id=admin.id,
            user_id=target.id,
            default_password=DEFAULT_PASSWORD,
            request_id="managed-reset",
            now=changed_at,
        )
        session.commit()
    finally:
        session.close()

    assert result.user.role is UserRole.VISITOR
    assert result.sessions_revoked == 2
    with auth_session_factory.begin() as session:
        event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "account.password_reset",
                AuditEvent.target_id == target.id,
            )
        )

    assert event is not None
    assert event.before_hash != event.after_hash
    assert event.details == {"role": "visitor", "sessions_revoked": 2}


def test_bulk_default_reset_excludes_admin_and_supports_dry_run(
    auth_session_factory: sessionmaker[Session],
) -> None:
    users = UserService()
    auth = AuthService(SESSION_SECRET)
    changed_at = datetime(2026, 9, 13, 6, 30, tzinfo=UTC)
    with auth_session_factory.begin() as session:
        admin = users.create_user(
            session,
            username="admin.one",
            display_name="Admin One",
            role=UserRole.ADMIN,
            initial_password=ADMIN_PASSWORD,
        )
        reviewer = users.create_user(
            session,
            username="reviewer.one",
            display_name="Reviewer One",
            role=UserRole.REVIEWER,
            initial_password=ADMIN_PASSWORD,
        )
        visitor = users.create_user(
            session,
            username="visitor.one",
            display_name="Visitor One",
            role=UserRole.VISITOR,
            initial_password=ADMIN_PASSWORD,
        )

    with auth_session_factory.begin() as session:
        auth.login(session, username=admin.username, password=ADMIN_PASSWORD)
        auth.login(session, username=reviewer.username, password=ADMIN_PASSWORD)
        auth.login(session, username=visitor.username, password=ADMIN_PASSWORD)

    with auth_session_factory.begin() as session:
        admin_before = session.get(type(admin), admin.id)
        reviewer_before = session.get(type(reviewer), reviewer.id)
        visitor_before = session.get(type(visitor), visitor.id)
        assert admin_before is not None
        assert reviewer_before is not None
        assert visitor_before is not None
        hashes_before = {
            admin.id: admin_before.password_hash,
            reviewer.id: reviewer_before.password_hash,
            visitor.id: visitor_before.password_hash,
        }
        dry_run = users.reset_non_admin_passwords_to_default(
            session,
            actor_id=admin.id,
            default_password=DEFAULT_PASSWORD,
            apply=False,
            request_id="bulk-default-dry-run",
            now=changed_at,
        )

    assert dry_run.applied is False
    assert dry_run.role_counts == {
        UserRole.REVIEWER: 1,
        UserRole.VISITOR: 1,
    }
    with auth_session_factory.begin() as session:
        assert session.get(type(admin), admin.id).password_hash == hashes_before[admin.id]
        assert session.get(type(reviewer), reviewer.id).password_hash == hashes_before[reviewer.id]
        assert session.get(type(visitor), visitor.id).password_hash == hashes_before[visitor.id]
        assert session.scalar(select(AuditEvent)) is None

    with auth_session_factory.begin() as session:
        applied = users.reset_non_admin_passwords_to_default(
            session,
            actor_id=admin.id,
            default_password=DEFAULT_PASSWORD,
            apply=True,
            request_id="bulk-default-apply",
            now=changed_at,
        )

    assert applied.applied is True
    assert applied.role_counts == dry_run.role_counts
    assert set(applied.affected_user_ids) == {reviewer.id, visitor.id}
    with auth_session_factory.begin() as session:
        persisted_admin = session.get(type(admin), admin.id)
        persisted_reviewer = session.get(type(reviewer), reviewer.id)
        persisted_visitor = session.get(type(visitor), visitor.id)
        assert persisted_admin is not None
        assert persisted_reviewer is not None
        assert persisted_visitor is not None
        assert persisted_admin.password_hash == hashes_before[admin.id]
        assert verify_password(persisted_reviewer.password_hash, DEFAULT_PASSWORD)
        assert verify_password(persisted_visitor.password_hash, DEFAULT_PASSWORD)
        assert persisted_reviewer.password_hash != persisted_visitor.password_hash
        assert persisted_reviewer.must_change_password is False
        assert persisted_visitor.must_change_password is False
        active_sessions = set(
            session.scalars(
                select(AuthSession.user_id).where(AuthSession.revoked_at.is_(None))
            )
        )
        assert admin.id in active_sessions
        assert reviewer.id not in active_sessions
        assert visitor.id not in active_sessions
        events = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "account.bulk_default_reset"
                )
            )
        )

    assert {event.target_id for event in events} == {reviewer.id, visitor.id}
    assert all("password" not in str(event.details).casefold() for event in events)
    assert all(event.details["sessions_revoked"] == 1 for event in events)


@pytest.mark.parametrize("actor_kind", ["missing", "disabled_admin", "reviewer", "visitor"])
def test_bulk_default_reset_rejects_any_actor_other_than_an_enabled_admin(
    auth_session_factory: sessionmaker[Session],
    actor_kind: str,
) -> None:
    users = UserService()
    with auth_session_factory.begin() as session:
        users.create_user(
            session,
            username="admin.enabled",
            display_name="Enabled Admin",
            role=UserRole.ADMIN,
            initial_password=ADMIN_PASSWORD,
        )
        disabled_admin = users.create_user(
            session,
            username="admin.disabled",
            display_name="Disabled Admin",
            role=UserRole.ADMIN,
            initial_password=ADMIN_PASSWORD,
        )
        disabled_admin.is_enabled = False
        reviewer = users.create_user(
            session,
            username="reviewer.one",
            display_name="Reviewer One",
            role=UserRole.REVIEWER,
            initial_password=ADMIN_PASSWORD,
        )
        visitor = users.create_user(
            session,
            username="visitor.one",
            display_name="Visitor One",
            role=UserRole.VISITOR,
            initial_password=ADMIN_PASSWORD,
        )
        actor_ids = {
            "missing": uuid4(),
            "disabled_admin": disabled_admin.id,
            "reviewer": reviewer.id,
            "visitor": visitor.id,
        }

    with pytest.raises(AccountManagementForbidden):
        with auth_session_factory.begin() as session:
            users.reset_non_admin_passwords_to_default(
                session,
                actor_id=actor_ids[actor_kind],
                default_password=DEFAULT_PASSWORD,
                apply=False,
                request_id="invalid-bulk-actor",
            )
