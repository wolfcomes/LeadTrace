from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.activities.service import ActivityDraft, ActivityReviewService
from app.compounds.models import Compound
from app.compounds.service import CompoundDraft, CompoundReviewService, CompoundVersionConflict
from app.evidence.service import EvidenceDraft, EvidenceReviewService
from app.lineages.service import LineageReviewService, PairReadinessService
from app.papers.models import Paper
from app.releases.models import Release
from app.revisions.models import StructureState
from app.revisions.service import RevisionService
from app.reviews.models import Changeset, ReviewTask, ReviewTaskStatus
from app.security.policies import WorkflowState
from app.structures.models import Structure
from app.users.models import UserRole
from app.users.service import UserService


def _seed(session) -> dict[str, object]:
    user = UserService().create_user(
        session,
        username=f"science-reviewer-{uuid4().hex[:8]}",
        display_name="Science Reviewer",
        role=UserRole.REVIEWER,
        initial_password="Science review password 2026!",
    )
    user.must_change_password = False
    paper = Paper(paper_key=f"science-paper-{uuid4().hex[:8]}")
    session.add(paper)
    session.flush()
    release = Release(
        release_key=f"science-release-{uuid4().hex[:8]}",
        title="Science release",
        notes="",
        metrics={},
        published_by_id=user.id,
        published_at=datetime.now(UTC),
        is_current=False,
        manifest_finalized=False,
    )
    session.add(release)
    session.flush()
    task = ReviewTask(
        paper_id=paper.id,
        assigned_reviewer_id=user.id,
        created_by_id=user.id,
        status=ReviewTaskStatus.IN_PROGRESS,
        version=1,
    )
    session.add(task)
    session.flush()
    changeset = Changeset(
        review_task_id=task.id,
        paper_id=paper.id,
        owner_id=user.id,
        base_release_id=release.id,
        title="Science edits",
        reason="Scientific review",
        workflow_state=WorkflowState.DRAFT,
        version=1,
    )
    session.add(changeset)
    session.flush()
    return {"user": user, "paper": paper, "changeset": changeset}


def test_compound_review_is_append_only_and_checks_expected_version(auth_session_factory) -> None:
    with auth_session_factory.begin() as session:
        seeded = _seed(session)
        service = CompoundReviewService()
        compound, first = service.create_compound(
            session,
            paper_id=seeded["paper"].id,
            actor_id=seeded["user"].id,
            changeset_id=seeded["changeset"].id,
            expected_version=1,
            draft=CompoundDraft("26b", "26b", "Transcribed from Table 2"),
        )
        assert first.snapshot["local_identity"] == "26b"
        with pytest.raises(CompoundVersionConflict):
            service.update_compound(
                session,
                compound_id=compound.id,
                actor_id=seeded["user"].id,
                changeset_id=seeded["changeset"].id,
                expected_version=1,
                draft=CompoundDraft("26b", "26b corrected", "Corrected label"),
            )
        second = service.update_compound(
            session,
            compound_id=compound.id,
            actor_id=seeded["user"].id,
            changeset_id=seeded["changeset"].id,
            expected_version=2,
            draft=CompoundDraft("26b", "26b corrected", "Corrected label"),
        )
        assert second.predecessor_id == first.id
        assert first.snapshot["display_label"] == "26b"
        assert second.snapshot["display_label"] == "26b corrected"


def test_evidence_and_activity_revisions_preserve_source_and_support_tombstones(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        seeded = _seed(session)
        compound = Compound(
            paper_id=seeded["paper"].id,
            local_identity="26b",
            display_label="26b",
            normalized_label="26b",
        )
        session.add(compound)
        session.flush()
        evidence_service = EvidenceReviewService()
        evidence, evidence_revision = evidence_service.create_evidence(
            session,
            paper_id=seeded["paper"].id,
            actor_id=seeded["user"].id,
            changeset_id=seeded["changeset"].id,
            expected_version=1,
            draft=EvidenceDraft("ev-1", "Original source sentence", "Table 2", (compound.id,)),
            reason="Bind original evidence",
        )
        activity_service = ActivityReviewService()
        activity, activity_revision = activity_service.create_activity(
            session,
            paper_id=seeded["paper"].id,
            actor_id=seeded["user"].id,
            changeset_id=seeded["changeset"].id,
            expected_version=2,
            draft=ActivityDraft(
                "assay-1", compound.id, "binding", "IC50", "12", "nM",
                evidence_text="Original assay sentence", evidence_ids=(evidence.id,)
            ),
            reason="Bind assay result",
        )
        updated_evidence = evidence_service.update_evidence(
            session,
            evidence_id=evidence.id,
            actor_id=seeded["user"].id,
            changeset_id=seeded["changeset"].id,
            expected_version=3,
            draft=EvidenceDraft("ev-1", "Corrected source sentence", "Table 2", (compound.id,)),
            reason="Correct transcription",
        )
        assert evidence_revision.snapshot["original_text"] == "Original source sentence"
        assert updated_evidence.snapshot["original_text"] == "Corrected source sentence"
        tombstone = evidence_service.delete_evidence(
            session,
            evidence_id=evidence.id,
            actor_id=seeded["user"].id,
            changeset_id=seeded["changeset"].id,
            expected_version=4,
            reason="Remove duplicate evidence",
        )
        assert tombstone.is_tombstone is True
        assert tombstone.evidence_state.value == "rejected"
        activity_tombstone = activity_service.delete_activity(
            session,
            activity_id=activity.id,
            actor_id=seeded["user"].id,
            changeset_id=seeded["changeset"].id,
            expected_version=5,
            reason="Remove invalid assay",
        )
        assert activity_tombstone.is_tombstone is True
        assert activity_tombstone.activity_state.value == "rejected"
        assert activity_revision.snapshot["evidence_text"] == "Original assay sentence"


def test_lineage_service_keeps_unresolved_parent_null_and_rejects_dangling_delete(
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        seeded = _seed(session)
        compound = Compound(
            paper_id=seeded["paper"].id,
            local_identity="26b",
            display_label="26b",
            normalized_label="26b",
        )
        child = Compound(
            paper_id=seeded["paper"].id,
            local_identity="27b",
            display_label="27b",
            normalized_label="27b",
        )
        session.add_all([compound, child])
        session.flush()
        service = LineageReviewService()
        lineage, _ = service.create_lineage(
            session,
            paper_id=seeded["paper"].id,
            actor_id=seeded["user"].id,
            changeset_id=seeded["changeset"].id,
            expected_version=1,
            lineage_key="series-a",
            reason="Create lineage",
        )
        parent_edge, parent_revision = service.create_edge(
            session,
            paper_id=seeded["paper"].id,
            lineage_id=lineage.id,
            actor_id=seeded["user"].id,
            changeset_id=seeded["changeset"].id,
            expected_version=2,
            edge_key="26b-to-27b",
            parent_compound_id=None,
            derived_compound_id=compound.id,
            relation_type="optimization",
            relation_status="unresolved",
            evidence_ids=(),
            reason="Unresolved parent in source",
        )
        assert parent_edge.parent_compound_id is None
        assert parent_revision.snapshot["parent_compound_id"] is None
        child_edge, _ = service.create_edge(
            session,
            paper_id=seeded["paper"].id,
            lineage_id=lineage.id,
            actor_id=seeded["user"].id,
            changeset_id=seeded["changeset"].id,
            expected_version=3,
            edge_key="26b-to-27b-confirmed",
            parent_compound_id=compound.id,
            derived_compound_id=child.id,
            relation_type="optimization",
            relation_status="text_explicit",
            evidence_ids=(),
            reason="Explicit downstream relation",
        )
        with pytest.raises(ValueError, match="duplicate lineage edge"):
            service.create_edge(
                session,
                paper_id=seeded["paper"].id,
                lineage_id=lineage.id,
                actor_id=seeded["user"].id,
                changeset_id=seeded["changeset"].id,
                expected_version=4,
                edge_key="duplicate-edge-key",
                parent_compound_id=compound.id,
                derived_compound_id=child.id,
                relation_type="optimization",
                relation_status="text_explicit",
                evidence_ids=(),
                reason="Duplicate relation",
            )
        with pytest.raises(ValueError, match="dangling"):
            service.delete_edge(
                session,
                edge_id=parent_edge.id,
                actor_id=seeded["user"].id,
                changeset_id=seeded["changeset"].id,
                expected_version=4,
                reason="Remove relation",
            )
        assert child_edge.id != parent_edge.id


def test_pair_readiness_database_entry_uses_current_revisions(auth_session_factory) -> None:
    with auth_session_factory.begin() as session:
        seeded = _seed(session)
        parent = Compound(paper_id=seeded["paper"].id, local_identity="26b", display_label="26b", normalized_label="26b")
        derived = Compound(paper_id=seeded["paper"].id, local_identity="27b", display_label="27b", normalized_label="27b")
        session.add_all([parent, derived])
        session.flush()
        evidence, _ = EvidenceReviewService().create_evidence(
            session,
            paper_id=seeded["paper"].id,
            actor_id=seeded["user"].id,
            changeset_id=seeded["changeset"].id,
            expected_version=1,
            draft=EvidenceDraft("ev-ready", "The optimized analog was confirmed.", "Figure 3", (parent.id, derived.id)),
            reason="Bind pair evidence",
        )
        parent_structure = Structure(paper_id=seeded["paper"].id, compound_id=parent.id, structure_key="parent")
        derived_structure = Structure(paper_id=seeded["paper"].id, compound_id=derived.id, structure_key="derived")
        session.add_all([parent_structure, derived_structure])
        session.flush()
        revisions = RevisionService()
        for structure, smiles in ((parent_structure, "CCO"), (derived_structure, "CCN")):
            revisions.create_revision(
                session,
                object_identity=structure,
                actor_id=seeded["user"].id,
                reason="Confirmed source structure",
                snapshot={"canonical_smiles": smiles},
                workflow_state=WorkflowState.PUBLISHED,
                is_current_published=True,
                structure_state=StructureState.STRUCTURE_CONFIRMED,
                canonical_smiles=smiles,
            )
        lineage, _ = LineageReviewService().create_lineage(
            session,
            paper_id=seeded["paper"].id,
            actor_id=seeded["user"].id,
            changeset_id=seeded["changeset"].id,
            expected_version=2,
            lineage_key="ready-series",
            reason="Create ready lineage",
        )
        edge, _ = LineageReviewService().create_edge(
            session,
            paper_id=seeded["paper"].id,
            lineage_id=lineage.id,
            actor_id=seeded["user"].id,
            changeset_id=seeded["changeset"].id,
            expected_version=3,
            edge_key="ready-edge",
            parent_compound_id=parent.id,
            derived_compound_id=derived.id,
            relation_type="optimization",
            relation_status="text_explicit",
            evidence_ids=(evidence.id,),
            reason="Bind confirmed relation",
        )
        readiness = PairReadinessService.from_database(session, edge.id)
        assert readiness.eligible is True
        assert readiness.blocking_codes == ()
