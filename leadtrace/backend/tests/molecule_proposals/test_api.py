from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.audit.models import AuditEvent
from app.compounds.models import Compound
from app.database import DatabaseResources
from app.main import create_app
from app.molecule_proposals.models import MoleculeProposal
from app.papers.models import Paper
from app.releases.models import Release
from app.revisions.models import ObjectRevision, ObjectKind
from app.reviews.models import Changeset, ReviewTask, ReviewTaskStatus
from app.security.policies import WorkflowState
from app.users.models import UserRole
from app.users.service import UserService
from app.visual_objects.models import VisualObject


PASSWORD = "Proposal API password 2026!"


def _seed(session) -> dict[str, object]:
    users = UserService()
    result: dict[str, object] = {}
    for label, role in (("reviewer", UserRole.REVIEWER), ("unassigned", UserRole.REVIEWER), ("visitor", UserRole.VISITOR), ("admin", UserRole.ADMIN)):
        user = users.create_user(session, username=f"proposal-api-{label}-{uuid4().hex[:8]}", display_name=label, role=role, initial_password=PASSWORD)
        user.must_change_password = False
        result[label] = user
    paper = Paper(paper_key=f"proposal-api-paper-{uuid4().hex[:8]}")
    session.add(paper)
    session.flush()
    release = Release(release_key=f"proposal-api-release-{uuid4().hex[:8]}", title="Proposal API", notes="", metrics={}, published_by_id=result["admin"].id, published_at=datetime.now(UTC), is_current=False, manifest_finalized=False)
    task = ReviewTask(paper_id=paper.id, assigned_reviewer_id=result["reviewer"].id, created_by_id=result["admin"].id, status=ReviewTaskStatus.IN_PROGRESS, version=1)
    visual = VisualObject(paper_id=paper.id, object_key="obj-1", object_type="complete_molecule")
    compound = Compound(paper_id=paper.id, local_identity="1", display_label="1", normalized_label="1")
    session.add(release)
    session.flush()
    session.add(task)
    session.flush()
    changeset = Changeset(review_task_id=task.id, paper_id=paper.id, owner_id=result["reviewer"].id, base_release_id=release.id, title="Proposal review", reason="Review OCSR", workflow_state=WorkflowState.DRAFT, version=1)
    session.add(changeset)
    session.add_all([visual, compound])
    session.flush()
    proposal = MoleculeProposal(paper_id=paper.id, visual_object_id=visual.id, proposal_key="p1", model_run_key="run-1")
    session.add(proposal)
    session.flush()
    revision = ObjectRevision(object_id=proposal.id, revision_number=1, actor_id=result["admin"].id, reason="baseline", content_hash="a" * 64, snapshot={"record_type": "molecule_proposal", "raw_values": {"raw_smiles": "CCO", "model_version": "ocsr-v1"}, "normalized_values": {"raw_smiles": "CCO"}}, workflow_state=WorkflowState.APPROVED, proposal_disposition="pending")
    session.add(revision)
    session.flush()
    result.update(paper=paper, proposal=proposal, changeset=changeset, compound=compound)
    return result


def _login(client: TestClient, username: str) -> str:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_molecule_proposal_api_is_scoped_and_typed(tmp_path: Path, postgresql_database_url: str, auth_session_factory) -> None:
    with auth_session_factory.begin() as session:
        seeded = _seed(session)
    resources = DatabaseResources(engine=auth_session_factory.kw["bind"], session_factory=auth_session_factory)
    settings = Settings(_env_file=None, environment="test", database_url=postgresql_database_url, session_secret="proposal-api-session-secret-more-than-thirty-two-characters", allowed_hosts=["testserver"], asset_root=tmp_path / "assets")
    application = create_app(settings=settings, database_probe=lambda _: True, database_bootstrap=lambda _: resources)
    paper_id = str(seeded["paper"].id)
    proposal_id = str(seeded["proposal"].id)
    with TestClient(application) as client:
        visitor_csrf = _login(client, seeded["visitor"].username)
        denied = client.get(f"/api/v1/papers/{paper_id}/molecule-proposals", headers={"X-CSRF-Token": visitor_csrf})
        assert denied.status_code == 403
        unassigned_csrf = _login(client, seeded["unassigned"].username)
        hidden = client.get(f"/api/v1/papers/{paper_id}/molecule-proposals", headers={"X-CSRF-Token": unassigned_csrf})
        assert hidden.status_code == 404
        reviewer_csrf = _login(client, seeded["reviewer"].username)
        listed = client.get(f"/api/v1/papers/{paper_id}/molecule-proposals", headers={"X-CSRF-Token": reviewer_csrf})
        assert listed.status_code == 200
        assert listed.json()[0]["machine"]["raw_values"]["raw_smiles"] == "CCO"
        assert "storage_key" not in listed.text
        rejected = client.patch(f"/api/v1/papers/{paper_id}/molecule-proposals/{proposal_id}", headers={"X-CSRF-Token": reviewer_csrf}, json={"changeset_id": str(seeded["changeset"].id), "expected_version": 1, "disposition": "rejected"})
        assert rejected.status_code == 422
        accepted = client.patch(f"/api/v1/papers/{paper_id}/molecule-proposals/{proposal_id}", headers={"X-CSRF-Token": reviewer_csrf}, json={"changeset_id": str(seeded["changeset"].id), "expected_version": 1, "disposition": "accepted", "reviewed_smiles": "CCO", "compound_id": str(seeded["compound"].id), "source_comparison": "match", "source_verified": True})
        assert accepted.status_code == 200
        assert accepted.json()["disposition"] == "accepted"
        assert accepted.json()["changeset_version"] == 2
        assert accepted.json()["machine"]["raw_values"]["raw_smiles"] == "CCO"
    with auth_session_factory.begin() as session:
        assert session.scalar(
            select(AuditEvent.id).where(
                AuditEvent.action == "review.molecule_proposal.updated",
                AuditEvent.target_id == seeded["proposal"].id,
            )
        ) is not None
