from __future__ import annotations

from sqlalchemy import select

from app.approvals.service import ApprovalService
from app.papers.models import Paper
from app.papers.service import paper_detail_payload
from app.releases.manifest import capture_release_artifact_manifest
from app.releases.models import ReleaseItem
from app.releases.service import publish_approved_changeset, rollback_release
from app.revisions.models import ObjectKind
from app.revisions.service import RevisionService
from app.reviews.attestations import PaperReviewScopeService
from app.reviews.service import ReviewService
from app.security.policies import WorkflowState
from tests.releases.test_task21_red import TEST_OVERVIEW_METRICS
from tests.reviews.test_service import _setup


def test_publish_derives_human_verification_from_attestation_and_admin_approval(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        partial_release_metrics = {
            **TEST_OVERVIEW_METRICS,
            "corpus": {"numerator": 2, "denominator": 2, "unit": "papers"},
            "lineage": {"numerator": 0, "denominator": 2, "unit": "papers"},
            "human_review": {"numerator": 0, "denominator": 2, "unit": "papers"},
        }
        reviewer, _, admin, paper, _, base = _setup(
            session,
            finalize_release=False,
            release_metrics=partial_release_metrics,
        )
        unverified_paper = Paper(paper_key="unverified-paper-in-partial-release")
        session.add(unverified_paper)
        session.flush()
        unverified_revision = RevisionService().create_revision(
            session,
            object_identity=unverified_paper,
            actor_id=admin.id,
            reason="Published unverified Paper",
            snapshot={"paper_key": unverified_paper.paper_key},
            workflow_state=WorkflowState.PUBLISHED,
            is_current_published=True,
        )
        session.add(
            ReleaseItem(
                release_id=base.id,
                object_id=unverified_paper.id,
                revision_id=unverified_revision.id,
                paper_id=unverified_paper.id,
                object_kind=ObjectKind.PAPER,
                manifest_order=2,
            )
        )
        session.flush()
        base.manifest_finalized = True
        session.flush()
        capture_release_artifact_manifest(session, base.id)
        review = ReviewService()
        task = review.create_task(
            session,
            paper_id=paper.id,
            assignee_id=reviewer.id,
            created_by_id=admin.id,
        )
        changeset = review.create_changeset(
            session,
            paper_id=paper.id,
            actor_id=reviewer.id,
            review_task_id=task.id,
            base_release_id=base.id,
            title="Attested Paper review",
            reason="Review the complete frozen scope",
        )
        scope = PaperReviewScopeService.ensure_scope(
            session,
            changeset=changeset,
            actor_id=reviewer.id,
        )
        _, attestation, _ = PaperReviewScopeService.attest(
            session,
            changeset=changeset,
            actor_id=reviewer.id,
            expected_version=1,
            scope_hash=scope.scope_hash,
            statement="I reviewed every required item in this Paper scope.",
        )
        review.submit_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=reviewer.id,
            expected_version=2,
        )
        ApprovalService().approve(
            session,
            changeset_id=changeset.id,
            actor_id=admin.id,
            expected_version=3,
            reason="Independent administrative approval",
        )
        assert base.metrics["human_review"] == {
            "numerator": 0,
            "denominator": 2,
            "unit": "papers",
        }

        published = publish_approved_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=admin.id,
        )

        assert published.release.metrics["human_review"] == {
            "numerator": 1,
            "denominator": 2,
            "unit": "papers",
        }
        paper_release_item = session.scalar(
            select(ReleaseItem).where(
                ReleaseItem.release_id == published.release.id,
                ReleaseItem.object_kind == ObjectKind.PAPER,
                ReleaseItem.object_id == paper.id,
            )
        )
        assert paper_release_item is not None
        detail = paper_detail_payload(
            session,
            published.release,
            paper.id,
            request_id="verified-paper-detail",
        )
        assert detail["quality_summary"]["human_review"] == {
            "reviewed": 1,
            "total": 1,
            "status": "human_verified",
            "verified": True,
            "release_id": str(published.release.id),
            "paper_revision_id": str(paper_release_item.revision_id),
            "attestation_id": str(attestation.id),
        }
        assert detail["verification"] == {
            "ai_baseline": "published",
            "human_verified": True,
            "release_status": "partially_verified",
        }
        assert base.metrics["human_review"] == {
            "numerator": 0,
            "denominator": 2,
            "unit": "papers",
        }
        published_id = published.release.id
        base_id = base.id
        admin_id = admin.id

    with auth_session_factory.begin() as session:
        rolled_back = rollback_release(
            session,
            target_release_id=base_id,
            actor_id=admin_id,
            reason="Restore unverified baseline",
        )
        assert rolled_back.release.id != published_id
        assert rolled_back.release.metrics["human_review"] == {
            "numerator": 0,
            "denominator": 2,
            "unit": "papers",
        }


def test_review_marker_without_attestation_does_not_verify_paper(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        reviewer, _, admin, paper, paper_revision, base = _setup(
            session,
            release_metrics=TEST_OVERVIEW_METRICS,
        )
        capture_release_artifact_manifest(session, base.id)
        review = ReviewService()
        task = review.create_task(
            session,
            paper_id=paper.id,
            assignee_id=reviewer.id,
            created_by_id=admin.id,
        )
        changeset = review.create_changeset(
            session,
            paper_id=paper.id,
            actor_id=reviewer.id,
            review_task_id=task.id,
            base_release_id=base.id,
            title="Unattested Paper marker",
            reason="Prove a marker alone has no verification authority",
        )
        review.add_changeset_item(
            session,
            changeset_id=changeset.id,
            actor_id=reviewer.id,
            expected_version=1,
            object_id=paper.id,
            object_kind=ObjectKind.PAPER.value,
            base_revision_id=paper_revision.id,
            proposed_snapshot={
                "paper_key": paper.paper_key,
                "normalized_values": {"review_status": "reviewed"},
            },
        )
        review.submit_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=reviewer.id,
            expected_version=2,
        )
        ApprovalService().approve(
            session,
            changeset_id=changeset.id,
            actor_id=admin.id,
            expected_version=3,
            reason="Legacy approval without a frozen review scope",
        )

        published = publish_approved_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=admin.id,
        )

        assert published.release.metrics["human_review"] == {
            "numerator": 0,
            "denominator": 1,
            "unit": "papers",
        }
