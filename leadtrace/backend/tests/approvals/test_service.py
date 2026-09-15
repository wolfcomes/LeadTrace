from __future__ import annotations

from uuid import uuid4

import pytest

from app.approvals.service import ApprovalConflict, ApprovalService
from app.revisions.models import ObjectKind
from app.reviews.attestations import PaperReviewScopeService
from app.reviews.models import PaperReviewAttestation
from app.reviews.service import ReviewService
from tests.reviews.test_attestations import _seed_review


def test_approval_rejects_submission_without_frozen_attestation_summary(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        reviewer, admin, changeset, paper, paper_revision = _seed_review(session)
        review = ReviewService()
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
        scope = PaperReviewScopeService.ensure_scope(
            session,
            changeset=changeset,
            actor_id=reviewer.id,
        )
        session.add(
            PaperReviewAttestation(
                id=uuid4(),
                changeset_id=changeset.id,
                scope_id=scope.id,
                paper_id=paper.id,
                paper_revision_id=paper_revision.id,
                changeset_version=2,
                scope_hash=scope.scope_hash,
                reviewer_id=reviewer.id,
                item_count=scope.item_count,
                resolved_count=scope.item_count,
                blocker_count=0,
                statement="Inserted without a frozen attestation summary.",
            )
        )
        session.flush()
        review.submit_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=reviewer.id,
            expected_version=2,
        )

        with pytest.raises(ApprovalConflict, match="attestation"):
            ApprovalService().approve(
                session,
                changeset_id=changeset.id,
                actor_id=admin.id,
                expected_version=3,
                reason="This forged review evidence must not be approved.",
            )
