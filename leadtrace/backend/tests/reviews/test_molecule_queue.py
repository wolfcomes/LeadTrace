from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import DatabaseResources
from app.main import create_app
from app.reviews.models import Changeset
from app.reviews.service import ReviewService
from tests.releases.test_baseline_publish import PASSWORD as BASELINE_PASSWORD
from tests.reviews.test_api import _login, _settings
from tests.reviews.test_workspace import seed_scientific_review


pytest_plugins = ("tests.imports.conftest",)


def test_molecule_queue_projects_existing_tasks_without_creating_changesets(
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
            start_changeset=False,
        )
        reviewer_username = seeded["reviewer"].username
        other_username = seeded["other"].username
        admin_username = seeded["admin"].username
        paper_id = seeded["paper"].id
        release_id = seeded["release"].id
        task_id = seeded["task"].id
        visual_object_id = seeded["visual_object"].id
        proposal_id = seeded["proposal"].id
        initial_changeset_count = session.scalar(select(func.count(Changeset.id)))

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
            "/api/v1/review/tasks/first-page-molecule-objects",
            params={"status": "proposal_review", "page": 1, "limit": 20},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["next_cursor"] is None
        assert payload["status_counts"] == {
            "localization_or_split": 0,
            "needs_ocsr": 0,
            "proposal_review": 1,
            "source_or_attachment": 0,
            "structure_assembly": 0,
            "complete": 0,
        }
        assert len(payload["items"]) == 1
        row = payload["items"][0]
        assert row["paper_id"] == str(paper_id)
        assert row["base_release_id"] == str(release_id)
        assert row["review_task_id"] == str(task_id)
        assert row["changeset_id"] is None
        assert row["changeset_version"] is None
        assert row["visual_object"]["id"] == str(visual_object_id)
        assert row["proposal"]["id"] == str(proposal_id)
        assert row["state"] == "proposal_review"
        assert row["blocking"] is True
        assert row["deep_link"] == {
            "view": "ocsr",
            "page": 1,
            "object": str(visual_object_id),
            "proposal": str(proposal_id),
        }
        assert row["crop_asset"]["url"].startswith("/api/v1/assets/")
        assert row["paper_progress"] == {
            "scope_count": 12,
            "resolved_count": 11,
            "blocker_count": 1,
        }
        assert "storage_key" not in response.text
        assert str(baseline_fixture["workspace"]) not in response.text

        assert client.get(
            "/api/v1/review/tasks/first-page-molecule-objects",
            params={"status": "complete"},
        ).json()["items"] == []

        _login(client, other_username)
        assert client.get(
            "/api/v1/review/tasks/first-page-molecule-objects"
        ).json()["items"] == []

        client.cookies.clear()
        admin_login = client.post(
            "/api/v1/auth/login",
            json={"username": admin_username, "password": BASELINE_PASSWORD},
        )
        assert admin_login.status_code == 200
        admin_payload = client.get(
            "/api/v1/review/tasks/first-page-molecule-objects"
        ).json()
        assert [item["review_task_id"] for item in admin_payload["items"]] == [
            str(task_id)
        ]

        for params in (
            {"status": "not-a-queue-state"},
            {"object_type": "not-a-molecule-object"},
            {"cursor": "%%%not-a-cursor%%%"},
        ):
            assert client.get(
                "/api/v1/review/tasks/first-page-molecule-objects",
                params=params,
            ).status_code == 422

    with auth_session_factory() as session:
        assert session.scalar(select(func.count(Changeset.id))) == initial_changeset_count

    with auth_session_factory.begin() as session:
        task = session.get(type(seeded["task"]), task_id)
        reviewer = session.get(type(seeded["reviewer"]), seeded["reviewer"].id)
        assert task is not None and reviewer is not None
        changeset = ReviewService().create_changeset(
            session,
            paper_id=paper_id,
            actor_id=reviewer.id,
            review_task_id=task.id,
            base_release_id=release_id,
            title="Started from molecule queue",
            reason="Preserve the selected object target",
        )
        changeset_id = changeset.id

    with TestClient(application) as client:
        _login(client, reviewer_username)
        row = client.get(
            "/api/v1/review/tasks/first-page-molecule-objects"
        ).json()["items"][0]
        assert row["changeset_id"] == str(changeset_id)
        assert row["changeset_version"] == 1


def test_workspace_and_queue_publish_named_response_contracts(
    tmp_path: Path,
    postgresql_database_url: str,
    auth_session_factory,
) -> None:
    resources = DatabaseResources(
        engine=auth_session_factory.kw["bind"],
        session_factory=auth_session_factory,
    )
    application = create_app(
        settings=_settings(tmp_path / "managed", postgresql_database_url),
        database_probe=lambda _: True,
        database_bootstrap=lambda _: resources,
    )

    openapi = application.openapi()
    queue_response = openapi["paths"][
        "/api/v1/review/tasks/first-page-molecule-objects"
    ]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    workspace_response = openapi["paths"][
        "/api/v1/review/changesets/{changeset_id}/workspace"
    ]["get"]["responses"]["200"]["content"]["application/json"]["schema"]

    assert queue_response == {
        "$ref": "#/components/schemas/MoleculeObjectQueueResponse"
    }
    assert workspace_response == {"$ref": "#/components/schemas/WorkspaceResponse"}
