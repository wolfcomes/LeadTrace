from __future__ import annotations

from pydantic import ValidationError
import pytest
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from app.papers.models import Paper
from app.releases.models import Release, ReleaseItem
from app.revisions.models import ObjectKind
from app.revisions.service import RevisionService
from app.reviews.attestations import (
    AttestationValidationError,
    PaperAttestationRequest,
    PaperReviewScopeService,
)
from app.reviews.models import PaperReviewAttestation
from app.reviews.service import InvalidReview, ReviewForbidden, ReviewService
from app.security.policies import WorkflowState
from app.users.models import UserRole
from app.users.service import UserService


def test_attestation_requires_literal_confirmation_and_scope_hash() -> None:
    with pytest.raises(ValidationError):
        PaperAttestationRequest(
            expected_version=1,
            scope_hash="not-a-hash",
            statement="I checked this Paper",
            confirmed=False,
        )


def _seed_review(session):
    users = UserService()
    reviewer = users.create_user(session, username=f"attest-reviewer-{uuid4().hex[:8]}", display_name="Reviewer", role=UserRole.REVIEWER, initial_password="Attestation password 2026!")
    reviewer.must_change_password = False
    admin = users.create_user(session, username=f"attest-admin-{uuid4().hex[:8]}", display_name="Admin", role=UserRole.ADMIN, initial_password="Attestation password 2026!")
    admin.must_change_password = False
    paper = Paper(paper_key=f"attest-paper-{uuid4().hex[:8]}")
    session.add(paper)
    session.flush()
    release = Release(release_key=f"attest-release-{uuid4().hex[:8]}", title="Attestation base", notes="", metrics={}, published_by_id=admin.id, published_at=datetime.now(UTC), is_current=True, manifest_finalized=False)
    session.add(release)
    session.flush()
    paper_revision = RevisionService().create_revision(session, object_identity=paper, actor_id=admin.id, reason="Published base", snapshot={"paper_key": paper.paper_key}, workflow_state=WorkflowState.PUBLISHED, is_current_published=True)
    session.add(ReleaseItem(release_id=release.id, object_id=paper.id, revision_id=paper_revision.id, paper_id=paper.id, object_kind=ObjectKind.PAPER, manifest_order=1))
    session.flush()
    release.manifest_finalized = True
    service = ReviewService()
    task = service.create_task(session, paper_id=paper.id, assignee_id=reviewer.id, created_by_id=admin.id)
    changeset = service.create_changeset(session, paper_id=paper.id, actor_id=reviewer.id, review_task_id=task.id, base_release_id=release.id, title="Review Paper", reason="Full scientific review")
    return reviewer, admin, changeset, paper, paper_revision


def test_scope_is_immutable_and_attestation_becomes_stale_after_mutation(auth_session_factory) -> None:
    with auth_session_factory.begin() as session:
        reviewer, _, changeset, paper, paper_revision = _seed_review(session)
        scope = PaperReviewScopeService.ensure_scope(session, changeset=changeset, actor_id=reviewer.id)
        assert PaperReviewScopeService.ensure_scope(session, changeset=changeset, actor_id=reviewer.id).id == scope.id
        _, attestation, progress = PaperReviewScopeService.attest(session, changeset=changeset, actor_id=reviewer.id, expected_version=1, scope_hash=scope.scope_hash, statement="I reviewed the complete frozen Paper scope.")
        assert progress.item_count == progress.resolved_count == 1
        assert attestation.changeset_version == changeset.version == 2
        ReviewService().update_changeset(session, changeset_id=changeset.id, actor_id=reviewer.id, expected_version=2, title="Mutated after attestation")
        assert changeset.version == 3
        assert session.scalar(select(PaperReviewAttestation).where(PaperReviewAttestation.id == attestation.id)).changeset_version == 2


def test_scoped_changeset_requires_current_attestation_to_submit(auth_session_factory) -> None:
    with auth_session_factory.begin() as session:
        reviewer, _, changeset, paper, paper_revision = _seed_review(session)
        ReviewService().add_changeset_item(
            session,
            changeset_id=changeset.id,
            actor_id=reviewer.id,
            expected_version=changeset.version,
            object_id=paper.id,
            object_kind=ObjectKind.PAPER.value,
            base_revision_id=paper_revision.id,
            proposed_snapshot=paper_revision.snapshot,
        )
        scope = PaperReviewScopeService.ensure_scope(session, changeset=changeset, actor_id=reviewer.id)
        with pytest.raises(InvalidReview, match="attestation"):
            ReviewService().submit_changeset(session, changeset_id=changeset.id, actor_id=reviewer.id, expected_version=2)
        _, attestation, _ = PaperReviewScopeService.attest(session, changeset=changeset, actor_id=reviewer.id, expected_version=2, scope_hash=scope.scope_hash, statement="I reviewed the complete frozen Paper scope.")
        submitted = ReviewService().submit_changeset(session, changeset_id=changeset.id, actor_id=reviewer.id, expected_version=3)
        assert submitted.workflow_state is WorkflowState.SUBMITTED
        assert submitted.submitted_snapshot["validation_results"]["paper_attestation"]["id"] == str(attestation.id)


def test_frozen_scope_makes_paper_review_status_server_owned(auth_session_factory) -> None:
    with auth_session_factory.begin() as session:
        reviewer, _, changeset, paper, paper_revision = _seed_review(session)
        PaperReviewScopeService.ensure_scope(session, changeset=changeset, actor_id=reviewer.id)
        with pytest.raises(InvalidReview, match="attestation endpoint"):
            ReviewService().add_changeset_item(
                session,
                changeset_id=changeset.id,
                actor_id=reviewer.id,
                expected_version=1,
                object_id=paper.id,
                object_kind=ObjectKind.PAPER.value,
                base_revision_id=paper_revision.id,
                proposed_snapshot={"paper_key": paper.paper_key, "review_status": "reviewed"},
            )


def test_only_assigned_enabled_reviewer_can_attest(auth_session_factory) -> None:
    with auth_session_factory.begin() as session:
        reviewer, admin, changeset, _, _ = _seed_review(session)
        scope = PaperReviewScopeService.ensure_scope(
            session,
            changeset=changeset,
            actor_id=reviewer.id,
        )

        with pytest.raises(ReviewForbidden, match="assigned Reviewer"):
            PaperReviewScopeService.attest(
                session,
                changeset=changeset,
                actor_id=admin.id,
                expected_version=1,
                scope_hash=scope.scope_hash,
                statement="An Admin must not sign the Reviewer attestation.",
            )
