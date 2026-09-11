from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.activities.models import Activity, ActivityState
from app.compounds.models import Compound
from app.evidence.models import Evidence, EvidenceState
from app.lineages.models import Lineage, LineageEdge
from app.papers.models import Paper
from app.revisions.models import ObjectRevision
from app.revisions.service import RevisionService
from app.security.policies import WorkflowState
from app.structures.models import Structure, StructureState
from app.users.models import UserRole
from app.users.service import UserService
from app.visual_objects.models import VisualRegion


PASSWORD = "Domain actor password 2026!"


def _actor_and_paper(
    session: Session,
    *,
    paper_key: str = "paper-001",
) -> tuple[object, Paper]:
    actor = UserService().create_user(
        session,
        username=f"domain.actor.{paper_key}",
        display_name="Domain Actor",
        role=UserRole.REVIEWER,
        initial_password=PASSWORD,
    )
    paper = Paper(paper_key=paper_key, doi=f"10.1000/{paper_key}")
    session.add(paper)
    session.flush()
    return actor, paper


def test_stable_identity_and_revision_metadata_are_preserved(
    auth_session_factory: sessionmaker[Session],
) -> None:
    service = RevisionService()
    with auth_session_factory.begin() as session:
        actor, paper = _actor_and_paper(session)
        compound = Compound(
            paper_id=paper.id,
            local_identity="26a′",
            display_label="26a′",
            normalized_label="26a′",
        )
        session.add(compound)
        session.flush()
        first = service.create_revision(
            session,
            object_identity=compound,
            actor_id=actor.id,
            reason="Imported source row",
            snapshot={"display_label": "26a′", "source_row": 10},
            search_text="26a′",
        )
        second = service.create_revision(
            session,
            object_identity=compound,
            actor_id=actor.id,
            reason="Clarify preferred label",
            snapshot={"display_label": "26a′", "preferred_name": "Example"},
            predecessor=first,
            changeset_id=uuid4(),
            search_text="26a′ Example",
        )

        assert compound.id == first.object_id == second.object_id
        assert first.revision_number == 1
        assert second.revision_number == 2
        assert second.predecessor_id == first.id
        assert second.actor_id == actor.id
        assert second.changeset_id is not None
        assert len(first.content_hash) == 64
        assert first.snapshot["source_row"] == 10


def test_revision_number_is_unique_per_stable_object(
    auth_session_factory: sessionmaker[Session],
) -> None:
    with pytest.raises(IntegrityError):
        with auth_session_factory.begin() as session:
            actor, paper = _actor_and_paper(session, paper_key="revision-unique")
            session.add_all(
                [
                    ObjectRevision(
                        object_id=paper.id,
                        revision_number=1,
                        actor_id=actor.id,
                        reason="first",
                        content_hash="a" * 64,
                        snapshot={},
                        workflow_state=WorkflowState.DRAFT,
                        is_current_published=False,
                    ),
                    ObjectRevision(
                        object_id=paper.id,
                        revision_number=1,
                        actor_id=actor.id,
                        reason="duplicate",
                        content_hash="b" * 64,
                        snapshot={},
                        workflow_state=WorkflowState.DRAFT,
                        is_current_published=False,
                    ),
                ]
            )


def test_only_one_current_published_revision_exists_per_object(
    auth_session_factory: sessionmaker[Session],
) -> None:
    with pytest.raises(IntegrityError):
        with auth_session_factory.begin() as session:
            actor, paper = _actor_and_paper(session, paper_key="published-unique")
            session.add_all(
                [
                    ObjectRevision(
                        object_id=paper.id,
                        revision_number=1,
                        actor_id=actor.id,
                        reason="published one",
                        content_hash="a" * 64,
                        snapshot={"title": "one"},
                        workflow_state=WorkflowState.PUBLISHED,
                        is_current_published=True,
                    ),
                    ObjectRevision(
                        object_id=paper.id,
                        revision_number=2,
                        actor_id=actor.id,
                        reason="published two",
                        content_hash="b" * 64,
                        snapshot={"title": "two"},
                        workflow_state=WorkflowState.PUBLISHED,
                        is_current_published=True,
                    ),
                ]
            )


def test_published_snapshot_cannot_be_updated_or_deleted(
    auth_session_factory: sessionmaker[Session],
) -> None:
    service = RevisionService()
    with auth_session_factory.begin() as session:
        actor, paper = _actor_and_paper(session, paper_key="immutable-published")
        revision = service.create_revision(
            session,
            object_identity=paper,
            actor_id=actor.id,
            reason="Initial publication",
            snapshot={"title": "Published title"},
            workflow_state=WorkflowState.PUBLISHED,
            is_current_published=True,
        )
        revision_id = revision.id

    with pytest.raises(DBAPIError, match="revision is immutable"):
        with auth_session_factory.begin() as session:
            session.execute(
                text(
                    "UPDATE object_revisions SET snapshot = :snapshot WHERE id = :id"
                ),
                {"snapshot": '{"title": "tampered"}', "id": revision_id},
            )
    with pytest.raises(DBAPIError, match="revision is immutable"):
        with auth_session_factory.begin() as session:
            session.execute(
                text("DELETE FROM object_revisions WHERE id = :id"),
                {"id": revision_id},
            )


def test_approved_baseline_revision_cannot_be_updated_or_deleted(
    auth_session_factory: sessionmaker[Session],
) -> None:
    service = RevisionService()
    with auth_session_factory.begin() as session:
        actor, paper = _actor_and_paper(session, paper_key="immutable-approved")
        revision = service.create_revision(
            session,
            object_identity=paper,
            actor_id=actor.id,
            reason="Authoritative baseline import",
            snapshot={"title": "Approved baseline"},
            workflow_state=WorkflowState.APPROVED,
            is_current_published=False,
        )
        revision_id = revision.id

    with pytest.raises(DBAPIError, match="revision is immutable"):
        with auth_session_factory.begin() as session:
            session.execute(
                text(
                    "UPDATE object_revisions SET snapshot = :snapshot WHERE id = :id"
                ),
                {"snapshot": '{"title": "tampered"}', "id": revision_id},
            )
    with pytest.raises(DBAPIError, match="revision is immutable"):
        with auth_session_factory.begin() as session:
            session.execute(
                text("DELETE FROM object_revisions WHERE id = :id"),
                {"id": revision_id},
            )


def test_new_publication_supersedes_pointer_without_mutating_old_snapshot(
    auth_session_factory: sessionmaker[Session],
) -> None:
    service = RevisionService()
    with auth_session_factory.begin() as session:
        actor, paper = _actor_and_paper(session, paper_key="supersede")
        first = service.create_revision(
            session,
            object_identity=paper,
            actor_id=actor.id,
            reason="Release one",
            snapshot={"title": "Version one"},
            workflow_state=WorkflowState.PUBLISHED,
            is_current_published=True,
        )
        second = service.create_revision(
            session,
            object_identity=paper,
            actor_id=actor.id,
            reason="Release two",
            snapshot={"title": "Version two"},
            predecessor=first,
            workflow_state=WorkflowState.PUBLISHED,
            is_current_published=True,
        )
        first_id = first.id
        second_id = second.id

    with auth_session_factory() as session:
        old = session.get(ObjectRevision, first_id)
        current = session.get(ObjectRevision, second_id)
        assert old is not None and current is not None
        assert old.workflow_state is WorkflowState.SUPERSEDED
        assert old.is_current_published is False
        assert old.snapshot == {"title": "Version one"}
        assert current.is_current_published is True


def test_region_bounds_and_page_are_constrained_in_postgresql(
    auth_session_factory: sessionmaker[Session],
) -> None:
    with pytest.raises(IntegrityError):
        with auth_session_factory.begin() as session:
            _, paper = _actor_and_paper(session, paper_key="region-bounds")
            session.add(
                VisualRegion(
                    paper_id=paper.id,
                    region_key="REGION-1",
                    asset_id=None,
                    page_number=0,
                )
            )

    service = RevisionService()
    with pytest.raises(IntegrityError):
        with auth_session_factory.begin() as session:
            actor, paper = _actor_and_paper(session, paper_key="region-geometry")
            region = VisualRegion(
                paper_id=paper.id,
                region_key="REGION-2",
                asset_id=None,
                page_number=1,
            )
            session.add(region)
            session.flush()
            service.create_revision(
                session,
                object_identity=region,
                actor_id=actor.id,
                reason="Invalid geometry",
                snapshot={"geometry": "invalid"},
                region_bounds=(0.8, 0.2, 0.4, 1.1),
            )


def test_lineage_edges_reject_self_loops_and_invalid_foreign_keys(
    auth_session_factory: sessionmaker[Session],
) -> None:
    with pytest.raises(IntegrityError):
        with auth_session_factory.begin() as session:
            _, paper = _actor_and_paper(session, paper_key="self-loop")
            compound = Compound(
                paper_id=paper.id,
                local_identity="1",
                display_label="1",
                normalized_label="1",
            )
            lineage = Lineage(paper_id=paper.id, lineage_key="LINEAGE-1")
            session.add_all([compound, lineage])
            session.flush()
            session.add(
                LineageEdge(
                    paper_id=paper.id,
                    lineage_id=lineage.id,
                    edge_key="EDGE-1",
                    parent_compound_id=compound.id,
                    derived_compound_id=compound.id,
                )
            )

    with pytest.raises(IntegrityError):
        with auth_session_factory.begin() as session:
            _, paper = _actor_and_paper(session, paper_key="dangling-edge")
            lineage = Lineage(paper_id=paper.id, lineage_key="LINEAGE-1")
            session.add(lineage)
            session.flush()
            session.add(
                LineageEdge(
                    paper_id=paper.id,
                    lineage_id=lineage.id,
                    edge_key="EDGE-DANGLING",
                    parent_compound_id=None,
                    derived_compound_id=uuid4(),
                )
            )


def test_structure_evidence_and_activity_states_are_independent(
    auth_session_factory: sessionmaker[Session],
) -> None:
    service = RevisionService()
    with auth_session_factory.begin() as session:
        actor, paper = _actor_and_paper(session, paper_key="domain-states")
        compound = Compound(
            paper_id=paper.id,
            local_identity="1",
            display_label="1",
            normalized_label="1",
        )
        session.add(compound)
        session.flush()
        structure = Structure(
            paper_id=paper.id,
            compound_id=compound.id,
            structure_key="STRUCT-1",
        )
        evidence = Evidence(paper_id=paper.id, evidence_key="EVID-1")
        activity = Activity(
            paper_id=paper.id,
            compound_id=compound.id,
            activity_key="ACT-1",
        )
        session.add_all([structure, evidence, activity])
        session.flush()
        structure_revision = service.create_revision(
            session,
            object_identity=structure,
            actor_id=actor.id,
            reason="Structure review",
            snapshot={"smiles": "CCO"},
            structure_state=StructureState.STRUCTURE_CONFIRMED,
            canonical_smiles="CCO",
        )
        evidence_revision = service.create_revision(
            session,
            object_identity=evidence,
            actor_id=actor.id,
            reason="Evidence review",
            snapshot={"text": "Compound 1 improved potency"},
            evidence_state=EvidenceState.CONFIRMED,
            evidence_text="Compound 1 improved potency",
        )
        activity_revision = service.create_revision(
            session,
            object_identity=activity,
            actor_id=actor.id,
            reason="Activity review",
            snapshot={"metric": "IC50", "value": "12", "unit": "nM"},
            activity_state=ActivityState.CONFIRMED,
            activity_metric="IC50",
            activity_value="12",
            activity_unit="nM",
        )

        assert structure_revision.structure_state is StructureState.STRUCTURE_CONFIRMED
        assert structure_revision.evidence_state is None
        assert evidence_revision.evidence_state is EvidenceState.CONFIRMED
        assert evidence_revision.activity_state is None
        assert activity_revision.activity_state is ActivityState.CONFIRMED
        assert activity_revision.structure_state is None


def test_revision_timestamps_are_timezone_aware(
    auth_session_factory: sessionmaker[Session],
) -> None:
    with auth_session_factory() as session:
        database_now = session.scalar(select(text("CURRENT_TIMESTAMP")))
    assert isinstance(database_now, datetime)
    assert database_now.tzinfo is not None
    assert database_now.astimezone(UTC).utcoffset().total_seconds() == 0


def test_long_searchable_evidence_text_does_not_hit_btree_index_limits(
    auth_session_factory: sessionmaker[Session],
) -> None:
    service = RevisionService()
    long_text = " ".join(f"distinct-evidence-token-{index}" for index in range(2000))

    with auth_session_factory.begin() as session:
        actor, paper = _actor_and_paper(session, paper_key="long-evidence")
        evidence = Evidence(paper_id=paper.id, evidence_key="EVID-LONG")
        session.add(evidence)
        session.flush()
        revision = service.create_revision(
            session,
            object_identity=evidence,
            actor_id=actor.id,
            reason="Preserve long source evidence",
            snapshot={"evidence_text": long_text},
            search_text=long_text,
            evidence_state=EvidenceState.SOURCE_BOUND,
            evidence_text=long_text,
        )

        assert revision.search_text == long_text
