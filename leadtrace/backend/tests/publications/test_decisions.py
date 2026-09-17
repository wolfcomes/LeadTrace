from __future__ import annotations

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.assets.models import Asset, AssetIntegrityState
from app.catalog.models import PaperSource, PaperSourceIntegrityState
from app.papers.models import Paper
from app.publications.models import (
    AdminDecision,
    AdminDecisionAction,
    PublishedPaperVersion,
)
from app.publications.service import (
    DecisionForbiddenError,
    DecisionHashMismatchError,
    DecisionReasonRequiredError,
    DecisionStateConflictError,
    PublicationService,
)
from app.users.models import User
from app.workspaces.models import (
    PaperSection,
    PaperSectionReview,
    PaperSectionState,
    PaperSubmission,
    PaperWorkspace,
    ReviewTask,
    ReviewTaskState,
    WorkspaceState,
)
from app.workspaces.submission import SubmissionService


def test_request_changes_preserves_submission_and_allows_resubmission(
    publication_fixture,
):
    fixture = publication_fixture
    first = fixture.submit()
    service = PublicationService()

    with fixture.session_factory.begin() as session:
        admin = session.get(User, fixture.admin_id)
        reviewer = session.get(User, fixture.reviewer_id)
        assert admin is not None and reviewer is not None
        with pytest.raises(DecisionForbiddenError):
            service.decide(
                session,
                submission_id=first.id,
                content_hash=first.content_hash,
                action=AdminDecisionAction.REQUEST_CHANGES,
                reason="Reviewer cannot decide",
                idempotency_key="reviewer-decision",
                actor=reviewer,
            )
        with pytest.raises(DecisionHashMismatchError):
            service.decide(
                session,
                submission_id=first.id,
                content_hash="0" * 64,
                action=AdminDecisionAction.REQUEST_CHANGES,
                reason="Wrong hash",
                idempotency_key="wrong-hash",
                actor=admin,
            )
        with pytest.raises(DecisionReasonRequiredError):
            service.decide(
                session,
                submission_id=first.id,
                content_hash=first.content_hash,
                action=AdminDecisionAction.REQUEST_CHANGES,
                reason="  ",
                idempotency_key="missing-reason",
                actor=admin,
            )

        result = service.decide(
            session,
            submission_id=first.id,
            content_hash=first.content_hash,
            action=AdminDecisionAction.REQUEST_CHANGES,
            reason="Please clarify the lineage.",
            idempotency_key="request-changes-1",
            actor=admin,
        )
        workspace = session.get(PaperWorkspace, fixture.workspace_id)
        task = session.get(ReviewTask, fixture.task_id)
        assert result.published_version is None
        assert workspace is not None and workspace.state is WorkspaceState.EDITING
        assert task is not None and task.status is ReviewTaskState.CHANGES_REQUESTED
        returned_version = workspace.version

        replay = service.decide(
            session,
            submission_id=first.id,
            content_hash=first.content_hash,
            action=AdminDecisionAction.REQUEST_CHANGES,
            reason="Please clarify the lineage.",
            idempotency_key="request-changes-1",
            actor=admin,
        )
        assert replay.decision.id == result.decision.id
        assert workspace.version == returned_version

    with fixture.session_factory.begin() as session:
        workspace = session.get(PaperWorkspace, fixture.workspace_id)
        assert workspace is not None
        second = SubmissionService().submit(
            session,
            workspace_id=fixture.workspace_id,
            reviewer_id=fixture.reviewer_id,
            expected_workspace_version=workspace.version,
            idempotency_key="submission-2",
            reviewer_note="Resubmitted",
        )
        assert second.submission_number == 2
        assert session.get(PaperSubmission, first.id).content_hash == first.content_hash
        assert session.scalar(select(func.count()).select_from(PaperSubmission)) == 2


def test_approve_publishes_exact_snapshot_and_is_idempotent(publication_fixture):
    fixture = publication_fixture
    submission = fixture.submit()
    service = PublicationService()
    with fixture.session_factory.begin() as session:
        admin = session.get(User, fixture.admin_id)
        assert admin is not None
        result = service.decide(
            session,
            submission_id=submission.id,
            content_hash=submission.content_hash,
            action=AdminDecisionAction.APPROVE,
            reason="Scientific review complete.",
            idempotency_key="approve-1",
            actor=admin,
        )
        assert result.published_version is not None
        assert result.published_version.version_number == 1
        assert result.published_version.snapshot == submission.snapshot
        assert result.published_version.content_hash == submission.content_hash
        paper = session.get(Paper, fixture.paper_id)
        workspace = session.get(PaperWorkspace, fixture.workspace_id)
        task = session.get(ReviewTask, fixture.task_id)
        assert paper is not None
        assert paper.current_published_version_id == result.published_version.id
        assert workspace is not None and workspace.state is WorkspaceState.APPROVED
        assert task is not None and task.status is ReviewTaskState.APPROVED

        replay = service.decide(
            session,
            submission_id=submission.id,
            content_hash=submission.content_hash,
            action=AdminDecisionAction.APPROVE,
            reason="Scientific review complete.",
            idempotency_key="approve-1",
            actor=admin,
        )
        assert replay.decision.id == result.decision.id
        assert replay.published_version is not None
        assert replay.published_version.id == result.published_version.id
        assert session.scalar(select(func.count()).select_from(AdminDecision)) == 1
        assert session.scalar(select(func.count()).select_from(PublishedPaperVersion)) == 1


@pytest.mark.parametrize("invalid_part", ["paper", "source", "asset"])
def test_approval_rejects_source_that_became_unverified(
    publication_fixture,
    invalid_part,
):
    fixture = publication_fixture
    submission = fixture.submit()
    with fixture.session_factory.begin() as session:
        paper = session.get(Paper, fixture.paper_id)
        assert paper is not None
        source = session.get(PaperSource, paper.source_id)
        assert source is not None
        asset = session.get(Asset, source.asset_id)
        assert asset is not None
        if invalid_part == "paper":
            paper.catalog_state = "source_error"
        elif invalid_part == "source":
            source.integrity_state = PaperSourceIntegrityState.MISSING
        else:
            asset.integrity_state = AssetIntegrityState.CORRUPT

    with fixture.session_factory.begin() as session:
        admin = session.get(User, fixture.admin_id)
        assert admin is not None
        with pytest.raises(DecisionStateConflictError):
            PublicationService().decide(
                session,
                submission_id=submission.id,
                content_hash=submission.content_hash,
                action=AdminDecisionAction.APPROVE,
                reason="Must not publish an unverified source.",
                idempotency_key=f"invalid-source-{invalid_part}",
                actor=admin,
            )


def test_later_approval_preserves_version_one_and_moves_current_pointer(
    publication_fixture,
):
    fixture = publication_fixture
    first_submission = fixture.submit()
    service = PublicationService()
    with fixture.session_factory.begin() as session:
        admin = session.get(User, fixture.admin_id)
        assert admin is not None
        first_result = service.decide(
            session,
            submission_id=first_submission.id,
            content_hash=first_submission.content_hash,
            action=AdminDecisionAction.APPROVE,
            reason="Approve version one.",
            idempotency_key="approve-version-one",
            actor=admin,
        )
        assert first_result.published_version is not None
        first_version_id = first_result.published_version.id
        first_snapshot = first_result.published_version.snapshot

        second_task = ReviewTask(
            paper_id=fixture.paper_id,
            assigned_reviewer_id=fixture.reviewer_id,
            created_by_id=fixture.admin_id,
            status=ReviewTaskState.ASSIGNED,
            version=1,
        )
        session.add(second_task)
        session.flush()
        second_workspace = PaperWorkspace(
            paper_id=fixture.paper_id,
            review_task_id=second_task.id,
            state=WorkspaceState.EDITING,
            version=1,
        )
        session.add(second_workspace)
        session.flush()
        session.add_all(
            [
                PaperSectionReview(
                    paper_id=fixture.paper_id,
                    workspace_id=second_workspace.id,
                    section_key=section,
                    state=PaperSectionState.NOT_REPORTED,
                    note=None,
                )
                for section in PaperSection
            ]
        )
        session.flush()
        second_submission = SubmissionService().submit(
            session,
            workspace_id=second_workspace.id,
            reviewer_id=fixture.reviewer_id,
            expected_workspace_version=1,
            idempotency_key="second-workspace-submission",
            reviewer_note="Publish version two.",
        )
        second_result = service.decide(
            session,
            submission_id=second_submission.id,
            content_hash=second_submission.content_hash,
            action=AdminDecisionAction.APPROVE,
            reason="Approve version two.",
            idempotency_key="approve-version-two",
            actor=admin,
        )
        assert second_result.published_version is not None
        assert second_result.published_version.version_number == 2
        paper = session.get(Paper, fixture.paper_id)
        assert paper is not None
        assert paper.current_published_version_id == second_result.published_version.id
        first_version = session.get(PublishedPaperVersion, first_version_id)
        assert first_version is not None
        assert first_version.version_number == 1
        assert first_version.snapshot == first_snapshot

    fixture.login("publication.visitor")
    detail = fixture.client.get(f"/api/v2/papers/{fixture.paper_id}")
    assert detail.status_code == 200
    assert detail.json()["version_number"] == 2
    assert detail.json()["content_hash"] == second_submission.content_hash


def test_decisions_and_published_versions_are_database_immutable(publication_fixture):
    fixture = publication_fixture
    submission = fixture.submit()
    with fixture.session_factory.begin() as session:
        admin = session.get(User, fixture.admin_id)
        assert admin is not None
        result = PublicationService().decide(
            session,
            submission_id=submission.id,
            content_hash=submission.content_hash,
            action=AdminDecisionAction.APPROVE,
            reason="Approved.",
            idempotency_key="immutable-approval",
            actor=admin,
        )
        assert result.published_version is not None
        decision_id = result.decision.id
        version_id = result.published_version.id

    for table_name, row_id in (
        ("admin_decisions", decision_id),
        ("published_paper_versions", version_id),
    ):
        with pytest.raises(DBAPIError) as update_error:
            with fixture.session_factory.begin() as session:
                session.execute(
                    text(f"UPDATE {table_name} SET content_hash = :hash WHERE id = :id"),
                    {"hash": "0" * 64, "id": row_id},
                )
        assert getattr(update_error.value.orig, "sqlstate", None) == "55000"
        with pytest.raises(DBAPIError) as delete_error:
            with fixture.session_factory.begin() as session:
                session.execute(
                    text(f"DELETE FROM {table_name} WHERE id = :id"),
                    {"id": row_id},
                )
        assert getattr(delete_error.value.orig, "sqlstate", None) == "55000"
