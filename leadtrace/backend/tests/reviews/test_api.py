from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.database import DatabaseResources
from app.main import create_app
from app.papers.models import Paper
from app.releases.models import Release, ReleaseItem
from app.revisions.models import ObjectKind, ObjectRevision
from app.revisions.service import RevisionService
from app.reviews.models import Changeset
from app.reviews.service import ReviewService
from app.security.policies import WorkflowState
from app.users.models import UserRole
from app.users.service import UserService


PASSWORD = "Review API password 2026!"


def _settings(tmp_path: Path, database_url: str) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        redis_url="redis://127.0.0.1:6379/0",
        session_secret="review-api-session-secret-more-than-thirty-two-characters",
        allowed_hosts=["testserver"],
        asset_root=tmp_path,
    )


def _seed_review(session) -> dict[str, UUID | str]:
    users = UserService()
    identities = {}
    for name, role in (
        ("review-api-reviewer", UserRole.REVIEWER),
        ("review-api-other", UserRole.REVIEWER),
        ("review-api-visitor", UserRole.VISITOR),
        ("review-api-admin", UserRole.ADMIN),
    ):
        user = users.create_user(
            session,
            username=f"{name}-{uuid4().hex[:6]}",
            display_name=name,
            role=role,
            initial_password=PASSWORD,
        )
        user.must_change_password = False
        identities[name] = user.id
        identities[f"{name}-username"] = user.username

    paper = Paper(paper_key=f"review-api-paper-{uuid4().hex[:8]}", doi=None)
    session.add(paper)
    session.flush()
    release = Release(
        release_key=f"review-api-release-{uuid4().hex[:8]}",
        title="Review API release",
        notes="",
        metrics={},
        published_by_id=identities["review-api-admin"],
        published_at=datetime.now(UTC),
        is_current=True,
        manifest_finalized=False,
    )
    session.add(release)
    session.flush()
    paper_revision = RevisionService().create_revision(
        session,
        object_identity=paper,
        actor_id=identities["review-api-admin"],
        reason="Review API published base",
        snapshot={"paper_key": paper.paper_key},
        workflow_state=WorkflowState.PUBLISHED,
        is_current_published=True,
    )
    session.add(
        ReleaseItem(
            release_id=release.id,
            object_id=paper.id,
            revision_id=paper_revision.id,
            paper_id=paper.id,
            object_kind=ObjectKind.PAPER,
            manifest_order=1,
        )
    )
    session.flush()
    release.manifest_finalized = True
    session.flush()
    task = ReviewService().create_task(
        session,
        paper_id=paper.id,
        assignee_id=identities["review-api-reviewer"],
        created_by_id=identities["review-api-admin"],
    )
    identities["paper"] = paper.id
    identities["release"] = release.id
    identities["task"] = task.id
    identities["paper_revision"] = paper_revision.id
    return identities


def _login(client: TestClient, username: str) -> str:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_review_api_enforces_roles_scope_csrf_and_version_conflicts(
    tmp_path: Path,
    postgresql_database_url: str,
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        seeded = _seed_review(session)

    resources = DatabaseResources(
        engine=auth_session_factory.kw["bind"],
        session_factory=auth_session_factory,
    )
    application = create_app(
        settings=_settings(tmp_path, postgresql_database_url),
        database_probe=lambda _: True,
        database_bootstrap=lambda _: resources,
    )
    with TestClient(application) as client:
        _login(client, str(seeded["review-api-visitor-username"]))
        assert client.get("/api/v1/review/tasks").status_code == 403

        reviewer_csrf = _login(
            client,
            str(seeded["review-api-reviewer-username"]),
        )
        tasks = client.get("/api/v1/review/tasks")
        assert tasks.status_code == 200
        assert [item["id"] for item in tasks.json()] == [str(seeded["task"])]

        long_reason = "r" * 4000
        create_payload = {
            "review_task_id": str(seeded["task"]),
            "paper_id": str(seeded["paper"]),
            "base_release_id": str(seeded["release"]),
            "title": "Correct parent compound",
            "reason": long_reason,
        }
        assert (
            client.post("/api/v1/review/changesets", json=create_payload).status_code
            == 403
        )
        created = client.post(
            "/api/v1/review/changesets",
            headers={"X-CSRF-Token": reviewer_csrf},
            json=create_payload,
        )
        assert created.status_code == 201
        changeset_id = created.json()["id"]
        duplicate = client.post(
            "/api/v1/review/changesets",
            headers={"X-CSRF-Token": reviewer_csrf},
            json=create_payload,
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["code"] == "REVIEW_STATE_CONFLICT"
        listed_changesets = client.get("/api/v1/review/changesets")
        assert listed_changesets.status_code == 200
        assert [item["id"] for item in listed_changesets.json()] == [changeset_id]

        item_created = client.post(
            f"/api/v1/review/changesets/{changeset_id}/items",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={
                "expected_version": 1,
                "object_id": str(seeded["paper"]),
                "object_kind": "paper",
                "base_revision_id": str(seeded["paper_revision"]),
                "proposed_snapshot": {
                    "paper_key": "reviewed-paper",
                    "review_status": "reviewed",
                },
            },
        )
        assert item_created.status_code == 201
        assert item_created.json()["changeset_version"] == 2
        item_id = item_created.json()["id"]
        listed_items = client.get(
            f"/api/v1/review/changesets/{changeset_id}/items"
        )
        assert listed_items.status_code == 200
        assert [item["id"] for item in listed_items.json()] == [item_id]
        item_updated = client.patch(
            f"/api/v1/review/changesets/{changeset_id}/items/{item_id}",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={
                "expected_version": 2,
                "proposed_snapshot": {
                    "paper_key": "reviewed-paper",
                    "review_status": "confirmed",
                },
            },
        )
        assert item_updated.status_code == 200
        assert item_updated.json()["changeset_version"] == 3
        item_deleted = client.request(
            "DELETE",
            f"/api/v1/review/changesets/{changeset_id}/items/{item_id}",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={"expected_version": 3},
        )
        assert item_deleted.status_code == 200
        assert item_deleted.json()["version"] == 4
        item_recreated = client.post(
            f"/api/v1/review/changesets/{changeset_id}/items",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={
                "expected_version": 4,
                "object_id": str(seeded["paper"]),
                "object_kind": "paper",
                "base_revision_id": str(seeded["paper_revision"]),
                "proposed_snapshot": item_updated.json()["proposed_snapshot"],
            },
        )
        assert item_recreated.status_code == 201
        assert item_recreated.json()["changeset_version"] == 5

        updated = client.patch(
            f"/api/v1/review/changesets/{changeset_id}",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={"expected_version": 5, "title": "Correct direct parent"},
        )
        assert updated.status_code == 200
        assert updated.json()["version"] == 6
        stale = client.patch(
            f"/api/v1/review/changesets/{changeset_id}",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={"expected_version": 5, "title": "Stale overwrite"},
        )
        assert stale.status_code == 409
        assert stale.json()["details"] == {
            "expected_version": 5,
            "current_version": 6,
        }

        _login(client, str(seeded["review-api-other-username"]))
        concealed = client.get(f"/api/v1/review/changesets/{changeset_id}")
        assert concealed.status_code == 404

        reviewer_csrf = _login(
            client,
            str(seeded["review-api-reviewer-username"]),
        )
        submitted = client.post(
            f"/api/v1/review/changesets/{changeset_id}/submit",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={"expected_version": 6},
        )
        assert submitted.status_code == 200
        assert submitted.json()["workflow_state"] == "submitted"
        assert (
            submitted.json()["submitted_snapshot"]["title"] == "Correct direct parent"
        )
        assert submitted.json()["submitted_snapshot"]["reason"] == long_reason
        blocked_edit = client.patch(
            f"/api/v1/review/changesets/{changeset_id}",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={"expected_version": 7, "title": "Edit after submission"},
        )
        assert blocked_edit.status_code == 409
        assert blocked_edit.json()["code"] == "REVIEW_STATE_CONFLICT"
        repeated_submit = client.post(
            f"/api/v1/review/changesets/{changeset_id}/submit",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={"expected_version": 7},
        )
        assert repeated_submit.status_code == 409
        assert repeated_submit.json()["code"] == "REVIEW_STATE_CONFLICT"
        reviewer_approval = client.post(
            f"/api/v1/review/changesets/{changeset_id}/approve",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={"expected_version": 7},
        )
        assert reviewer_approval.status_code == 403

        admin_csrf = _login(client, str(seeded["review-api-admin-username"]))
        approved = client.post(
            f"/api/v1/review/changesets/{changeset_id}/approve",
            headers={"X-CSRF-Token": admin_csrf},
            json={"expected_version": 7},
        )
        assert approved.status_code == 200
        assert approved.json()["workflow_state"] == "approved"

    with auth_session_factory() as session:
        changeset = session.get(Changeset, UUID(changeset_id))
        assert changeset is not None
        assert changeset.workflow_state is WorkflowState.APPROVED
        assert session.get(Release, seeded["release"]).is_current


def test_admin_can_create_edit_and_submit_for_assigned_reviewer(
    tmp_path: Path,
    postgresql_database_url: str,
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        seeded = _seed_review(session)

    resources = DatabaseResources(
        engine=auth_session_factory.kw["bind"],
        session_factory=auth_session_factory,
    )
    application = create_app(
        settings=_settings(tmp_path, postgresql_database_url),
        database_probe=lambda _: True,
        database_bootstrap=lambda _: resources,
    )
    with TestClient(application) as client:
        admin_csrf = _login(client, str(seeded["review-api-admin-username"]))
        created = client.post(
            "/api/v1/review/changesets",
            headers={"X-CSRF-Token": admin_csrf},
            json={
                "review_task_id": str(seeded["task"]),
                "paper_id": str(seeded["paper"]),
                "base_release_id": str(seeded["release"]),
                "title": "Admin-assisted review",
                "reason": "Admin prepares a draft for the assigned Reviewer",
            },
        )
        assert created.status_code == 201
        assert created.json()["owner_id"] == str(seeded["review-api-reviewer"])
        changeset_id = created.json()["id"]

        item = client.post(
            f"/api/v1/review/changesets/{changeset_id}/items",
            headers={"X-CSRF-Token": admin_csrf},
            json={
                "expected_version": 1,
                "object_id": str(seeded["paper"]),
                "object_kind": "paper",
                "base_revision_id": str(seeded["paper_revision"]),
                "proposed_snapshot": {"paper_key": "admin-reviewed"},
            },
        )
        assert item.status_code == 201
        with auth_session_factory.begin() as session:
            paper = session.get(Paper, seeded["paper"])
            assert paper is not None
            RevisionService().create_revision(
                session,
                object_identity=paper,
                actor_id=seeded["review-api-admin"],
                reason="Admin-assisted draft revision",
                snapshot=item.json()["proposed_snapshot"],
                predecessor=session.get(
                    ObjectRevision,
                    seeded["paper_revision"],
                ),
                changeset_id=UUID(changeset_id),
            )
        blocked_delete = client.request(
            "DELETE",
            f"/api/v1/review/changesets/{changeset_id}/items/{item.json()['id']}",
            headers={"X-CSRF-Token": admin_csrf},
            json={"expected_version": 2},
        )
        assert blocked_delete.status_code == 409
        assert blocked_delete.json()["code"] == "CHANGESET_ITEM_HAS_REVISIONS"
        edited = client.patch(
            f"/api/v1/review/changesets/{changeset_id}",
            headers={"X-CSRF-Token": admin_csrf},
            json={"expected_version": 2, "title": "Admin-assisted correction"},
        )
        assert edited.status_code == 200
        submitted = client.post(
            f"/api/v1/review/changesets/{changeset_id}/submit",
            headers={"X-CSRF-Token": admin_csrf},
            json={"expected_version": 3},
        )
        assert submitted.status_code == 200
        assert submitted.json()["workflow_state"] == "submitted"
