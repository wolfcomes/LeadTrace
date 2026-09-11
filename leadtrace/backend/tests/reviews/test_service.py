from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text, update
from sqlalchemy.engine import make_url

from app.compounds.models import Compound
from app.papers.models import Paper
from app.releases.models import Release, ReleaseItem
from app.revisions.models import ObjectKind, ObjectRevision
from app.revisions.service import RevisionService
from app.reviews.models import ChangesetSubmission, ReviewTaskStatus
from app.reviews.service import (
    BaseReleaseConflict,
    InvalidReview,
    RevisionConflict,
    ReviewForbidden,
    ReviewNotFound,
    ReviewService,
    ReviewStateConflict,
)
from app.security.policies import WorkflowState
from app.users.models import UserRole
from app.users.service import UserService


PASSWORD = "Review workflow test password 2026!"


def _setup(session):
    users = UserService()
    reviewer = users.create_user(
        session,
        username=f"reviewer-{uuid4().hex[:8]}",
        display_name="Reviewer",
        role=UserRole.REVIEWER,
        initial_password=PASSWORD,
    )
    reviewer.must_change_password = False
    other = users.create_user(
        session,
        username=f"other-{uuid4().hex[:8]}",
        display_name="Other",
        role=UserRole.REVIEWER,
        initial_password=PASSWORD,
    )
    other.must_change_password = False
    admin = users.create_user(
        session,
        username=f"admin-{uuid4().hex[:8]}",
        display_name="Admin",
        role=UserRole.ADMIN,
        initial_password=PASSWORD,
    )
    admin.must_change_password = False
    paper = Paper(paper_key=f"review-paper-{uuid4().hex[:8]}", doi=None)
    session.add(paper)
    session.flush()
    release = Release(
        release_key=f"review-release-{uuid4().hex[:8]}",
        title="Review release",
        notes="",
        metrics={},
        published_by_id=admin.id,
        published_at=datetime.now(UTC),
        is_current=True,
        manifest_finalized=False,
    )
    session.add(release)
    session.flush()
    paper_revision = RevisionService().create_revision(
        session,
        object_identity=paper,
        actor_id=admin.id,
        reason="Published review base",
        snapshot={"paper_key": paper.paper_key},
        workflow_state=WorkflowState.PUBLISHED,
        is_current_published=True,
    )
    session.add(
        ReleaseItem(
            release_id=release.id,
            object_id=paper.id,
            revision_id=paper_revision.id,
            paper_id=paper.id,
            object_kind=ObjectKind.PAPER,
            manifest_order=1,
        )
    )
    session.flush()
    release.manifest_finalized = True
    session.flush()
    return reviewer, other, admin, paper, paper_revision, release


def _add_paper_item(session, service, changeset, reviewer, paper, paper_revision):
    return service.add_changeset_item(
        session,
        changeset_id=changeset.id,
        actor_id=reviewer.id,
        expected_version=changeset.version,
        object_id=paper.id,
        object_kind=ObjectKind.PAPER.value,
        base_revision_id=paper_revision.id,
        proposed_snapshot={"paper_key": paper.paper_key, "reviewed": True},
    )


def test_reviewer_can_create_and_submit_owned_changeset(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        reviewer, _, admin, paper, paper_revision, release = _setup(session)
        service = ReviewService()
        task = service.create_task(
            session,
            paper_id=paper.id,
            assignee_id=reviewer.id,
            created_by_id=admin.id,
        )
        changeset = service.create_changeset(
            session,
            paper_id=paper.id,
            actor_id=reviewer.id,
            review_task_id=task.id,
            base_release_id=release.id,
            title="Correct relation",
            reason="Source text confirms the direct parent",
        )
        _add_paper_item(
            session, service, changeset, reviewer, paper, paper_revision
        )
        service.submit_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=reviewer.id,
            expected_version=2,
        )
        session.refresh(changeset)
        session.refresh(task)
        assert changeset.workflow_state is WorkflowState.SUBMITTED
        assert task.status.value == "submitted"
        assert changeset.version == 3


def test_reviewer_cannot_submit_another_reviewers_changeset(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        reviewer, other, admin, paper, paper_revision, release = _setup(session)
        service = ReviewService()
        task = service.create_task(
            session,
            paper_id=paper.id,
            assignee_id=reviewer.id,
            created_by_id=admin.id,
        )
        changeset = service.create_changeset(
            session,
            paper_id=paper.id,
            actor_id=reviewer.id,
            review_task_id=task.id,
            base_release_id=release.id,
            title="Private draft",
            reason="Needs review",
        )
        _add_paper_item(
            session, service, changeset, reviewer, paper, paper_revision
        )
        with pytest.raises(ReviewNotFound):
            service.submit_changeset(
                session,
                changeset_id=changeset.id,
                actor_id=other.id,
                expected_version=changeset.version,
            )


def test_stale_changeset_update_returns_expected_and_current_versions(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        reviewer, _, admin, paper, _, release = _setup(session)
        service = ReviewService()
        task = service.create_task(
            session,
            paper_id=paper.id,
            assignee_id=reviewer.id,
            created_by_id=admin.id,
        )
        changeset = service.create_changeset(
            session,
            paper_id=paper.id,
            actor_id=reviewer.id,
            review_task_id=task.id,
            base_release_id=release.id,
            title="Initial",
            reason="Initial reason",
        )
        service.update_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=reviewer.id,
            expected_version=1,
            title="Updated once",
        )
        with pytest.raises(RevisionConflict) as error:
            service.update_changeset(
                session,
                changeset_id=changeset.id,
                actor_id=reviewer.id,
                expected_version=1,
                title="Stale overwrite",
            )
        assert error.value.expected_version == 1
        assert error.value.current_version == 2


def test_changeset_is_scoped_to_one_paper_and_task_assignment_is_explicit(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        reviewer, _, admin, paper, _, release = _setup(session)
        service = ReviewService()
        task = service.create_task(
            session,
            paper_id=paper.id,
            assignee_id=reviewer.id,
            created_by_id=admin.id,
        )
        changeset = service.create_changeset(
            session,
            paper_id=paper.id,
            actor_id=reviewer.id,
            review_task_id=task.id,
            base_release_id=release.id,
            title="Scoped",
            reason="One paper only",
        )
        assert changeset.paper_id == paper.id
        assert changeset.review_task_id == task.id
        assert service.list_tasks(session, reviewer.id)[0].paper_id == paper.id


def test_unassigned_reviewer_cannot_create_changeset(auth_session_factory) -> None:
    with auth_session_factory.begin() as session:
        reviewer, other, admin, paper, _, release = _setup(session)
        task = ReviewService().create_task(
            session,
            paper_id=paper.id,
            assignee_id=other.id,
            created_by_id=admin.id,
        )
        with pytest.raises(ReviewForbidden):
            ReviewService().create_changeset(
                session,
                paper_id=paper.id,
                actor_id=reviewer.id,
                review_task_id=task.id,
                base_release_id=release.id,
                title="Out of scope",
                reason="No assignment",
            )


def test_resubmission_keeps_every_immutable_submitted_snapshot(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        reviewer, _, admin, paper, paper_revision, release = _setup(session)
        service = ReviewService()
        task = service.create_task(
            session,
            paper_id=paper.id,
            assignee_id=reviewer.id,
            created_by_id=admin.id,
        )
        changeset = service.create_changeset(
            session,
            paper_id=paper.id,
            actor_id=reviewer.id,
            review_task_id=task.id,
            base_release_id=release.id,
            title="First submission",
            reason="Initial review",
        )
        _add_paper_item(
            session, service, changeset, reviewer, paper, paper_revision
        )
        service.submit_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=reviewer.id,
            expected_version=2,
        )
        service.transition_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=admin.id,
            expected_version=3,
            next_state=WorkflowState.CHANGES_REQUESTED,
        )
        service.revise_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=reviewer.id,
            expected_version=4,
        )
        service.update_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=reviewer.id,
            expected_version=5,
            title="Second submission",
        )
        service.submit_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=reviewer.id,
            expected_version=6,
        )
        submissions = list(
            session.scalars(
                select(ChangesetSubmission)
                .where(ChangesetSubmission.changeset_id == changeset.id)
                .order_by(ChangesetSubmission.submission_number)
            )
        )

        assert [item.snapshot["title"] for item in submissions] == [
            "First submission",
            "Second submission",
        ]
        assert [item.changeset_version for item in submissions] == [3, 7]
        assert task.status is ReviewTaskStatus.SUBMITTED


def test_revised_item_creates_new_revision_and_can_be_resubmitted(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        reviewer, _, admin, paper, paper_revision, release = _setup(session)
        service = ReviewService()
        task = service.create_task(
            session,
            paper_id=paper.id,
            assignee_id=reviewer.id,
            created_by_id=admin.id,
        )
        changeset = service.create_changeset(
            session,
            paper_id=paper.id,
            actor_id=reviewer.id,
            review_task_id=task.id,
            base_release_id=release.id,
            title="Correct reviewed item",
            reason="A returned item needs a new immutable revision",
        )
        item = _add_paper_item(
            session, service, changeset, reviewer, paper, paper_revision
        )
        first_revision = RevisionService().create_revision(
            session,
            object_identity=paper,
            actor_id=reviewer.id,
            reason="First reviewed content",
            snapshot=item.proposed_snapshot,
            predecessor=paper_revision,
            changeset_id=changeset.id,
        )
        service.submit_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=reviewer.id,
            expected_version=2,
        )
        service.transition_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=admin.id,
            expected_version=3,
            next_state=WorkflowState.CHANGES_REQUESTED,
        )
        service.revise_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=reviewer.id,
            expected_version=4,
        )
        second_snapshot = {"paper_key": paper.paper_key, "reviewed": "corrected"}
        unbound_revision = RevisionService().create_revision(
            session,
            object_identity=paper,
            actor_id=reviewer.id,
            reason="Unbound competing revision",
            snapshot=second_snapshot,
            predecessor=first_revision,
            changeset_id=changeset.id,
            workflow_state=WorkflowState.REVISED_DRAFT,
        )
        changeset, item = service.update_changeset_item(
            session,
            changeset_id=changeset.id,
            item_id=item.id,
            actor_id=reviewer.id,
            expected_version=5,
            proposed_snapshot=second_snapshot,
        )
        second_revision = session.get(ObjectRevision, item.proposed_revision_id)
        assert second_revision is not None
        assert second_revision.id not in {first_revision.id, unbound_revision.id}
        assert second_revision.predecessor_id == first_revision.id
        assert second_revision.snapshot == second_snapshot

        service.submit_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=reviewer.id,
            expected_version=6,
        )
        submissions = list(
            session.scalars(
                select(ChangesetSubmission)
                .where(ChangesetSubmission.changeset_id == changeset.id)
                .order_by(ChangesetSubmission.submission_number)
            )
        )
        assert [
            submission.snapshot["items"][0]["proposed_revision_id"]
            for submission in submissions
        ] == [str(first_revision.id), str(second_revision.id)]


def test_long_changeset_reason_is_preserved_when_submission_creates_revision(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        reviewer, _, admin, paper, paper_revision, release = _setup(session)
        service = ReviewService()
        task = service.create_task(
            session,
            paper_id=paper.id,
            assignee_id=reviewer.id,
            created_by_id=admin.id,
        )
        long_reason = "r" * 4000
        changeset = service.create_changeset(
            session,
            paper_id=paper.id,
            actor_id=reviewer.id,
            review_task_id=task.id,
            base_release_id=release.id,
            title="Long review rationale",
            reason=long_reason,
        )
        item = _add_paper_item(
            session, service, changeset, reviewer, paper, paper_revision
        )

        submitted = service.submit_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=reviewer.id,
            expected_version=2,
        )

        session.refresh(item)
        revision = session.get(ObjectRevision, item.proposed_revision_id)
        assert revision is not None
        assert submitted.reason == long_reason
        assert submitted.submitted_snapshot is not None
        assert submitted.submitted_snapshot["reason"] == long_reason
        assert len(revision.reason) <= 500


def test_only_admin_can_approve_and_reassign(auth_session_factory) -> None:
    with auth_session_factory.begin() as session:
        reviewer, other, admin, paper, paper_revision, release = _setup(session)
        service = ReviewService()
        task = service.create_task(
            session,
            paper_id=paper.id,
            assignee_id=reviewer.id,
            created_by_id=admin.id,
        )
        with pytest.raises(ReviewForbidden):
            service.reassign_task(
                session,
                task_id=task.id,
                actor_id=reviewer.id,
                assignee_id=other.id,
                expected_version=1,
            )
        reassigned = service.reassign_task(
            session,
            task_id=task.id,
            actor_id=admin.id,
            assignee_id=other.id,
            expected_version=1,
        )
        changeset = service.create_changeset(
            session,
            paper_id=paper.id,
            actor_id=other.id,
            review_task_id=task.id,
            base_release_id=release.id,
            title="Admin review",
            reason="Approval boundary",
        )
        _add_paper_item(session, service, changeset, other, paper, paper_revision)
        service.submit_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=other.id,
            expected_version=2,
        )

        with pytest.raises(ReviewForbidden):
            service.transition_changeset(
                session,
                changeset_id=changeset.id,
                actor_id=other.id,
                expected_version=3,
                next_state=WorkflowState.APPROVED,
            )
        service.transition_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=admin.id,
            expected_version=3,
            next_state=WorkflowState.APPROVED,
        )

        assert reassigned.assigned_reviewer_id == other.id
        assert reassigned.status is ReviewTaskStatus.COMPLETED


def test_one_review_task_cannot_back_multiple_changesets(auth_session_factory) -> None:
    with auth_session_factory.begin() as session:
        reviewer, _, admin, paper, _, release = _setup(session)
        service = ReviewService()
        task = service.create_task(
            session,
            paper_id=paper.id,
            assignee_id=reviewer.id,
            created_by_id=admin.id,
        )
        service.create_changeset(
            session,
            review_task_id=task.id,
            paper_id=paper.id,
            actor_id=reviewer.id,
            base_release_id=release.id,
            title="First task changeset",
            reason="One task, one changeset",
        )

        with pytest.raises(ReviewStateConflict):
            service.create_changeset(
                session,
                review_task_id=task.id,
                paper_id=paper.id,
                actor_id=reviewer.id,
                base_release_id=release.id,
                title="Second task changeset",
                reason="Must not share task state",
            )


def test_base_revision_must_be_pinned_by_current_finalized_release(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        reviewer, _, admin, paper, _, release = _setup(session)
        service = ReviewService()
        task = service.create_task(
            session,
            paper_id=paper.id,
            assignee_id=reviewer.id,
            created_by_id=admin.id,
        )
        changeset = service.create_changeset(
            session,
            review_task_id=task.id,
            paper_id=paper.id,
            actor_id=reviewer.id,
            base_release_id=release.id,
            title="Pinned base revision",
            reason="Reject revisions outside the release manifest",
        )

        with pytest.raises(InvalidReview, match="base-release revision"):
            service.add_changeset_item(
                session,
                changeset_id=changeset.id,
                actor_id=reviewer.id,
                expected_version=1,
                object_id=paper.id,
                object_kind=ObjectKind.PAPER.value,
                base_revision_id=uuid4(),
                proposed_snapshot={"paper_key": paper.paper_key},
            )


def test_stale_base_release_blocks_submission(auth_session_factory) -> None:
    with auth_session_factory.begin() as session:
        reviewer, _, admin, paper, paper_revision, release = _setup(session)
        service = ReviewService()
        task = service.create_task(
            session,
            paper_id=paper.id,
            assignee_id=reviewer.id,
            created_by_id=admin.id,
        )
        changeset = service.create_changeset(
            session,
            review_task_id=task.id,
            paper_id=paper.id,
            actor_id=reviewer.id,
            base_release_id=release.id,
            title="Stale base",
            reason="Current release changes before submission",
        )
        _add_paper_item(
            session, service, changeset, reviewer, paper, paper_revision
        )
        release.is_current = False
        session.flush()
        replacement = Release(
            release_key=f"replacement-{uuid4().hex[:8]}",
            title="Replacement current release",
            notes="",
            metrics={},
            published_by_id=admin.id,
            published_at=datetime.now(UTC),
            is_current=True,
            manifest_finalized=True,
        )
        session.add(replacement)
        session.flush()

        with pytest.raises(BaseReleaseConflict) as error:
            service.submit_changeset(
                session,
                changeset_id=changeset.id,
                actor_id=reviewer.id,
                expected_version=2,
            )
        assert error.value.base_release_id == release.id
        assert error.value.current_release_id == replacement.id


def test_revision_cannot_reference_changeset_item_for_another_object(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        reviewer, _, admin, paper, paper_revision, release = _setup(session)
        service = ReviewService()
        task = service.create_task(
            session,
            paper_id=paper.id,
            assignee_id=reviewer.id,
            created_by_id=admin.id,
        )
        changeset = service.create_changeset(
            session,
            review_task_id=task.id,
            paper_id=paper.id,
            actor_id=reviewer.id,
            base_release_id=release.id,
            title="Paper A only",
            reason="Revision scope test",
        )
        _add_paper_item(
            session, service, changeset, reviewer, paper, paper_revision
        )
        other_paper = Paper(
            paper_key=f"other-review-paper-{uuid4().hex[:8]}",
            doi=None,
        )
        session.add(other_paper)
        session.flush()

        with pytest.raises(InvalidReview, match="one Paper"):
            service.add_changeset_item(
                session,
                changeset_id=changeset.id,
                actor_id=reviewer.id,
                expected_version=2,
                object_id=other_paper.id,
                object_kind=ObjectKind.PAPER.value,
                base_revision_id=None,
                proposed_snapshot={"paper_key": other_paper.paper_key},
            )
        with pytest.raises(ValueError, match="same revisioned object"):
            RevisionService().create_revision(
                session,
                object_identity=other_paper,
                actor_id=reviewer.id,
                reason="Must not cross Paper scope",
                snapshot={"paper_key": other_paper.paper_key},
                changeset_id=changeset.id,
            )


def test_new_object_revision_from_same_changeset_can_be_submitted(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        reviewer, _, admin, paper, _, release = _setup(session)
        service = ReviewService()
        task = service.create_task(
            session,
            paper_id=paper.id,
            assignee_id=reviewer.id,
            created_by_id=admin.id,
        )
        changeset = service.create_changeset(
            session,
            review_task_id=task.id,
            paper_id=paper.id,
            actor_id=reviewer.id,
            base_release_id=release.id,
            title="Add new compound",
            reason="The source contains a previously unregistered compound",
        )
        compound = Compound(
            paper_id=paper.id,
            local_identity="NEW-1",
            display_label="NEW-1",
            normalized_label="NEW-1",
        )
        session.add(compound)
        session.flush()
        service.add_changeset_item(
            session,
            changeset_id=changeset.id,
            actor_id=reviewer.id,
            expected_version=1,
            object_id=compound.id,
            object_kind=ObjectKind.COMPOUND.value,
            base_revision_id=None,
            proposed_snapshot={"display_label": "NEW-1"},
        )
        RevisionService().create_revision(
            session,
            object_identity=compound,
            actor_id=reviewer.id,
            reason="Create compound in review",
            snapshot={"display_label": "NEW-1"},
            changeset_id=changeset.id,
        )

        submitted = service.submit_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=reviewer.id,
            expected_version=2,
        )

        assert submitted.workflow_state is WorkflowState.SUBMITTED


def test_revision_service_rejects_new_revision_after_changeset_submission(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        reviewer, _, admin, paper, paper_revision, release = _setup(session)
        service = ReviewService()
        task = service.create_task(
            session,
            paper_id=paper.id,
            assignee_id=reviewer.id,
            created_by_id=admin.id,
        )
        changeset = service.create_changeset(
            session,
            review_task_id=task.id,
            paper_id=paper.id,
            actor_id=reviewer.id,
            base_release_id=release.id,
            title="Submitted revision boundary",
            reason="No linked revision may be appended after submission",
        )
        _add_paper_item(
            session, service, changeset, reviewer, paper, paper_revision
        )
        service.submit_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=reviewer.id,
            expected_version=2,
        )

        with pytest.raises(ValueError, match="draft changeset"):
            RevisionService().create_revision(
                session,
                object_identity=paper,
                actor_id=reviewer.id,
                reason="Late linked revision",
                snapshot={"paper_key": paper.paper_key, "late": True},
                predecessor=paper_revision,
                changeset_id=changeset.id,
            )


def test_changeset_revision_cannot_be_published_before_approval(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        reviewer, _, admin, paper, paper_revision, release = _setup(session)
        service = ReviewService()
        task = service.create_task(
            session,
            paper_id=paper.id,
            assignee_id=reviewer.id,
            created_by_id=admin.id,
        )
        changeset = service.create_changeset(
            session,
            review_task_id=task.id,
            paper_id=paper.id,
            actor_id=reviewer.id,
            base_release_id=release.id,
            title="Approval boundary",
            reason="Draft revisions cannot change the published pointer",
        )
        _add_paper_item(
            session, service, changeset, reviewer, paper, paper_revision
        )

        with pytest.raises(ValueError, match="cannot be published"):
            RevisionService().create_revision(
                session,
                object_identity=paper,
                actor_id=reviewer.id,
                reason="Premature publication",
                snapshot={"paper_key": paper.paper_key, "reviewed": True},
                predecessor=paper_revision,
                changeset_id=changeset.id,
                workflow_state=WorkflowState.PUBLISHED,
                is_current_published=True,
            )

        session.refresh(paper_revision)
        assert paper_revision.workflow_state is WorkflowState.PUBLISHED
        assert paper_revision.is_current_published is True


def test_submission_selects_latest_matching_immutable_revision(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        reviewer, _, admin, paper, paper_revision, release = _setup(session)
        service = ReviewService()
        task = service.create_task(
            session,
            paper_id=paper.id,
            assignee_id=reviewer.id,
            created_by_id=admin.id,
        )
        changeset = service.create_changeset(
            session,
            review_task_id=task.id,
            paper_id=paper.id,
            actor_id=reviewer.id,
            base_release_id=release.id,
            title="Bind approved revision",
            reason="The immutable revision must match the reviewed content",
        )
        item = _add_paper_item(
            session, service, changeset, reviewer, paper, paper_revision
        )
        proposed_snapshot = item.proposed_snapshot
        first = RevisionService().create_revision(
            session,
            object_identity=paper,
            actor_id=reviewer.id,
            reason="First matching draft",
            snapshot=proposed_snapshot,
            predecessor=paper_revision,
            changeset_id=changeset.id,
        )
        latest = RevisionService().create_revision(
            session,
            object_identity=paper,
            actor_id=reviewer.id,
            reason="Latest matching draft",
            snapshot=proposed_snapshot,
            predecessor=first,
            changeset_id=changeset.id,
        )

        submitted = service.submit_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=reviewer.id,
            expected_version=2,
        )

        session.refresh(item)
        assert item.proposed_revision_id == latest.id
        assert submitted.submitted_snapshot is not None
        assert submitted.submitted_snapshot["items"][0]["proposed_revision_id"] == str(
            latest.id
        )


def test_submission_rejects_revision_that_does_not_match_item_content(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        reviewer, _, admin, paper, paper_revision, release = _setup(session)
        service = ReviewService()
        task = service.create_task(
            session,
            paper_id=paper.id,
            assignee_id=reviewer.id,
            created_by_id=admin.id,
        )
        changeset = service.create_changeset(
            session,
            review_task_id=task.id,
            paper_id=paper.id,
            actor_id=reviewer.id,
            base_release_id=release.id,
            title="Reject mismatched revision",
            reason="Only the reviewed content may be submitted",
        )
        _add_paper_item(
            session, service, changeset, reviewer, paper, paper_revision
        )
        RevisionService().create_revision(
            session,
            object_identity=paper,
            actor_id=reviewer.id,
            reason="Different draft content",
            snapshot={"paper_key": paper.paper_key, "reviewed": False},
            predecessor=paper_revision,
            changeset_id=changeset.id,
        )

        with pytest.raises(InvalidReview, match="matching immutable revision"):
            service.submit_changeset(
                session,
                changeset_id=changeset.id,
                actor_id=reviewer.id,
                expected_version=2,
            )


def test_review_migration_round_trip_clears_removed_changeset_references(
    auth_session_factory,
    postgresql_database_url: str,
) -> None:
    with auth_session_factory.begin() as session:
        reviewer, _, admin, paper, paper_revision, release = _setup(session)
        service = ReviewService()
        task = service.create_task(
            session,
            paper_id=paper.id,
            assignee_id=reviewer.id,
            created_by_id=admin.id,
        )
        changeset = service.create_changeset(
            session,
            review_task_id=task.id,
            paper_id=paper.id,
            actor_id=reviewer.id,
            base_release_id=release.id,
            title="Migration round trip",
            reason="Preserve a valid schema after downgrade and upgrade",
        )
        item = _add_paper_item(
            session, service, changeset, reviewer, paper, paper_revision
        )
        draft_revision = RevisionService().create_revision(
            session,
            object_identity=paper,
            actor_id=reviewer.id,
            reason="Draft tied to changeset",
            snapshot={"paper_key": paper.paper_key, "reviewed": True},
            predecessor=paper_revision,
            changeset_id=changeset.id,
        )
        service.submit_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=reviewer.id,
            expected_version=2,
        )
        session.refresh(item)
        assert item.proposed_revision_id == draft_revision.id
        draft_revision_id = draft_revision.id

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", postgresql_database_url)
    config.attributes["leadtrace_database_url"] = postgresql_database_url
    config.attributes["leadtrace_expected_database_name"] = make_url(
        postgresql_database_url
    ).database
    command.downgrade(config, "0008_release_hardening")
    with auth_session_factory.begin() as session:
        session.execute(
            text(
                "ALTER TABLE object_revisions "
                "DISABLE TRIGGER trg_object_revisions_immutable"
            )
        )
        session.execute(
            update(ObjectRevision)
            .where(ObjectRevision.id == draft_revision_id)
            .values(changeset_id=uuid4())
        )
        session.execute(
            text(
                "ALTER TABLE object_revisions "
                "ENABLE TRIGGER trg_object_revisions_immutable"
            )
        )
    command.upgrade(config, "head")

    with auth_session_factory() as session:
        restored = session.get(ObjectRevision, draft_revision_id)
        assert restored is not None
        assert restored.changeset_id is None
