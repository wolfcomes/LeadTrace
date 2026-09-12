from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.database import DatabaseResources
from app.main import create_app
from app.compounds.models import Compound
from app.papers.models import Paper
from app.releases.models import Release
from app.reviews.models import Changeset, ReviewTask, ReviewTaskStatus
from app.security.policies import WorkflowState
from app.users.models import UserRole
from app.users.service import UserService


PASSWORD = "Structure API password 2026!"


def _seed(session) -> dict[str, object]:
    users = UserService()
    result: dict[str, object] = {}
    for label, role in (("reviewer", UserRole.REVIEWER), ("visitor", UserRole.VISITOR), ("admin", UserRole.ADMIN)):
        user = users.create_user(
            session,
            username=f"structure-api-{label}-{uuid4().hex[:8]}",
            display_name=f"Structure {label}",
            role=role,
            initial_password=PASSWORD,
        )
        user.must_change_password = False
        result[label] = user
    paper = Paper(paper_key=f"structure-api-paper-{uuid4().hex[:8]}")
    session.add(paper)
    session.flush()
    compound = Compound(
        paper_id=paper.id,
        local_identity="26a",
        display_label="26a",
        normalized_label="26a",
    )
    release = Release(
        release_key=f"structure-api-release-{uuid4().hex[:8]}",
        title="Structure API release",
        notes="",
        metrics={},
        published_by_id=result["admin"].id,
        published_at=datetime.now(UTC),
        is_current=False,
        manifest_finalized=False,
    )
    session.add_all([compound, release])
    session.flush()
    task = ReviewTask(
        paper_id=paper.id,
        assigned_reviewer_id=result["reviewer"].id,
        created_by_id=result["admin"].id,
        status=ReviewTaskStatus.IN_PROGRESS,
        version=1,
    )
    session.add(task)
    session.flush()
    changeset = Changeset(
        review_task_id=task.id,
        paper_id=paper.id,
        owner_id=result["reviewer"].id,
        base_release_id=release.id,
        title="Structure API changes",
        reason="Review structures",
        workflow_state=WorkflowState.DRAFT,
        version=1,
    )
    session.add(changeset)
    session.flush()
    result.update(paper=paper, compound=compound, changeset=changeset)
    return result


def _login(client: TestClient, username: str) -> str:
    client.cookies.clear()
    response = client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_structure_api_is_source_aware_scoped_and_idempotent(
    tmp_path: Path,
    postgresql_database_url: str,
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        seeded = _seed(session)
    resources = DatabaseResources(
        engine=auth_session_factory.kw["bind"],
        session_factory=auth_session_factory,
    )
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=postgresql_database_url,
        session_secret="structure-api-session-secret-more-than-thirty-two-characters",
        allowed_hosts=["testserver"],
        asset_root=tmp_path / "assets",
    )
    application = create_app(
        settings=settings,
        database_probe=lambda _: True,
        database_bootstrap=lambda _: resources,
    )

    paper_id = str(seeded["paper"].id)
    compound_id = str(seeded["compound"].id)
    changeset_id = str(seeded["changeset"].id)
    with TestClient(application) as client:
        visitor_csrf = _login(client, seeded["visitor"].username)
        denied = client.post(
            f"/api/v1/papers/{paper_id}/structures/validate",
            headers={"X-CSRF-Token": visitor_csrf},
            json={"smiles": "CCO"},
        )
        assert denied.status_code == 403

        reviewer_csrf = _login(client, seeded["reviewer"].username)
        validated = client.post(
            f"/api/v1/papers/{paper_id}/structures/validate",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={"smiles": "C[C@H](O)Cl"},
        )
        assert validated.status_code == 200
        assert validated.json()["parseable"] is True
        assert "structure_confirmed" not in validated.json()["eligible_states"]

        first_drawing = client.post(
            f"/api/v1/papers/{paper_id}/structures/drawings",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={"smiles": "C1=CC=CC=C1", "width": 320, "height": 240},
        )
        second_drawing = client.post(
            f"/api/v1/papers/{paper_id}/structures/drawings",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={"smiles": "c1ccccc1", "width": 320, "height": 240},
        )
        assert first_drawing.status_code == second_drawing.status_code == 200
        assert first_drawing.json()["asset_id"] == second_drawing.json()["asset_id"]
        assert second_drawing.json()["reused"] is True

        created = client.post(
            f"/api/v1/papers/{paper_id}/structures",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={
                "compound_id": compound_id,
                "changeset_id": changeset_id,
                "expected_version": 1,
                "structure_key": "26a-main",
                "smiles": "C[C@H](O)Cl",
                "structure_state": "source_bound_candidate",
                "source": "SI, Table S2",
                "reason": "Transcribed from the supporting information",
                "source_comparison": "match",
                "source_verified": True,
                "drawing_asset_id": first_drawing.json()["asset_id"],
            },
        )
        assert created.status_code == 201
        assert created.json()["changeset_version"] == 2

        stale = client.patch(
            f"/api/v1/papers/{paper_id}/structures/{created.json()['id']}",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={
                "changeset_id": changeset_id,
                "expected_version": 1,
                "smiles": "CCO",
                "structure_state": "parseable_candidate",
                "source": "Article, Figure 2",
                "reason": "Corrected structure",
            },
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "REVISION_CONFLICT"
