from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.assets.models import Asset, AssetCategory, AssetIntegrityState
from app.chemistry.drawing import DrawingOptions
from app.chemistry.validation import SourceComparison
from app.compounds.models import Compound
from app.papers.models import Paper
from app.releases.models import Release
from app.revisions.models import StructureState
from app.reviews.models import Changeset, ChangesetItem, ReviewTask, ReviewTaskStatus
from app.security.policies import WorkflowState
from app.structures.service import (
    StructureDrawingService,
    StructureReviewService,
    StructureValidationError,
    StructureVersionConflict,
)
from app.users.models import UserRole
from app.users.service import UserService


def _seed_structure_review(session: Session) -> tuple[object, Paper, Compound, Changeset]:
    users = UserService()
    reviewer = users.create_user(
        session,
        username=f"structure-reviewer-{uuid4().hex[:8]}",
        display_name="Structure reviewer",
        role=UserRole.REVIEWER,
        initial_password="Structure password 2026!",
    )
    admin = users.create_user(
        session,
        username=f"structure-admin-{uuid4().hex[:8]}",
        display_name="Structure admin",
        role=UserRole.ADMIN,
        initial_password="Structure password 2026!",
    )
    paper = Paper(paper_key=f"structure-paper-{uuid4().hex[:8]}")
    session.add(paper)
    session.flush()
    compound = Compound(
        paper_id=paper.id,
        local_identity="26a",
        display_label="26a",
        normalized_label="26a",
    )
    release = Release(
        release_key=f"structure-release-{uuid4().hex[:8]}",
        title="Structure release",
        notes="",
        metrics={},
        published_by_id=admin.id,
        published_at=datetime.now(UTC),
        is_current=False,
        manifest_finalized=False,
    )
    session.add_all([compound, release])
    session.flush()
    task = ReviewTask(
        paper_id=paper.id,
        assigned_reviewer_id=reviewer.id,
        created_by_id=admin.id,
        status=ReviewTaskStatus.IN_PROGRESS,
        version=1,
    )
    session.add(task)
    session.flush()
    changeset = Changeset(
        review_task_id=task.id,
        paper_id=paper.id,
        owner_id=reviewer.id,
        base_release_id=release.id,
        title="Structure changes",
        reason="Verify source structure",
        workflow_state=WorkflowState.DRAFT,
        version=1,
    )
    session.add(changeset)
    session.flush()
    return reviewer, paper, compound, changeset


def test_structure_draft_creates_append_only_revision_and_detects_stale_writes(
    auth_session_factory: sessionmaker[Session],
) -> None:
    with auth_session_factory.begin() as session:
        reviewer, paper, compound, changeset = _seed_structure_review(session)
        service = StructureReviewService()
        structure, revision = service.create_structure(
            session,
            paper_id=paper.id,
            compound_id=compound.id,
            actor_id=reviewer.id,
            changeset_id=changeset.id,
            expected_version=1,
            structure_key="26a-main",
            smiles="C[C@H](O)Cl",
            structure_state=StructureState.SOURCE_BOUND_CANDIDATE,
            source="SI, Table S2",
            reason="Transcribed from the supporting information",
            source_comparison=SourceComparison.MATCH,
            source_verified=True,
        )

        assert structure.paper_id == paper.id
        assert revision.snapshot["canonical_isomeric_smiles"] == "C[C@H](O)Cl"
        assert revision.structure_state is StructureState.SOURCE_BOUND_CANDIDATE
        assert revision.canonical_smiles == "C[C@H](O)Cl"
        assert changeset.version == 2
        item = session.scalar(select(ChangesetItem).where(ChangesetItem.object_id == structure.id))
        assert item is not None and item.proposed_revision_id == revision.id

        with pytest.raises(StructureVersionConflict):
            service.update_structure(
                session,
                structure_id=structure.id,
                actor_id=reviewer.id,
                changeset_id=changeset.id,
                expected_version=1,
                smiles="CCO",
                structure_state=StructureState.PARSEABLE_CANDIDATE,
                source="Article, Figure 2",
                reason="Corrected transcription",
            )


def test_structure_confirmation_cannot_be_inferred_from_parseability(
    auth_session_factory: sessionmaker[Session],
) -> None:
    with auth_session_factory.begin() as session:
        reviewer, paper, compound, changeset = _seed_structure_review(session)
        with pytest.raises(StructureValidationError, match="not eligible"):
            StructureReviewService().create_structure(
                session,
                paper_id=paper.id,
                compound_id=compound.id,
                actor_id=reviewer.id,
                changeset_id=changeset.id,
                expected_version=1,
                structure_key="26a-unverified",
                smiles="CCO",
                structure_state=StructureState.STRUCTURE_CONFIRMED,
                source="Article, Figure 2",
                reason="RDKit parsed it",
            )


def test_drawing_job_reuses_one_verified_immutable_asset(
    tmp_path: Path,
    auth_session_factory: sessionmaker[Session],
) -> None:
    with auth_session_factory.begin() as session:
        reviewer, _, _, _ = _seed_structure_review(session)
        service = StructureDrawingService(tmp_path)
        first = service.draw(
            session,
            smiles="C1=CC=CC=C1",
            options=DrawingOptions(width=320, height=240),
            created_by_id=reviewer.id,
        )
        second = service.draw(
            session,
            smiles="c1ccccc1",
            options=DrawingOptions(width=320, height=240),
            created_by_id=reviewer.id,
        )

        assert first.asset.id == second.asset.id
        assert first.reused is False
        assert second.reused is True
        assert first.path.read_bytes().startswith(b"\x89PNG")
        asset = session.get(Asset, first.asset.id)
        assert asset is not None
        assert asset.category is AssetCategory.RDKIT_STRUCTURE
        assert asset.integrity_state is AssetIntegrityState.VERIFIED
        assert asset.sha256 == first.asset.sha256
        assert asset.derivation_metadata["drawing_key"] == first.drawing_key

        resized = service.draw(
            session,
            smiles="c1ccccc1",
            options=DrawingOptions(width=321, height=240),
            created_by_id=reviewer.id,
        )
        assert resized.asset.id != first.asset.id
