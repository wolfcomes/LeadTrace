from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Barrier, Event, Lock, Thread, current_thread
from uuid import UUID, uuid4

import pytest
from sqlalchemy import cast, delete, event, func, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import DBAPIError

from app.compounds.models import Compound
from app.audit.models import AuditChainHead
from app.audit.service import AuditService, canonical_content_hash
from app.papers.models import Paper
from app.releases.models import Release, ReleaseItem
from app.revisions.models import ObjectKind, ObjectRevision
from app.revisions.service import RevisionService
from app.reviews.models import (
    Changeset,
    ChangesetItem,
    ChangesetSubmission,
    ReviewTask,
)
from app.reviews.comments import (
    CommentAction,
    CommentService,
    CommentTargetType,
)
from app.reviews.service import RevisionConflict, ReviewService
from app.security.policies import WorkflowState
from app.users.models import UserRole
from app.users.service import UserService


PASSWORD = "Concurrent review password 2026!"


def _review_fixture(session) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    users = UserService()
    reviewer = users.create_user(
        session,
        username=f"concurrent-{uuid4().hex[:8]}",
        display_name="Concurrent Reviewer",
        role=UserRole.REVIEWER,
        initial_password=PASSWORD,
    )
    reviewer.must_change_password = False
    admin = users.create_user(
        session,
        username=f"concurrent-admin-{uuid4().hex[:8]}",
        display_name="Concurrent Admin",
        role=UserRole.ADMIN,
        initial_password=PASSWORD,
    )
    admin.must_change_password = False
    paper = Paper(paper_key=f"concurrent-paper-{uuid4().hex[:8]}", doi=None)
    session.add(paper)
    session.flush()
    release = Release(
        release_key=f"concurrent-release-{uuid4().hex[:8]}",
        title="Concurrent release",
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
        reason="Concurrent published base",
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
        title="Concurrent draft",
        reason="Verify serialized optimistic updates",
    )
    return changeset.id, reviewer.id, admin.id, paper.id, paper_revision.id


def _approved_review_fixture(session) -> tuple[UUID, UUID]:
    changeset_id, reviewer_id, admin_id, paper_id, paper_revision_id = (
        _review_fixture(session)
    )
    service = ReviewService()
    item = service.add_changeset_item(
        session,
        changeset_id=changeset_id,
        actor_id=reviewer_id,
        expected_version=1,
        object_id=paper_id,
        object_kind="paper",
        base_revision_id=paper_revision_id,
        proposed_snapshot={"label": "approved proposal"},
    )
    paper = session.get(Paper, paper_id)
    assert paper is not None
    revision = RevisionService().create_revision(
        session,
        object_identity=paper,
        actor_id=reviewer_id,
        reason="Approved proposal",
        snapshot=item.proposed_snapshot,
        predecessor=session.get(ObjectRevision, paper_revision_id),
        changeset_id=changeset_id,
    )
    service.submit_changeset(
        session,
        changeset_id=changeset_id,
        actor_id=reviewer_id,
        expected_version=2,
    )
    service.transition_changeset(
        session,
        changeset_id=changeset_id,
        actor_id=admin_id,
        expected_version=3,
        next_state=WorkflowState.APPROVED,
    )
    return changeset_id, revision.id


def test_two_same_version_saves_have_exactly_one_winner(auth_session_factory) -> None:
    with auth_session_factory.begin() as session:
        changeset_id, reviewer_id, _, _, _ = _review_fixture(session)

    barrier = Barrier(2)
    guard = Lock()
    results: list[tuple[str, int | None]] = []

    def update(title: str) -> None:
        try:
            with auth_session_factory.begin() as session:
                barrier.wait()
                ReviewService().update_changeset(
                    session,
                    changeset_id=changeset_id,
                    actor_id=reviewer_id,
                    expected_version=1,
                    title=title,
                )
            outcome = ("updated", None)
        except RevisionConflict as error:
            outcome = ("conflict", error.current_version)
        with guard:
            results.append(outcome)

    threads = [Thread(target=update, args=(f"Writer {index}",)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert sorted(results) == [("conflict", 2), ("updated", None)]
    with auth_session_factory() as session:
        changeset = session.get(Changeset, changeset_id)
        assert changeset is not None
        assert changeset.version == 2
        assert changeset.title in {"Writer 0", "Writer 1"}


def test_locking_version_check_refreshes_a_preloaded_identity(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        changeset_id, reviewer_id, _, _, _ = _review_fixture(session)

    with auth_session_factory() as first_session:
        with first_session.begin():
            preloaded = first_session.get(Changeset, changeset_id)
            assert preloaded is not None
            assert preloaded.version == 1
            with auth_session_factory.begin() as second_session:
                ReviewService().update_changeset(
                    second_session,
                    changeset_id=changeset_id,
                    actor_id=reviewer_id,
                    expected_version=1,
                    title="Committed by another session",
                )

            with pytest.raises(RevisionConflict) as error:
                ReviewService().update_changeset(
                    first_session,
                    changeset_id=changeset_id,
                    actor_id=reviewer_id,
                    expected_version=1,
                    title="Must not overwrite with preloaded state",
                )

            assert error.value.current_version == 2


def test_comment_and_changeset_audits_use_deadlock_free_lock_order(
    auth_session_factory,
    monkeypatch,
) -> None:
    with auth_session_factory.begin() as session:
        changeset_id, reviewer_id, _, paper_id, _ = _review_fixture(session)
        changeset = session.get(Changeset, changeset_id)
        assert changeset is not None
        comment, _ = CommentService().create_comment(
            session,
            changeset_id=changeset.id,
            actor_id=reviewer_id,
            target_type=CommentTargetType.CHANGESET,
            target_id=changeset.id,
            changeset_item_id=None,
            field_path=None,
            body="Resolve while another editor saves.",
            ip_address="192.0.2.30",
            request_id="comment-created",
        )
        comment_id = comment.id
        release_id = changeset.base_release_id

    original_append = AuditService.append_event
    audit_head_locked = Event()
    editor_has_changeset = Event()
    errors: list[BaseException] = []
    error_guard = Lock()

    def observed_append(self, session, **kwargs):
        if kwargs["action"] == "review.comment.resolved":
            session.scalar(
                select(AuditChainHead)
                .where(AuditChainHead.id == 1)
                .with_for_update()
            )
            audit_head_locked.set()
            editor_has_changeset.wait(timeout=0.5)
        return original_append(self, session, **kwargs)

    monkeypatch.setattr(AuditService, "append_event", observed_append)

    def resolve_comment() -> None:
        try:
            with auth_session_factory.begin() as session:
                CommentService().transition(
                    session,
                    comment_id=comment_id,
                    actor_id=reviewer_id,
                    action=CommentAction.RESOLVED,
                    reason="Source checked",
                    ip_address="192.0.2.30",
                    request_id="comment-resolved",
                )
        except BaseException as error:  # pragma: no cover - asserted below
            with error_guard:
                errors.append(error)

    def update_changeset() -> None:
        assert audit_head_locked.wait(timeout=5)
        try:
            with auth_session_factory.begin() as session:
                changeset = ReviewService().update_changeset(
                    session,
                    changeset_id=changeset_id,
                    actor_id=reviewer_id,
                    expected_version=1,
                    title="Saved without a lock cycle",
                )
                editor_has_changeset.set()
                AuditService().append_event(
                    session,
                    actor_id=reviewer_id,
                    action="review.changeset.updated",
                    target_type="changeset",
                    target_id=changeset.id,
                    paper_id=paper_id,
                    changeset_id=changeset.id,
                    release_id=release_id,
                    ip_address="192.0.2.31",
                    request_id="changeset-updated",
                    result="success",
                    reason="Concurrent save",
                    before_hash=canonical_content_hash({"version": 1}),
                    after_hash=canonical_content_hash({"version": 2}),
                    details={},
                )
        except BaseException as error:  # pragma: no cover - asserted below
            with error_guard:
                errors.append(error)

    threads = [Thread(target=resolve_comment), Thread(target=update_changeset)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    with auth_session_factory() as session:
        assert AuditService().verify_chain(session).valid is True


def test_changeset_creation_does_not_hold_release_while_waiting_for_task(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        changeset_id, reviewer_id, admin_id, paper_id, _ = _review_fixture(session)
        changeset = session.get(Changeset, changeset_id)
        assert changeset is not None
        task_id = changeset.review_task_id
        release_id = changeset.base_release_id

    task_locked = Event()
    creator_waiting_for_task = Event()
    errors: list[BaseException] = []
    error_guard = Lock()
    engine = auth_session_factory.kw["bind"]

    def observe_creator_task_lock(
        _connection, _cursor, statement, _parameters, _context, _many
    ) -> None:
        if (
            current_thread().name == "changeset-creator"
            and "FROM review_tasks" in statement
            and "FOR UPDATE" in statement
        ):
            creator_waiting_for_task.set()

    event.listen(engine, "before_cursor_execute", observe_creator_task_lock)

    def create_duplicate_changeset() -> None:
        assert task_locked.wait(timeout=5)
        try:
            with auth_session_factory.begin() as session:
                session.execute(text("SET LOCAL lock_timeout = '5s'"))
                ReviewService().create_changeset(
                    session,
                    paper_id=paper_id,
                    actor_id=reviewer_id,
                    review_task_id=task_id,
                    base_release_id=release_id,
                    title="Concurrent duplicate",
                    reason="Exercise task before release lock order",
                )
        except Exception as error:
            if "already has a changeset" not in str(error):
                with error_guard:
                    errors.append(error)

    def approve_while_creation_waits() -> None:
        try:
            with auth_session_factory.begin() as session:
                session.execute(text("SET LOCAL lock_timeout = '5s'"))
                session.scalar(
                    select(ReviewTask)
                    .where(ReviewTask.id == task_id)
                    .with_for_update()
                )
                task_locked.set()
                assert creator_waiting_for_task.wait(timeout=5)
                AuditService().append_event(
                    session,
                    actor_id=admin_id,
                    action="review.changeset.approved",
                    target_type="changeset",
                    target_id=changeset_id,
                    paper_id=paper_id,
                    changeset_id=changeset_id,
                    release_id=release_id,
                    ip_address="192.0.2.32",
                    request_id="concurrent-approval",
                    result="success",
                    reason="Verify lock order",
                    before_hash=canonical_content_hash({"state": "submitted"}),
                    after_hash=canonical_content_hash({"state": "approved"}),
                    details={},
                )
        except BaseException as error:  # pragma: no cover - asserted below
            with error_guard:
                errors.append(error)

    threads = [
        Thread(target=approve_while_creation_waits, name="changeset-approver"),
        Thread(target=create_duplicate_changeset, name="changeset-creator"),
    ]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=12)
    finally:
        event.remove(engine, "before_cursor_execute", observe_creator_task_lock)

    assert all(not thread.is_alive() for thread in threads)
    assert errors == []


def test_database_rejects_submitted_content_and_item_mutation(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        changeset_id, reviewer_id, _, paper_id, paper_revision_id = _review_fixture(
            session
        )
        service = ReviewService()
        item = service.add_changeset_item(
            session,
            changeset_id=changeset_id,
            actor_id=reviewer_id,
            expected_version=1,
            object_id=paper_id,
            object_kind="paper",
            base_revision_id=paper_revision_id,
            proposed_snapshot={"label": "26a"},
        )
        service.submit_changeset(
            session,
            changeset_id=changeset_id,
            actor_id=reviewer_id,
            expected_version=2,
        )
        item_id = item.id
        submission_id = session.scalar(
            select(ChangesetSubmission.id).where(
                ChangesetSubmission.changeset_id == changeset_id
            )
        )
        submitted_changeset = session.get(Changeset, changeset_id)
        assert submitted_changeset is not None
        base_release = session.get(Release, submitted_changeset.base_release_id)
        assert base_release is not None
        other_reviewer = UserService().create_user(
            session,
            username=f"move-target-{uuid4().hex[:8]}",
            display_name="Move Target Reviewer",
            role=UserRole.REVIEWER,
            initial_password=PASSWORD,
        )
        other_reviewer.must_change_password = False
        other_task = service.create_task(
            session,
            paper_id=paper_id,
            assignee_id=other_reviewer.id,
            created_by_id=base_release.published_by_id,
        )
        draft_target = service.create_changeset(
            session,
            review_task_id=other_task.id,
            paper_id=paper_id,
            actor_id=other_reviewer.id,
            base_release_id=base_release.id,
            title="Move target",
            reason="Submitted items must not move here",
        )
        draft_target_id = draft_target.id

    with pytest.raises(DBAPIError):
        with auth_session_factory.begin() as session:
            changeset = session.get(Changeset, changeset_id)
            assert changeset is not None
            changeset.title = "Mutation after submission"

    with pytest.raises(DBAPIError):
        with auth_session_factory.begin() as session:
            session.execute(delete(ChangesetItem).where(ChangesetItem.id == item_id))

    with pytest.raises(DBAPIError):
        with auth_session_factory.begin() as session:
            session.execute(
                update(ChangesetItem)
                .where(ChangesetItem.id == item_id)
                .values(
                    changeset_id=draft_target_id,
                    proposed_snapshot={"label": "moved and mutated"},
                    content_hash="b" * 64,
                )
            )

    with pytest.raises(DBAPIError):
        with auth_session_factory.begin() as session:
            submitted = session.get(Changeset, changeset_id)
            assert submitted is not None
            assert submitted.submitted_at is not None
            session.execute(
                update(Changeset)
                .where(Changeset.id == changeset_id)
                .values(
                    workflow_state=WorkflowState.APPROVED.value,
                    version=submitted.version + 1,
                    submitted_at=submitted.submitted_at + timedelta(minutes=1),
                )
            )

    with pytest.raises(DBAPIError):
        with auth_session_factory.begin() as session:
            session.execute(delete(Changeset).where(Changeset.id == changeset_id))

    with pytest.raises(DBAPIError):
        with auth_session_factory.begin() as session:
            session.execute(
                delete(ChangesetSubmission).where(
                    ChangesetSubmission.id == submission_id
                )
            )

    with pytest.raises(DBAPIError):
        with auth_session_factory.begin() as session:
            session.add(
                ChangesetSubmission(
                    changeset_id=draft_target_id,
                    submission_number=1,
                    changeset_version=1,
                    submitted_by_id=other_reviewer.id,
                    snapshot={"forged": True},
                    content_hash="f" * 64,
                )
            )


def test_database_preserves_submission_metadata_during_revised_draft(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        changeset_id, reviewer_id, admin_id, paper_id, paper_revision_id = (
            _review_fixture(session)
        )
        service = ReviewService()
        service.add_changeset_item(
            session,
            changeset_id=changeset_id,
            actor_id=reviewer_id,
            expected_version=1,
            object_id=paper_id,
            object_kind="paper",
            base_revision_id=paper_revision_id,
            proposed_snapshot={"label": "26a"},
        )
        changeset = service.submit_changeset(
            session,
            changeset_id=changeset_id,
            actor_id=reviewer_id,
            expected_version=2,
        )
        service.transition_changeset(
            session,
            changeset_id=changeset_id,
            actor_id=admin_id,
            expected_version=3,
            next_state=WorkflowState.CHANGES_REQUESTED,
        )
        service.revise_changeset(
            session,
            changeset_id=changeset_id,
            actor_id=reviewer_id,
            expected_version=4,
        )
        original_snapshot = changeset.submitted_snapshot

    with pytest.raises(DBAPIError, match="submission metadata is immutable"):
        with auth_session_factory.begin() as session:
            session.execute(
                update(Changeset)
                .where(Changeset.id == changeset_id)
                .values(
                    submitted_snapshot={"forged": True},
                    version=6,
                )
            )

    with auth_session_factory() as session:
        changeset = session.get(Changeset, changeset_id)
        assert changeset is not None
        assert changeset.workflow_state is WorkflowState.REVISED_DRAFT
        assert changeset.version == 5
        assert changeset.submitted_snapshot == original_snapshot


def test_database_rejects_revision_linked_after_changeset_submission(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        changeset_id, reviewer_id, _, paper_id, paper_revision_id = _review_fixture(
            session
        )
        service = ReviewService()
        service.add_changeset_item(
            session,
            changeset_id=changeset_id,
            actor_id=reviewer_id,
            expected_version=1,
            object_id=paper_id,
            object_kind="paper",
            base_revision_id=paper_revision_id,
            proposed_snapshot={"label": "26a"},
        )
        service.submit_changeset(
            session,
            changeset_id=changeset_id,
            actor_id=reviewer_id,
            expected_version=2,
        )
        late_snapshot = {"label": "late"}
        late_content_hash = session.scalar(
            select(func.leadtrace_jsonb_sha256(cast(late_snapshot, JSONB)))
        )
        assert late_content_hash is not None

    with pytest.raises(DBAPIError, match="draft changeset"):
        with auth_session_factory.begin() as session:
            session.add(
                ObjectRevision(
                    object_id=paper_id,
                    revision_number=2,
                    predecessor_id=paper_revision_id,
                    changeset_id=changeset_id,
                    actor_id=reviewer_id,
                    reason="Late raw revision",
                    content_hash=late_content_hash,
                    snapshot=late_snapshot,
                    workflow_state=WorkflowState.DRAFT,
                    is_current_published=False,
                )
            )


def test_database_rejects_published_revision_linked_to_draft_changeset(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        changeset_id, reviewer_id, _, _, _ = _review_fixture(session)
        changeset = session.get(Changeset, changeset_id)
        assert changeset is not None
        compound = Compound(
            paper_id=changeset.paper_id,
            local_identity=f"direct-publish-{uuid4().hex[:8]}",
            display_label="Direct publish",
            normalized_label="direct publish",
        )
        session.add(compound)
        session.flush()
        ReviewService().add_changeset_item(
            session,
            changeset_id=changeset_id,
            actor_id=reviewer_id,
            expected_version=1,
            object_id=compound.id,
            object_kind="compound",
            proposed_snapshot={"display_label": "Direct publish"},
        )
        published_snapshot = {"display_label": "Direct publish"}
        published_content_hash = session.scalar(
            select(func.leadtrace_jsonb_sha256(cast(published_snapshot, JSONB)))
        )
        assert published_content_hash is not None
        compound_id = compound.id

    with pytest.raises(DBAPIError, match="cannot be published"):
        with auth_session_factory.begin() as session:
            session.add(
                ObjectRevision(
                    object_id=compound_id,
                    revision_number=1,
                    changeset_id=changeset_id,
                    actor_id=reviewer_id,
                    reason="Bypass approval",
                    content_hash=published_content_hash,
                    snapshot=published_snapshot,
                    workflow_state=WorkflowState.PUBLISHED,
                    is_current_published=True,
                )
            )


def test_database_rejects_linked_revision_state_advance_before_approval(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        changeset_id, reviewer_id, _, paper_id, paper_revision_id = _review_fixture(
            session
        )
        item = ReviewService().add_changeset_item(
            session,
            changeset_id=changeset_id,
            actor_id=reviewer_id,
            expected_version=1,
            object_id=paper_id,
            object_kind="paper",
            base_revision_id=paper_revision_id,
            proposed_snapshot={"label": "26a"},
        )
        paper = session.get(Paper, paper_id)
        assert paper is not None
        revision = RevisionService().create_revision(
            session,
            object_identity=paper,
            actor_id=reviewer_id,
            reason="Draft cannot self-approve",
            snapshot=item.proposed_snapshot,
            predecessor=session.get(ObjectRevision, paper_revision_id),
            changeset_id=changeset_id,
        )
        revision_id = revision.id

    with pytest.raises(DBAPIError, match="before changeset approval"):
        with auth_session_factory.begin() as session:
            session.execute(
                update(ObjectRevision)
                .where(ObjectRevision.id == revision_id)
                .values(workflow_state=WorkflowState.SUBMITTED)
            )


@pytest.mark.parametrize(
    "terminal_state",
    [WorkflowState.CHANGES_REQUESTED, WorkflowState.REJECTED],
)
def test_database_rejects_negative_revision_outcome_after_changeset_approval(
    auth_session_factory,
    terminal_state: WorkflowState,
) -> None:
    with auth_session_factory.begin() as session:
        _, revision_id = _approved_review_fixture(session)

    with auth_session_factory.begin() as session:
        session.execute(
            update(ObjectRevision)
            .where(ObjectRevision.id == revision_id)
            .values(workflow_state=WorkflowState.SUBMITTED)
        )

    with pytest.raises(DBAPIError, match="inconsistent with changeset state"):
        with auth_session_factory.begin() as session:
            session.execute(
                update(ObjectRevision)
                .where(ObjectRevision.id == revision_id)
                .values(workflow_state=terminal_state)
            )


def test_database_rejects_revision_publication_until_changeset_is_published(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        _, revision_id = _approved_review_fixture(session)

    for state in (WorkflowState.SUBMITTED, WorkflowState.APPROVED):
        with auth_session_factory.begin() as session:
            session.execute(
                update(ObjectRevision)
                .where(ObjectRevision.id == revision_id)
                .values(workflow_state=state)
            )

    with pytest.raises(DBAPIError, match="inconsistent with changeset state"):
        with auth_session_factory.begin() as session:
            session.execute(
                update(ObjectRevision)
                .where(ObjectRevision.id == revision_id)
                .values(workflow_state=WorkflowState.PUBLISHED)
            )


def test_revision_update_does_not_take_reverse_changeset_lock(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        changeset_id, revision_id = _approved_review_fixture(session)

    outcomes: list[str] = []

    def advance_revision() -> None:
        try:
            with auth_session_factory.begin() as session:
                session.execute(text("SET LOCAL lock_timeout = '750ms'"))
                session.execute(
                    update(ObjectRevision)
                    .where(ObjectRevision.id == revision_id)
                    .values(workflow_state=WorkflowState.SUBMITTED)
                )
            outcomes.append("updated")
        except DBAPIError:
            outcomes.append("blocked")

    thread = Thread(target=advance_revision)
    lock_session = auth_session_factory()
    lock_transaction = lock_session.begin()
    try:
        lock_session.execute(
            select(Changeset)
            .where(Changeset.id == changeset_id)
            .with_for_update()
        )
        thread.start()
        thread.join(timeout=3)
        completed_while_locked = not thread.is_alive()
    finally:
        lock_transaction.rollback()
        lock_session.close()

    thread.join(timeout=5)
    assert completed_while_locked
    assert outcomes == ["updated"]


def test_database_rejects_changeset_item_hash_mismatch(auth_session_factory) -> None:
    with auth_session_factory.begin() as session:
        changeset_id, reviewer_id, _, paper_id, paper_revision_id = _review_fixture(
            session
        )
        item = ReviewService().add_changeset_item(
            session,
            changeset_id=changeset_id,
            actor_id=reviewer_id,
            expected_version=1,
            object_id=paper_id,
            object_kind="paper",
            base_revision_id=paper_revision_id,
            proposed_snapshot={"label": "26a"},
        )
        item_id = item.id

    with pytest.raises(DBAPIError, match="content hash"):
        with auth_session_factory.begin() as session:
            session.execute(
                update(ChangesetItem)
                .where(ChangesetItem.id == item_id)
                .values(
                    proposed_snapshot={"label": "26b"},
                    content_hash="a" * 64,
                )
            )


def test_database_rejects_coordinated_forged_submission(auth_session_factory) -> None:
    with auth_session_factory.begin() as session:
        changeset_id, reviewer_id, _, paper_id, paper_revision_id = _review_fixture(
            session
        )
        ReviewService().add_changeset_item(
            session,
            changeset_id=changeset_id,
            actor_id=reviewer_id,
            expected_version=1,
            object_id=paper_id,
            object_kind="paper",
            base_revision_id=paper_revision_id,
            proposed_snapshot={"label": "26a"},
        )

    forged_snapshot = {"forged": True}
    with pytest.raises(DBAPIError, match="canonical changeset content"):
        with auth_session_factory.begin() as session:
            session.execute(
                update(Changeset)
                .where(Changeset.id == changeset_id)
                .values(
                    workflow_state=WorkflowState.SUBMITTED,
                    version=3,
                    submitted_at=datetime.now(UTC),
                    submitted_snapshot=forged_snapshot,
                    submitted_content_hash="f" * 64,
                )
            )
            session.add(
                ChangesetSubmission(
                    changeset_id=changeset_id,
                    submission_number=1,
                    changeset_version=3,
                    submitted_by_id=reviewer_id,
                    snapshot=forged_snapshot,
                    content_hash="f" * 64,
                )
            )


def test_database_requires_task_transition_for_canonical_submission(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        changeset_id, reviewer_id, _, paper_id, paper_revision_id = _review_fixture(
            session
        )
        item = ReviewService().add_changeset_item(
            session,
            changeset_id=changeset_id,
            actor_id=reviewer_id,
            expected_version=1,
            object_id=paper_id,
            object_kind="paper",
            base_revision_id=paper_revision_id,
            proposed_snapshot={"label": "26a"},
        )
        paper = session.get(Paper, paper_id)
        assert paper is not None
        proposed_revision = RevisionService().create_revision(
            session,
            object_identity=paper,
            actor_id=reviewer_id,
            reason="Canonical proposed revision",
            snapshot=item.proposed_snapshot,
            predecessor=session.get(ObjectRevision, paper_revision_id),
            changeset_id=changeset_id,
        )
        item.proposed_revision_id = proposed_revision.id
        session.flush()
        canonical_snapshot = session.scalar(
            select(
                cast(
                    func.leadtrace_changeset_snapshot(changeset_id),
                    JSONB,
                )
            )
        )
        canonical_hash = session.scalar(
            select(func.leadtrace_changeset_snapshot_hash(changeset_id))
        )
        assert canonical_snapshot is not None
        assert canonical_hash is not None

    with pytest.raises(DBAPIError, match="review task states are inconsistent"):
        with auth_session_factory.begin() as session:
            session.execute(
                update(Changeset)
                .where(Changeset.id == changeset_id)
                .values(
                    workflow_state=WorkflowState.SUBMITTED,
                    version=3,
                    submitted_at=datetime.now(UTC),
                    submitted_snapshot=canonical_snapshot,
                    submitted_content_hash=canonical_hash,
                )
            )
            session.add(
                ChangesetSubmission(
                    changeset_id=changeset_id,
                    submission_number=1,
                    changeset_version=3,
                    submitted_by_id=reviewer_id,
                    snapshot=canonical_snapshot,
                    content_hash=canonical_hash,
                )
            )
