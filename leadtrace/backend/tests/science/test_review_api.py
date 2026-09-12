from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.database import DatabaseResources
from app.main import create_app
from app.papers.models import Paper
from app.releases.models import Release
from app.reviews.models import Changeset, ReviewTask, ReviewTaskStatus
from app.security.policies import WorkflowState
from app.users.models import UserRole
from app.users.service import UserService


PASSWORD = "Scientific API password 2026!"


def _seed(session) -> dict[str, object]:
    users = UserService()
    reviewer = users.create_user(session, username=f"science-api-reviewer-{uuid4().hex[:8]}", display_name="Science API reviewer", role=UserRole.REVIEWER, initial_password=PASSWORD)
    visitor = users.create_user(session, username=f"science-api-visitor-{uuid4().hex[:8]}", display_name="Science API visitor", role=UserRole.VISITOR, initial_password=PASSWORD)
    reviewer.must_change_password = False
    visitor.must_change_password = False
    paper = Paper(paper_key=f"science-api-paper-{uuid4().hex[:8]}")
    session.add(paper)
    session.flush()
    release = Release(release_key=f"science-api-release-{uuid4().hex[:8]}", title="Science API release", notes="", metrics={}, published_by_id=reviewer.id, published_at=datetime.now(UTC), is_current=False, manifest_finalized=False)
    session.add(release)
    session.flush()
    task = ReviewTask(paper_id=paper.id, assigned_reviewer_id=reviewer.id, created_by_id=reviewer.id, status=ReviewTaskStatus.IN_PROGRESS, version=1)
    session.add(task)
    session.flush()
    changeset = Changeset(review_task_id=task.id, paper_id=paper.id, owner_id=reviewer.id, base_release_id=release.id, title="Science API changes", reason="Review science", workflow_state=WorkflowState.DRAFT, version=1)
    session.add(changeset)
    session.flush()
    return {"paper": paper, "reviewer": reviewer, "visitor": visitor, "changeset": changeset}


def _login(client: TestClient, username: str) -> str:
    client.cookies.clear()
    response = client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_science_review_api_enforces_scope_csrf_and_revision_conflicts(
    tmp_path: Path,
    postgresql_database_url: str,
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        seeded = _seed(session)
    resources = DatabaseResources(engine=auth_session_factory.kw["bind"], session_factory=auth_session_factory)
    settings = Settings(_env_file=None, environment="test", database_url=postgresql_database_url, session_secret="science-api-session-secret-more-than-thirty-two-characters", allowed_hosts=["testserver"], asset_root=tmp_path / "assets")
    application = create_app(settings=settings, database_probe=lambda _: True, database_bootstrap=lambda _: resources)
    paper_id = str(seeded["paper"].id)
    changeset_id = str(seeded["changeset"].id)
    with TestClient(application) as client:
        _login(client, seeded["visitor"].username)
        denied = client.get(f"/api/v1/papers/{paper_id}/compounds")
        assert denied.status_code == 403
        reviewer_csrf = _login(client, seeded["reviewer"].username)
        missing_csrf = client.post(f"/api/v1/papers/{paper_id}/compounds", json={"local_identity": "26b", "display_label": "26b", "reason": "source", "changeset_id": changeset_id, "expected_version": 1})
        assert missing_csrf.status_code == 403
        created = client.post(f"/api/v1/papers/{paper_id}/compounds", headers={"X-CSRF-Token": reviewer_csrf}, json={"local_identity": "26b", "display_label": "26b", "reason": "source", "changeset_id": changeset_id, "expected_version": 1})
        assert created.status_code == 201
        compound_id = created.json()["id"]
        duplicate = client.post(f"/api/v1/papers/{paper_id}/compounds", headers={"X-CSRF-Token": reviewer_csrf}, json={"local_identity": "26b", "display_label": "duplicate", "reason": "source", "changeset_id": changeset_id, "expected_version": 2})
        assert duplicate.status_code == 422
        stale = client.patch(f"/api/v1/papers/{paper_id}/compounds/{compound_id}", headers={"X-CSRF-Token": reviewer_csrf}, json={"local_identity": "26b", "display_label": "stale", "reason": "source", "changeset_id": changeset_id, "expected_version": 1})
        assert stale.status_code == 409
        assert stale.json()["code"] == "REVISION_CONFLICT"
        evidence = client.post(f"/api/v1/papers/{paper_id}/evidence", headers={"X-CSRF-Token": reviewer_csrf}, json={"evidence_key": "ev-1", "original_text": "Original sentence", "source_locator": "Table 2", "compound_ids": [compound_id], "reason": "bind", "changeset_id": changeset_id, "expected_version": 2})
        assert evidence.status_code == 201
        lineage = client.post(f"/api/v1/papers/{paper_id}/lineages", headers={"X-CSRF-Token": reviewer_csrf}, json={"lineage_key": "series-a", "reason": "bind lineage", "changeset_id": changeset_id, "expected_version": 3})
        assert lineage.status_code == 201
        edge = client.post(f"/api/v1/papers/{paper_id}/lineages/{lineage.json()['id']}/edges", headers={"X-CSRF-Token": reviewer_csrf}, json={"edge_key": "edge-1", "parent_compound_id": None, "derived_compound_id": compound_id, "relation_type": "optimization", "relation_status": "unresolved", "evidence_ids": [evidence.json()["id"]], "reason": "bind edge", "changeset_id": changeset_id, "expected_version": 4})
        assert edge.status_code == 201
        readiness = client.get(f"/api/v1/papers/{paper_id}/lineage-edges/{edge.json()['id']}/pair-readiness")
        assert readiness.status_code == 200
        assert readiness.json()["eligible"] is False
        assert "UNRESOLVED_PARENT" in readiness.json()["blocking_codes"]
        forbidden_field = client.post(f"/api/v1/papers/{paper_id}/lineages/{lineage.json()['id']}/edges", headers={"X-CSRF-Token": reviewer_csrf}, json={"edge_key": "edge-2", "parent_compound_id": None, "derived_compound_id": compound_id, "relation_type": "optimization", "relation_status": "unresolved", "evidence_ids": [], "pair_ready": True, "reason": "bind edge", "changeset_id": changeset_id, "expected_version": 5})
        assert forbidden_field.status_code == 422
