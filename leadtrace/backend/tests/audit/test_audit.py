from __future__ import annotations

from datetime import UTC, datetime
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Thread, current_thread
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, event, select, update
from sqlalchemy.exc import DBAPIError

from app.audit.models import AuditEvent
from app.audit.service import (
    AuditImmutableError,
    AuditService,
    canonical_content_hash,
    persisted_content_hash,
    persisted_json_value,
    redact_secrets,
)
from app.papers.models import Paper
from app.releases.models import Release
from app.users.models import UserRole
from app.users.service import UserService


PASSWORD = "Audit test password 2026!"


def _setup_scope(session) -> tuple[UUID, UUID, UUID]:
    actor = UserService().create_user(
        session,
        username=f"audit-admin-{uuid4().hex[:8]}",
        display_name="Audit Admin",
        role=UserRole.ADMIN,
        initial_password=PASSWORD,
    )
    actor.must_change_password = False
    paper = Paper(paper_key=f"audit-paper-{uuid4().hex[:8]}", doi=None)
    session.add(paper)
    session.flush()
    release = Release(
        release_key=f"audit-release-{uuid4().hex[:8]}",
        title="Audit release",
        notes="",
        metrics={},
        published_by_id=actor.id,
        published_at=datetime.now(UTC),
        is_current=False,
        manifest_finalized=True,
    )
    session.add(release)
    session.flush()
    return actor.id, paper.id, release.id


def _append(
    session,
    actor_id: UUID,
    paper_id: UUID,
    release_id: UUID,
    number: int = 1,
    *,
    details: dict[str, object] | None = None,
):
    return AuditService().append_event(
        session,
        actor_id=actor_id,
        action="review.changeset.updated",
        target_type="changeset",
        target_id=uuid4(),
        paper_id=paper_id,
        changeset_id=None,
        release_id=release_id,
        ip_address="192.0.2.10",
        request_id=f"request-{number}",
        result="success",
        reason="Reviewer corrected source-bound metadata",
        before_hash=canonical_content_hash({"title": "Before"}),
        after_hash=canonical_content_hash({"title": f"After {number}"}),
        details=details or {"field": "title"},
    )


def test_audit_event_records_complete_context_and_verifies_hash_chain(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        actor_id, paper_id, release_id = _setup_scope(session)
        first = _append(session, actor_id, paper_id, release_id)
        second = _append(session, actor_id, paper_id, release_id, 2)

        assert first.sequence_number == 1
        assert second.sequence_number == 2
        assert first.actor_id == actor_id
        assert first.action == "review.changeset.updated"
        assert first.target_type == "changeset"
        assert first.target_id is not None
        assert first.paper_id == paper_id
        assert first.changeset_id is None
        assert first.release_id == release_id
        assert first.occurred_at.tzinfo is not None
        assert first.ip_address == "192.0.2.10"
        assert first.request_id == "request-1"
        assert first.result == "success"
        assert first.reason == "Reviewer corrected source-bound metadata"
        assert len(first.before_hash) == len(first.after_hash) == 64
        assert first.previous_event_hash == "0" * 64
        assert second.previous_event_hash == first.event_hash
        assert len(first.event_hash) == len(second.event_hash) == 64

        verification = AuditService().verify_chain(session)
        assert verification.valid is True
        assert verification.event_count == 2
        assert verification.first_invalid_sequence is None


def test_audit_details_recursively_redact_credentials_and_tokens() -> None:
    sanitized = redact_secrets(
        {
            "password": "plain text",
            "session_id": "opaque session",
            "csrf": "bare csrf value",
            "csrfToken": "csrf value",
            "Authorization": "Bearer token",
            "Cookie": "leadtrace_session=secret",
            "nested": {
                "client_secret": "client secret",
                "private_key": "private key",
                "private_key_pem": "private key material",
                "credentials": "credential bundle",
                "access_key": "access credential",
                "aws_access_key_id": "aws access credential",
                "x_api_key": "vendor api credential",
                "authorization_header": "Basic credential",
                "cookie_header": "session cookie",
                "safe": "retained",
            },
            "items": [{"api-key": "api secret"}, "ordinary"],
        }
    )

    assert sanitized == {
        "password": "[REDACTED]",
        "session_id": "[REDACTED]",
        "csrf": "[REDACTED]",
        "csrfToken": "[REDACTED]",
        "Authorization": "[REDACTED]",
        "Cookie": "[REDACTED]",
        "nested": {
            "client_secret": "[REDACTED]",
            "private_key": "[REDACTED]",
            "private_key_pem": "[REDACTED]",
            "credentials": "[REDACTED]",
            "access_key": "[REDACTED]",
            "aws_access_key_id": "[REDACTED]",
            "x_api_key": "[REDACTED]",
            "authorization_header": "[REDACTED]",
            "cookie_header": "[REDACTED]",
            "safe": "retained",
        },
        "items": [{"api-key": "[REDACTED]"}, "ordinary"],
    }


def test_audit_reason_redacts_inline_credentials_and_hashes_persisted_reason(
    auth_session_factory,
) -> None:
    secret_reason = (
        "Reviewer note password=plain-password token: bearer-secret "
        "api_key=vendor-secret authorization=Bearer auth-secret "
        "csrf=bare-csrf-key csrf_token=csrf-token session=session-secret "
        "session_id=session-id-secret"
    )
    with auth_session_factory.begin() as session:
        actor_id, paper_id, release_id = _setup_scope(session)
        event = AuditService().append_event(
            session,
            actor_id=actor_id,
            action="review.changeset.updated",
            target_type="changeset",
            target_id=uuid4(),
            paper_id=paper_id,
            changeset_id=None,
            release_id=release_id,
            ip_address="192.0.2.10",
            request_id="reason-redaction",
            result="success",
            reason=secret_reason,
            before_hash=canonical_content_hash({"before": True}),
            after_hash=canonical_content_hash({"after": True}),
            details={},
        )
        assert "plain-password" not in event.reason
        assert "bearer-secret" not in event.reason
        assert "vendor-secret" not in event.reason
        assert "auth-secret" not in event.reason
        assert "bare-csrf-key" not in event.reason
        assert "csrf-token" not in event.reason
        assert "session-secret" not in event.reason
        assert "session-id-secret" not in event.reason
        assert event.reason.count("[REDACTED]") == 8
        assert AuditService().verify_chain(session).valid is True


def test_audit_hash_uses_persisted_jsonb_numeric_representation(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        actor_id, paper_id, release_id = _setup_scope(session)
        _append(
            session,
            actor_id,
            paper_id,
            release_id,
            details={
                "normalized_values": {
                    "negative_zero": -0.0,
                    "exponent": 1e20,
                    "large_integer": 123456789012345678901234567890,
                }
            },
        )

    with auth_session_factory() as session:
        verification = AuditService().verify_chain(session)

    assert verification.valid is True
    assert verification.first_invalid_sequence is None


def test_persisted_content_hash_matches_jsonb_value_in_audit_details(
    auth_session_factory,
) -> None:
    value = {"normalized_values": {"x0": -0.0, "exponent": 1e20}}
    with auth_session_factory.begin() as session:
        persisted = persisted_json_value(session, value)
        assert persisted == {
            "normalized_values": {"x0": 0.0, "exponent": 100000000000000000000}
        }
        assert persisted_content_hash(session, value) == canonical_content_hash(persisted)


def test_audit_events_reject_orm_and_database_update_or_delete(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        actor_id, paper_id, release_id = _setup_scope(session)
        event = _append(session, actor_id, paper_id, release_id)
        event_id = event.id

    with auth_session_factory() as session:
        event = session.get(AuditEvent, event_id)
        assert event is not None
        event.reason = "tampered"
        with pytest.raises(AuditImmutableError):
            session.flush()
        session.rollback()

    with auth_session_factory() as session:
        with pytest.raises(DBAPIError):
            session.execute(
                update(AuditEvent)
                .where(AuditEvent.id == event_id)
                .values(reason="tampered through SQL")
            )
        session.rollback()

    with auth_session_factory() as session:
        with pytest.raises(DBAPIError):
            session.execute(delete(AuditEvent).where(AuditEvent.id == event_id))
        session.rollback()

    with auth_session_factory() as session:
        assert session.scalar(
            select(AuditEvent.reason).where(AuditEvent.id == event_id)
        ) == "Reviewer corrected source-bound metadata"


def test_concurrent_audit_appends_form_one_unbroken_sequence(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        actor_id, paper_id, release_id = _setup_scope(session)
    ready = Barrier(2)

    def append(number: int) -> int:
        with auth_session_factory.begin() as session:
            ready.wait(timeout=5)
            return _append(
                session, actor_id, paper_id, release_id, number
            ).sequence_number

    with ThreadPoolExecutor(max_workers=2) as executor:
        sequences = list(executor.map(append, (1, 2)))

    with auth_session_factory() as session:
        assert sorted(sequences) == [1, 2]
        assert AuditService().verify_chain(session).valid is True


def test_audit_locks_release_before_global_chain_head(auth_session_factory) -> None:
    with auth_session_factory.begin() as session:
        actor_id, paper_id, release_id = _setup_scope(session)

    statements: list[str] = []
    engine = auth_session_factory.kw["bind"]

    def record_lock_statements(
        _connection, _cursor, statement, _parameters, _context, _many
    ) -> None:
        if "FOR UPDATE" in statement and (
            "audit_chain_head" in statement or "releases" in statement
        ):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_lock_statements)
    try:
        with auth_session_factory.begin() as session:
            _append(session, actor_id, paper_id, release_id)
    finally:
        event.remove(engine, "before_cursor_execute", record_lock_statements)

    release_index = next(
        index for index, statement in enumerate(statements) if "releases" in statement
    )
    head_index = next(
        index
        for index, statement in enumerate(statements)
        if "audit_chain_head" in statement
    )
    assert release_index < head_index


def test_chain_verification_is_a_consistent_snapshot_during_append(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        actor_id, paper_id, release_id = _setup_scope(session)
        _append(session, actor_id, paper_id, release_id)

    events_read = Event()
    append_committed = Event()
    verification_results = []

    def coordinate_verification_snapshot(
        _connection, _cursor, statement, _parameters, _context, _many
    ) -> None:
        if "FROM audit_events ORDER BY audit_events.sequence_number" in statement:
            events_read.set()
        if (
            current_thread().name == "audit-verifier"
            and "FROM audit_chain_head" in statement
            and events_read.is_set()
        ):
            assert append_committed.wait(timeout=5)

    engine = auth_session_factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", coordinate_verification_snapshot)
    try:
        def verify() -> None:
            with auth_session_factory.begin() as session:
                verification_results.append(AuditService().verify_chain(session))

        def append() -> None:
            assert events_read.wait(timeout=5)
            with auth_session_factory.begin() as session:
                _append(session, actor_id, paper_id, release_id, 2)
            append_committed.set()

        threads = [
            Thread(target=verify, name="audit-verifier"),
            Thread(target=append, name="audit-appender"),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
    finally:
        event.remove(
            engine,
            "before_cursor_execute",
            coordinate_verification_snapshot,
        )

    assert all(not thread.is_alive() for thread in threads)
    assert events_read.is_set()
    assert append_committed.is_set()
    assert verification_results[0].valid is True
    with auth_session_factory() as session:
        assert AuditService().verify_chain(session).valid is True
