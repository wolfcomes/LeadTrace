from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.approvals.service import ApprovalService
from app.database import DatabaseResources
from app.main import create_app
from app.molecule_proposals.models import MoleculeProposal, MoleculeProposalDisposition
from app.molecule_proposals.service import MoleculeProposalReviewService
from app.papers.models import Paper
from app.releases.service import publish_approved_baseline
from app.reviews.attestations import PaperReviewScopeService
from app.reviews.completeness import QueueState
from app.reviews.models import PaperReviewScope
from app.reviews.service import ReviewService
from app.reviews.workspace import build_workspace, list_molecule_object_queue
from app.users.models import UserRole
from app.users.service import UserService
from app.visual_objects.models import VisualObject, VisualRegion
from app.visual_objects.bindings import BindingService
from app.visual_objects.models import VisualObjectRegionBinding
from tests.releases.test_baseline_publish import (
    _approve,
    _asset_store,
    _import_candidate,
)
from tests.reviews.test_api import PASSWORD, _login, _settings


pytest_plugins = ("tests.imports.conftest",)


def seed_scientific_review(
    session,
    *,
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    start_changeset: bool,
) -> dict[str, object]:
    admin, candidate = _import_candidate(session, tmp_path, baseline_fixture)
    _approve(session, admin, candidate)
    published = publish_approved_baseline(
        session,
        candidate_id=candidate.id,
        actor_id=admin.id,
        idempotency_key=f"workspace-{uuid4()}",
        asset_store=_asset_store(tmp_path, baseline_fixture),
    )
    reviewer = UserService().create_user(
        session,
        username=f"workspace-reviewer-{uuid4().hex[:8]}",
        display_name="Scientific Reviewer",
        role=UserRole.REVIEWER,
        initial_password=PASSWORD,
    )
    reviewer.must_change_password = False
    other = UserService().create_user(
        session,
        username=f"workspace-other-{uuid4().hex[:8]}",
        display_name="Other Reviewer",
        role=UserRole.REVIEWER,
        initial_password=PASSWORD,
    )
    other.must_change_password = False
    visitor = UserService().create_user(
        session,
        username=f"workspace-visitor-{uuid4().hex[:8]}",
        display_name="Workspace Visitor",
        role=UserRole.VISITOR,
        initial_password=PASSWORD,
    )
    visitor.must_change_password = False
    paper = session.scalar(select(Paper))
    visual_object = session.scalar(select(VisualObject))
    region = session.scalar(select(VisualRegion))
    proposal = session.scalar(select(MoleculeProposal))
    assert paper is not None
    assert visual_object is not None
    assert region is not None
    assert proposal is not None
    task = ReviewService().create_task(
        session,
        paper_id=paper.id,
        assignee_id=reviewer.id,
        created_by_id=admin.id,
        priority=80,
    )
    changeset = None
    if start_changeset:
        changeset = ReviewService().create_changeset(
            session,
            paper_id=paper.id,
            actor_id=reviewer.id,
            review_task_id=task.id,
            base_release_id=published.release.id,
            title="Scientific Paper review",
            reason="Review every required object and its source evidence",
        )
    return {
        "admin": admin,
        "reviewer": reviewer,
        "other": other,
        "visitor": visitor,
        "paper": paper,
        "visual_object": visual_object,
        "region": region,
        "proposal": proposal,
        "task": task,
        "changeset": changeset,
        "release": published.release,
    }


def test_workspace_returns_one_safe_version_consistent_scientific_projection(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    postgresql_database_url: str,
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        seeded = seed_scientific_review(
            session,
            tmp_path=tmp_path,
            baseline_fixture=baseline_fixture,
            start_changeset=True,
        )
        changeset_id = seeded["changeset"].id
        reviewer_username = seeded["reviewer"].username
        other_username = seeded["other"].username
        visitor_username = seeded["visitor"].username
        paper_id = seeded["paper"].id
        release_id = seeded["release"].id
        visual_object_id = seeded["visual_object"].id
        proposal_id = seeded["proposal"].id
        region_id = seeded["region"].id
        base_binding = session.scalar(
            select(VisualObjectRegionBinding).where(
                VisualObjectRegionBinding.visual_object_id == visual_object_id,
                VisualObjectRegionBinding.changeset_id.is_(None),
            )
        )
        assert base_binding is not None
        BindingService().update_region(
            session,
            binding_id=base_binding.id,
            changeset_id=changeset_id,
            actor_id=seeded["reviewer"].id,
            expected_version=1,
            role="corrected_source",
            note="Confirmed against the whole PDF page",
        )

    resources = DatabaseResources(
        engine=auth_session_factory.kw["bind"],
        session_factory=auth_session_factory,
    )
    application = create_app(
        settings=_settings(tmp_path / "managed", postgresql_database_url),
        database_probe=lambda _: True,
        database_bootstrap=lambda _: resources,
    )
    with TestClient(application) as client:
        _login(client, reviewer_username)
        response = client.get(
            f"/api/v1/review/changesets/{changeset_id}/workspace"
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["workspace_version"] == payload["changeset"]["version"] == 2
        assert payload["paper"]["id"] == str(paper_id)
        assert payload["paper"]["base_release_id"] == str(release_id)
        assert payload["document"] == {
            "url": (
                f"/api/v1/papers/{paper_id}/source-pdf"
                f"?kind=article&release_id={release_id}"
            ),
            "release_id": str(release_id),
        }
        assert payload["pages"] == [
            {
                "page_number": 1,
                "region_count": 1,
                "visual_object_count": 1,
                "proposal_count": 1,
                "blocker_count": 1,
            }
        ]
        assert payload["regions"][0]["id"] == str(region_id)
        assert payload["regions"][0]["is_tombstone"] is False
        assert payload["regions"][0]["bounds"] == {
            "x0": 0.25,
            "y0": 0.3125,
            "x1": 5 / 12,
            "y1": 0.4375,
        }
        assert payload["visual_objects"][0]["id"] == str(visual_object_id)
        assert payload["visual_objects"][0]["queue_state"] == "proposal_review"
        assert payload["visual_objects"][0]["bindings"]["regions"][0]["role"] == (
            "corrected_source"
        )
        assert payload["molecule_proposals"][0]["id"] == str(proposal_id)
        assert payload["molecule_proposals"][0]["disposition"] == "pending"
        assert payload["molecule_proposals"][0]["crop_asset"]["url"].startswith(
            "/api/v1/assets/"
        )
        assert len(payload["structures"]) == 2
        assert payload["source_locators"] == [
            {
                "visual_object_id": str(visual_object_id),
                "region_id": str(region_id),
                "page_number": 1,
                "bounds": payload["regions"][0]["bounds"],
                "source_asset_id": payload["regions"][0]["asset_id"],
                "crop_asset_id": payload["molecule_proposals"][0]["crop_asset"]["id"],
            }
        ]
        assert payload["progress"]["scope_count"] == 12
        assert payload["progress"]["resolved_count"] == 11
        assert payload["progress"]["blocker_count"] == 1
        assert payload["progress"]["by_kind"]["molecule_proposal"] == {
            "total": 1,
            "resolved": 0,
            "blockers": 1,
        }
        assert payload["attestation"] is None

        serialized = response.text
        assert str(baseline_fixture["workspace"]) not in serialized
        assert "storage_key" not in serialized
        assert "crop_path" not in serialized
        assert "source_pdf\"" not in serialized

        _login(client, other_username)
        assert (
            client.get(
                f"/api/v1/review/changesets/{changeset_id}/workspace"
            ).status_code
            == 404
        )
        _login(client, visitor_username)
        assert (
            client.get(
                f"/api/v1/review/changesets/{changeset_id}/workspace"
            ).status_code
            == 403
        )

    with auth_session_factory() as session:
        scope = session.scalar(
            select(PaperReviewScope).where(
                PaperReviewScope.changeset_id == UUID(str(changeset_id))
            )
        )
        assert scope is not None


def test_missing_crop_is_a_shared_workspace_and_attestation_blocker(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        seeded = seed_scientific_review(
            session,
            tmp_path=tmp_path,
            baseline_fixture=baseline_fixture,
            start_changeset=True,
        )
        changeset = seeded["changeset"]
        proposal = seeded["proposal"]
        assert changeset is not None
        scope = PaperReviewScopeService.ensure_scope(
            session,
            changeset=changeset,
            actor_id=seeded["reviewer"].id,
        )
        proposal.crop_asset_id = None
        MoleculeProposalReviewService().update(
            session,
            paper_id=seeded["paper"].id,
            proposal_id=proposal.id,
            actor_id=seeded["reviewer"].id,
            changeset_id=changeset.id,
            expected_version=changeset.version,
            disposition=MoleculeProposalDisposition.REJECTED,
            rationale="The crop does not depict a molecule.",
        )

        progress = PaperReviewScopeService.progress(
            session,
            changeset=changeset,
            scope=scope,
        )
        proposal_index = next(
            index
            for index, item in enumerate(scope.snapshot["items"])
            if item["object_id"] == str(proposal.id)
        )

        assert progress.states[proposal_index].state is QueueState.SOURCE_OR_ATTACHMENT
        assert progress.blocker_count == 1
        workspace = build_workspace(
            session,
            changeset_id=changeset.id,
            actor_id=seeded["reviewer"].id,
            is_admin=False,
        )
        assert workspace["progress"]["blocker_count"] == 1
        queue = list_molecule_object_queue(
            session,
            actor_id=seeded["reviewer"].id,
            is_admin=False,
        )
        assert queue["items"][0]["state"] == QueueState.SOURCE_OR_ATTACHMENT.value


def test_admin_scientific_evidence_includes_attested_proposal_source_context(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        seeded = seed_scientific_review(
            session,
            tmp_path=tmp_path,
            baseline_fixture=baseline_fixture,
            start_changeset=True,
        )
        changeset = seeded["changeset"]
        proposal = seeded["proposal"]
        assert changeset is not None
        scope = PaperReviewScopeService.ensure_scope(
            session,
            changeset=changeset,
            actor_id=seeded["reviewer"].id,
        )
        MoleculeProposalReviewService().update(
            session,
            paper_id=seeded["paper"].id,
            proposal_id=proposal.id,
            actor_id=seeded["reviewer"].id,
            changeset_id=changeset.id,
            expected_version=changeset.version,
            disposition=MoleculeProposalDisposition.REJECTED,
            rationale="The candidate is not a chemical structure.",
        )
        _, attestation, _ = PaperReviewScopeService.attest(
            session,
            changeset=changeset,
            actor_id=seeded["reviewer"].id,
            expected_version=changeset.version,
            scope_hash=scope.scope_hash,
            statement="I reviewed every required Paper item against its source.",
        )
        ReviewService().submit_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=seeded["reviewer"].id,
            expected_version=changeset.version,
        )

        evidence = ApprovalService().scientific_evidence(
            session,
            changeset.id,
            changed_only=True,
        )

        assert evidence["scope"] == {
            "id": str(scope.id),
            "scope_hash": scope.scope_hash,
            "item_count": 12,
        }
        assert evidence["attestation"]["id"] == str(attestation.id)
        assert evidence["progress"] == {
            "scope_count": 12,
            "resolved_count": 12,
            "blocker_count": 0,
        }
        assert len(evidence["molecule_proposals"]) == 1
        proposal_evidence = evidence["molecule_proposals"][0]
        assert proposal_evidence["object_id"] == str(proposal.id)
        assert proposal_evidence["before_disposition"] == "pending"
        assert proposal_evidence["after_disposition"] == "rejected"
        assert proposal_evidence["after"]["review"]["rationale"] == (
            "The candidate is not a chemical structure."
        )
        assert len(evidence["source_context"]) == 1
        source_context = evidence["source_context"][0]
        assert source_context["proposal_id"] == str(proposal.id)
        assert source_context["visual_object_id"] == str(
            seeded["visual_object"].id
        )
        assert source_context["region"]["id"] == str(seeded["region"].id)
        assert source_context["region"]["page_number"] == 1
        assert source_context["crop_asset"]["url"].startswith("/api/v1/assets/")
        assert source_context["source_asset"]["url"].startswith(
            "/api/v1/assets/"
        )
        serialized = str(evidence)
        assert str(baseline_fixture["workspace"]) not in serialized
        assert "storage_key" not in serialized
        assert "crop_path" not in serialized
