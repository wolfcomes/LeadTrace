from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.activities.models import Activity
from app.compounds.models import Compound
from app.config import Settings
from app.database import DatabaseResources
from app.evidence.models import Evidence
from app.lineages.models import Lineage, LineageEdge
from app.main import create_app
from app.papers.models import Paper
from app.releases.models import Release, ReleaseItem
from app.revisions.models import (
    ActivityState,
    EvidenceState,
    ObjectRevision,
    RevisionedObject,
    StructureState,
)
from app.security.policies import WorkflowState
from app.structures.models import Structure
from app.users.models import UserRole
from app.users.service import UserService


PASSWORD = "Published API visitor password 2026!"


@dataclass(frozen=True, slots=True)
class PublishedApiFixture:
    client: TestClient
    session_factory: sessionmaker[Session]
    release_id: UUID
    release_key: str
    ordered_paper_ids: tuple[UUID, ...]
    ordered_paper_keys: tuple[str, ...]
    detail_paper_id: UUID
    published_revision_id: UUID
    draft_revision_id: UUID
    unpublished_paper_id: UUID


def _content_hash(snapshot: dict[str, object]) -> str:
    content = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _revision(
    domain_object: RevisionedObject,
    *,
    actor_id: UUID,
    revision_number: int,
    snapshot: dict[str, object],
    workflow_state: WorkflowState = WorkflowState.PUBLISHED,
    predecessor_id: UUID | None = None,
) -> ObjectRevision:
    return ObjectRevision(
        object_id=domain_object.id,
        revision_number=revision_number,
        predecessor_id=predecessor_id,
        actor_id=actor_id,
        reason="Published API fixture",
        content_hash=_content_hash(snapshot),
        search_text=" ".join(
            str(value)
            for value in snapshot.get("normalized_values", {}).values()
            if value
        ),
        snapshot=snapshot,
        workflow_state=workflow_state,
        is_current_published=workflow_state is WorkflowState.PUBLISHED,
        is_tombstone=False,
    )


def _paper_snapshot(index: int, title: str) -> dict[str, object]:
    return {
        "record_type": "paper",
        "original_id": f"paper-{index:02d}",
        "source": {
            "file": f"/private/source/paper-{index:02d}.csv",
            "row_locator": f"row={index + 2}",
            "sha256": "f" * 64,
        },
        "raw_values": {
            "source_pdf": f"/private/source/paper-{index:02d}.pdf",
        },
        "normalized_values": {
            "paper_id": f"paper-{index:02d}",
            "title_guess": title,
            "filename_year": "2026",
            "target": "Kinase A" if index % 2 == 0 else "Protease B",
            "review_status": "unreviewed",
            "source_pdf": f"/private/source/paper-{index:02d}.pdf",
        },
    }


def _add_release_item(
    session: Session,
    release: Release,
    domain_object: RevisionedObject,
    revision: ObjectRevision,
    *,
    paper_id: UUID,
    manifest_order: int,
) -> None:
    session.add(
        ReleaseItem(
            release_id=release.id,
            object_id=domain_object.id,
            revision_id=revision.id,
            paper_id=paper_id,
            object_kind=domain_object.object_kind,
            manifest_order=manifest_order,
        )
    )


def _add_detail_objects(
    session: Session,
    release: Release,
    paper: Paper,
    actor_id: UUID,
) -> None:
    parent = Compound(
        paper_id=paper.id,
        local_identity="CMP-PARENT",
        display_label="26a′",
        normalized_label="26a′",
    )
    derived = Compound(
        paper_id=paper.id,
        local_identity="CMP-DERIVED",
        display_label="26b",
        normalized_label="26b",
    )
    session.add_all([parent, derived])
    session.flush()
    parent_revision = _revision(
        parent,
        actor_id=actor_id,
        revision_number=1,
        snapshot={"normalized_values": {"display_label": "26a′"}},
    )
    derived_revision = _revision(
        derived,
        actor_id=actor_id,
        revision_number=1,
        snapshot={"normalized_values": {"display_label": "26b"}},
    )
    session.add_all([parent_revision, derived_revision])
    session.flush()

    lineage = Lineage(paper_id=paper.id, lineage_key="LINEAGE-1")
    structure = Structure(
        paper_id=paper.id,
        compound_id=derived.id,
        structure_key="STRUCTURE-1",
    )
    evidence = Evidence(paper_id=paper.id, evidence_key="EVIDENCE-1")
    activity = Activity(
        paper_id=paper.id,
        compound_id=derived.id,
        activity_key="ACTIVITY-1",
    )
    session.add_all([lineage, structure, evidence, activity])
    session.flush()
    edge = LineageEdge(
        paper_id=paper.id,
        lineage_id=lineage.id,
        edge_key="EDGE-1",
        parent_compound_id=parent.id,
        derived_compound_id=derived.id,
    )
    session.add(edge)
    session.flush()

    lineage_revision = _revision(
        lineage,
        actor_id=actor_id,
        revision_number=1,
        snapshot={"normalized_values": {"lineage_id": "LINEAGE-1"}},
    )
    structure_revision = _revision(
        structure,
        actor_id=actor_id,
        revision_number=1,
        snapshot={"normalized_values": {"compound_label": "26b"}},
    )
    structure_revision.structure_state = StructureState.STRUCTURE_CONFIRMED
    structure_revision.canonical_smiles = "CCN"
    evidence_revision = _revision(
        evidence,
        actor_id=actor_id,
        revision_number=1,
        snapshot={"normalized_values": {"evidence_text": "Potency improved."}},
    )
    evidence_revision.evidence_state = EvidenceState.CONFIRMED
    evidence_revision.evidence_text = "Potency improved."
    activity_revision = _revision(
        activity,
        actor_id=actor_id,
        revision_number=1,
        snapshot={"normalized_values": {"qualifier": "="}},
    )
    activity_revision.activity_state = ActivityState.CONFIRMED
    activity_revision.activity_metric = "IC50"
    activity_revision.activity_value = "12"
    activity_revision.activity_unit = "nM"
    edge_revision = _revision(
        edge,
        actor_id=actor_id,
        revision_number=1,
        snapshot={"normalized_values": {"pair_eligible": "yes"}},
    )
    edge_revision.relation_type = "direct_optimization"
    edge_revision.relation_status = "text_explicit"
    revisions = [
        lineage_revision,
        structure_revision,
        evidence_revision,
        activity_revision,
        edge_revision,
    ]
    session.add_all(revisions)
    session.flush()

    objects_and_revisions = [
        (parent, parent_revision),
        (derived, derived_revision),
        (lineage, lineage_revision),
        (structure, structure_revision),
        (evidence, evidence_revision),
        (activity, activity_revision),
        (edge, edge_revision),
    ]
    for offset, (domain_object, revision) in enumerate(objects_and_revisions, 100):
        _add_release_item(
            session,
            release,
            domain_object,
            revision,
            paper_id=paper.id,
            manifest_order=offset,
        )


@pytest.fixture
def published_api(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> Iterator[PublishedApiFixture]:
    with auth_session_factory.begin() as session:
        visitor = UserService().create_user(
            session,
            username="published.visitor",
            display_name="Published Visitor",
            role=UserRole.VISITOR,
            initial_password=PASSWORD,
        )
        visitor.must_change_password = False
        admin = UserService().create_user(
            session,
            username="published.admin",
            display_name="Published Admin",
            role=UserRole.ADMIN,
            initial_password=PASSWORD,
        )
        admin.must_change_password = False
        release = Release(
            release_key="baseline-2026-09-11",
            title="LeadTrace verified baseline",
            notes="Published API fixture",
            metrics={
                "corpus": {"numerator": 672, "denominator": 672, "unit": "papers"},
                "lineage": {"numerator": 138, "denominator": 672, "unit": "papers"},
                "relation": {"numerator": 4144, "denominator": 4144, "unit": "edges"},
                "structure": {"numerator": 4011, "denominator": 4301, "unit": "compounds"},
                "pair": {"numerator": 1730, "denominator": 4144, "unit": "edges"},
                "human_review": {"numerator": 0, "denominator": 672, "unit": "papers"},
            },
            published_by_id=admin.id,
            published_at=datetime(2026, 9, 11, 1, 0, tzinfo=UTC),
            is_current=True,
        )
        session.add(release)
        session.flush()

        papers: list[Paper] = []
        published_revisions: list[ObjectRevision] = []
        for index in range(25):
            paper = Paper(
                paper_key=f"paper-{index:02d}",
                doi=f"10.1000/paper-{index:02d}",
            )
            session.add(paper)
            session.flush()
            revision = _revision(
                paper,
                actor_id=admin.id,
                revision_number=1,
                snapshot=_paper_snapshot(
                    index,
                    f"Published optimization study {index:02d}",
                ),
            )
            session.add(revision)
            session.flush()
            _add_release_item(
                session,
                release,
                paper,
                revision,
                paper_id=paper.id,
                manifest_order=24 - index,
            )
            papers.append(paper)
            published_revisions.append(revision)

        detail_paper = papers[24]
        published_revision = published_revisions[24]
        draft_snapshot = _paper_snapshot(24, "SECRET newer draft title")
        draft_revision = _revision(
            detail_paper,
            actor_id=admin.id,
            revision_number=2,
            snapshot=draft_snapshot,
            workflow_state=WorkflowState.DRAFT,
            predecessor_id=published_revision.id,
        )
        draft_revision.is_current_published = False
        session.add(draft_revision)

        unpublished_paper = Paper(
            paper_key="unpublished-paper",
            doi="10.1000/unpublished",
        )
        session.add(unpublished_paper)
        session.flush()
        session.add(
            _revision(
                unpublished_paper,
                actor_id=admin.id,
                revision_number=1,
                snapshot=_paper_snapshot(99, "Hidden draft"),
                workflow_state=WorkflowState.DRAFT,
            )
        )
        _add_detail_objects(session, release, detail_paper, admin.id)
        session.flush()

        ordered = list(reversed(papers))
        ordered_paper_ids = tuple(paper.id for paper in ordered)
        ordered_paper_keys = tuple(paper.paper_key for paper in ordered)
        release_id = release.id
        draft_revision_id = draft_revision.id
        published_revision_id = published_revision.id
        unpublished_paper_id = unpublished_paper.id

    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=empty_postgresql_database_url,
        redis_url="redis://127.0.0.1:6379/0",
        session_secret="published-api-secret-more-than-thirty-two-characters",
        allowed_hosts=["testserver"],
        asset_root=tmp_path / "assets",
    )
    resources = DatabaseResources(
        engine=auth_session_factory.kw["bind"],
        session_factory=auth_session_factory,
    )
    application = create_app(
        settings=settings,
        database_probe=lambda _: True,
        database_bootstrap=lambda _: resources,
    )
    with TestClient(application) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "published.visitor", "password": PASSWORD},
        )
        assert login.status_code == 200
        yield PublishedApiFixture(
            client=client,
            session_factory=auth_session_factory,
            release_id=release_id,
            release_key="baseline-2026-09-11",
            ordered_paper_ids=ordered_paper_ids,
            ordered_paper_keys=ordered_paper_keys,
            detail_paper_id=detail_paper.id,
            published_revision_id=published_revision_id,
            draft_revision_id=draft_revision_id,
            unpublished_paper_id=unpublished_paper_id,
        )
