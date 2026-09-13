from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.audit.service import (
    AuditService,
    canonical_content_hash,
    persisted_json_value,
)
from app.imports.approval import (
    CandidateDecisionConflict,
    CandidateDecisionForbidden,
    ImportCandidateApprovalService,
)
from app.imports.models import (
    ImportBatch,
    ImportCandidateDecision,
    ImportReleaseCandidate,
)
from app.users.models import UserRole
from app.users.service import UserService


PASSWORD = "Baseline decision test password 2026!"


def _candidate_scope(session):
    actor = UserService().create_user(
        session,
        username=f"baseline-admin-{uuid4().hex[:8]}",
        display_name="Baseline Admin",
        role=UserRole.ADMIN,
        initial_password=PASSWORD,
    )
    actor.must_change_password = False
    batch = ImportBatch(
        source_fingerprint=uuid4().hex + uuid4().hex,
        status="completed",
        counts={"papers": 1},
        integrity={"missing": 0},
        asset_linkage={"resolved": 1},
        completed_at=datetime.now(UTC),
    )
    session.add(batch)
    session.flush()
    candidate = ImportReleaseCandidate(
        import_batch_id=batch.id,
        status="imported_baseline",
        manifest={"revision_count": 1, "source_fingerprint": batch.source_fingerprint},
        is_current=False,
    )
    session.add(candidate)
    session.flush()
    return actor, candidate


def _decision(actor, candidate, **overrides):
    manifest = dict(candidate.manifest)
    values = {
        "decision": "approve",
        "reason": "Imported facts and asset linkage were reviewed.",
        "manifest": manifest,
        "manifest_hash": canonical_content_hash(manifest),
    }
    values.update(overrides)
    return ImportCandidateDecision(
        candidate_id=candidate.id,
        actor_id=actor.id,
        **values,
    )


def test_candidate_decision_persists_one_immutable_snapshot_per_candidate(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        actor, candidate = _candidate_scope(session)
        decision = _decision(actor, candidate)
        session.add(decision)
        session.flush()
        decision_id = decision.id

    with auth_session_factory() as session:
        stored = session.get(ImportCandidateDecision, decision_id)
        assert stored is not None
        assert stored.candidate_id == candidate.id
        assert stored.decision == "approve"
        assert stored.actor_id == actor.id
        assert stored.manifest == candidate.manifest
        assert len(stored.manifest_hash) == 64

        stored.reason = "tampered"
        with pytest.raises(RuntimeError, match="append-only"):
            session.flush()
        session.rollback()

    with auth_session_factory() as session:
        stored = session.get(ImportCandidateDecision, decision_id)
        assert stored is not None
        session.delete(stored)
        with pytest.raises(RuntimeError, match="append-only"):
            session.flush()
        session.rollback()


def test_candidate_decision_rejects_a_second_decision_for_one_candidate(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        actor, candidate = _candidate_scope(session)
        session.add(_decision(actor, candidate))

    with auth_session_factory() as session:
        actor = session.get(type(actor), actor.id)
        candidate = session.get(ImportReleaseCandidate, candidate.id)
        assert actor is not None
        assert candidate is not None
        session.add(
            _decision(
                actor,
                candidate,
                decision="reject",
                reason="A second terminal decision must not be accepted.",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


@pytest.mark.parametrize(
    ("decision_value", "manifest_hash"),
    [("publish", "a" * 64), ("approve", "short")],
)
def test_candidate_decision_validates_action_and_manifest_hash(
    auth_session_factory,
    decision_value: str,
    manifest_hash: str,
) -> None:
    with auth_session_factory() as session:
        actor, candidate = _candidate_scope(session)
        session.add(
            _decision(
                actor,
                candidate,
                decision=decision_value,
                manifest_hash=manifest_hash,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_candidate_decision_database_trigger_rejects_update_and_delete(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        actor, candidate = _candidate_scope(session)
        decision = _decision(actor, candidate)
        session.add(decision)
        session.flush()
        decision_id = decision.id

    with auth_session_factory() as session:
        with pytest.raises(DBAPIError, match="append-only"):
            session.execute(
                update(ImportCandidateDecision)
                .where(ImportCandidateDecision.id == decision_id)
                .values(reason="tampered through SQL")
            )
            session.commit()
        session.rollback()

    with auth_session_factory() as session:
        with pytest.raises(DBAPIError, match="append-only"):
            session.execute(
                delete(ImportCandidateDecision).where(
                    ImportCandidateDecision.id == decision_id
                )
            )
            session.commit()
        session.rollback()

    with auth_session_factory() as session:
        assert session.scalar(
            select(ImportCandidateDecision.reason).where(
                ImportCandidateDecision.id == decision_id
            )
        ) == "Imported facts and asset linkage were reviewed."


def test_corpus_audit_event_with_no_paper_remains_hash_chain_verifiable(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        actor, candidate = _candidate_scope(session)
        event = AuditService().append_event(
            session,
            actor_id=actor.id,
            action="import_candidate.approved",
            target_type="import_release_candidate",
            target_id=candidate.id,
            paper_id=None,
            changeset_id=None,
            release_id=None,
            ip_address="192.0.2.10",
            request_id="candidate-decision-request",
            result="success",
            reason="Baseline candidate reviewed",
            before_hash=canonical_content_hash({"status": "imported_baseline"}),
            after_hash=canonical_content_hash({"status": "approved"}),
            details={"candidate_id": str(candidate.id)},
        )

        assert event.paper_id is None
        assert AuditService().verify_chain(session).valid is True


def test_service_approve_normalizes_manifest_and_changes_candidate_status(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        actor, candidate = _candidate_scope(session)
        candidate.manifest = {
            "revision_count": 1,
            "numeric": {"negative_zero": -0.0, "exponent": 1e20},
        }
        expected_manifest = persisted_json_value(session, candidate.manifest)
        result = ImportCandidateApprovalService().decide(
            session,
            candidate_id=candidate.id,
            actor_id=actor.id,
            action="approve",
            reason="  Imported facts and asset linkage were reviewed.  ",
        )

        assert result.idempotent is False
        assert result.decision.manifest == expected_manifest
        assert result.decision.manifest_hash == canonical_content_hash(
            expected_manifest
        )
        assert result.decision.reason == (
            "Imported facts and asset linkage were reviewed."
        )
        assert candidate.status == "approved"


def test_service_reject_changes_candidate_to_terminal_rejected_state(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        actor, candidate = _candidate_scope(session)
        result = ImportCandidateApprovalService().decide(
            session,
            candidate_id=candidate.id,
            actor_id=actor.id,
            action="reject",
            reason="The imported integrity summary requires a corrected import.",
        )

        assert result.decision.decision == "reject"
        assert candidate.status == "rejected"


@pytest.mark.parametrize("role", [UserRole.VISITOR, UserRole.REVIEWER])
def test_service_forbids_non_admin_candidate_decisions(
    auth_session_factory,
    role: UserRole,
) -> None:
    with auth_session_factory.begin() as session:
        _, candidate = _candidate_scope(session)
        actor = UserService().create_user(
            session,
            username=f"baseline-{role.value}-{uuid4().hex[:8]}",
            display_name="Unauthorized actor",
            role=role,
            initial_password=PASSWORD,
        )
        actor.must_change_password = False

        with pytest.raises(
            CandidateDecisionForbidden,
            match="enabled Admin",
        ):
            ImportCandidateApprovalService().decide(
                session,
                candidate_id=candidate.id,
                actor_id=actor.id,
                action="approve",
                reason="This actor must not decide.",
            )


def test_service_forbids_disabled_admin_candidate_decision(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        actor, candidate = _candidate_scope(session)
        actor.is_enabled = False

        with pytest.raises(CandidateDecisionForbidden, match="enabled Admin"):
            ImportCandidateApprovalService().decide(
                session,
                candidate_id=candidate.id,
                actor_id=actor.id,
                action="approve",
                reason="A disabled Admin must not decide.",
            )


@pytest.mark.parametrize(
    ("candidate_status", "batch_status", "has_completed_at"),
    [
        ("approved", "completed", True),
        ("imported_baseline", "staging", False),
        ("imported_baseline", "completed", False),
    ],
)
def test_service_requires_pending_candidate_from_completed_import(
    auth_session_factory,
    candidate_status: str,
    batch_status: str,
    has_completed_at: bool,
) -> None:
    with auth_session_factory.begin() as session:
        actor, candidate = _candidate_scope(session)
        batch = session.get(ImportBatch, candidate.import_batch_id)
        assert batch is not None
        candidate.status = candidate_status
        batch.status = batch_status
        batch.completed_at = datetime.now(UTC) if has_completed_at else None

        with pytest.raises(CandidateDecisionConflict):
            ImportCandidateApprovalService().decide(
                session,
                candidate_id=candidate.id,
                actor_id=actor.id,
                action="approve",
                reason="Only a completed pending import can be approved.",
            )


@pytest.mark.parametrize("reason", ["", "   ", "x" * 4001])
def test_service_validates_candidate_decision_reason(
    auth_session_factory,
    reason: str,
) -> None:
    with auth_session_factory.begin() as session:
        actor, candidate = _candidate_scope(session)

        with pytest.raises(ValueError, match="reason"):
            ImportCandidateApprovalService().decide(
                session,
                candidate_id=candidate.id,
                actor_id=actor.id,
                action="approve",
                reason=reason,
            )


def test_service_exact_retry_returns_original_candidate_decision(
    auth_session_factory,
) -> None:
    reason = "Imported facts and asset linkage were reviewed."
    with auth_session_factory.begin() as session:
        actor, candidate = _candidate_scope(session)
        first = ImportCandidateApprovalService().decide(
            session,
            candidate_id=candidate.id,
            actor_id=actor.id,
            action="approve",
            reason=reason,
        )
        retried = ImportCandidateApprovalService().decide(
            session,
            candidate_id=candidate.id,
            actor_id=actor.id,
            action="approve",
            reason=reason,
        )

        assert retried.idempotent is True
        assert retried.decision.id == first.decision.id
        assert session.scalar(
            select(func.count()).select_from(ImportCandidateDecision)
        ) == 1


@pytest.mark.parametrize(
    "difference",
    ["actor", "action", "reason", "manifest"],
)
def test_service_conflicting_retry_is_rejected(
    auth_session_factory,
    difference: str,
) -> None:
    original_reason = "Imported facts and asset linkage were reviewed."
    with auth_session_factory.begin() as session:
        actor, candidate = _candidate_scope(session)
        ImportCandidateApprovalService().decide(
            session,
            candidate_id=candidate.id,
            actor_id=actor.id,
            action="approve",
            reason=original_reason,
        )
        retry_actor_id: UUID = actor.id
        retry_action = "approve"
        retry_reason = original_reason
        if difference == "actor":
            retry_actor = UserService().create_user(
                session,
                username=f"second-baseline-admin-{uuid4().hex[:8]}",
                display_name="Second Baseline Admin",
                role=UserRole.ADMIN,
                initial_password=PASSWORD,
            )
            retry_actor.must_change_password = False
            retry_actor_id = retry_actor.id
        elif difference == "action":
            retry_action = "reject"
        elif difference == "reason":
            retry_reason = "The reason differs from the persisted decision."
        else:
            candidate.manifest = {**candidate.manifest, "revision_count": 2}

        with pytest.raises(CandidateDecisionConflict, match="conflict"):
            ImportCandidateApprovalService().decide(
                session,
                candidate_id=candidate.id,
                actor_id=retry_actor_id,
                action=retry_action,
                reason=retry_reason,
            )
