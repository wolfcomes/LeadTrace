from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.ai_prefill.models import AiExtractionRun, AiExtractionRunStatus
from app.config import Settings
from app.database import DatabaseResources
from app.main import create_app

from .test_apply import AiContext, ai_context  # noqa: F401


@dataclass(frozen=True, slots=True)
class AiApiContext:
    client: TestClient
    database: AiContext
    dispatched: list[tuple[UUID, UUID]]
    dispatch_errors: list[Exception]
    dispatch_actions: list[Callable[[UUID, UUID], None]]

    def login(self, username: str, password: str) -> str:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        assert response.status_code == 200
        return str(response.json()["csrf_token"])


@pytest.fixture
def ai_api_context(
    ai_context: AiContext,
    tmp_path: Path,
) -> Iterator[AiApiContext]:
    dispatched: list[tuple[UUID, UUID]] = []
    dispatch_errors: list[Exception] = []
    dispatch_actions: list[Callable[[UUID, UUID], None]] = []

    def capture_dispatch(run_id: UUID, dispatch_token: UUID) -> None:
        for action in dispatch_actions:
            action(run_id, dispatch_token)
        if dispatch_errors:
            raise dispatch_errors[0]
        dispatched.append((run_id, dispatch_token))

    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=str(ai_context.session_factory.kw["bind"].url),
        redis_url="redis://127.0.0.1:6379/0",
        session_secret="ai-prefill-api-secret-more-than-thirty-two-characters",
        allowed_hosts=["testserver"],
        asset_root=tmp_path / "managed",
        ai_prefill_engine="legacy_pipeline",
        ai_prefill_engine_version="pilot-v1",
    )
    resources = DatabaseResources(
        engine=ai_context.session_factory.kw["bind"],
        session_factory=ai_context.session_factory,
    )
    application = create_app(
        settings=settings,
        database_probe=lambda _: True,
        database_bootstrap=lambda _: resources,
        ai_prefill_dispatch=capture_dispatch,
    )
    with TestClient(application) as client:
        yield AiApiContext(
            client,
            ai_context,
            dispatched,
            dispatch_errors,
            dispatch_actions,
        )


def test_admin_queues_and_reads_ai_prefill_status_with_csrf(
    ai_api_context: AiApiContext,
) -> None:
    csrf = ai_api_context.login(
        "ai.prefill.admin", "AI prefill Admin password 2026!"
    )

    before = ai_api_context.client.get(
        f"/api/v2/admin/papers/{ai_api_context.database.paper_id}/ai-prefill"
    )
    queued = ai_api_context.client.post(
        f"/api/v2/admin/papers/{ai_api_context.database.paper_id}/ai-prefill",
        headers={"X-CSRF-Token": csrf},
    )
    after = ai_api_context.client.get(
        f"/api/v2/admin/papers/{ai_api_context.database.paper_id}/ai-prefill"
    )

    assert before.status_code == 200
    assert before.json() == {
        "run": None,
        "can_start": True,
        "blocked_reason": None,
    }
    assert queued.status_code == 202
    payload = queued.json()
    assert payload["run"]["status"] == "queued"
    assert payload["run"]["engine"] == "legacy_pipeline"
    assert payload["run"]["engine_version"] == "pilot-v1"
    assert payload["run"]["paper_id"] == str(ai_api_context.database.paper_id)
    assert payload["run"]["workspace_id"] == str(
        ai_api_context.database.workspace_id
    )
    assert payload["can_start"] is False
    run_id = UUID(payload["run"]["id"])
    assert len(ai_api_context.dispatched) == 1
    assert ai_api_context.dispatched[0][0] == run_id
    with ai_api_context.database.session_factory() as session:
        run = session.get(AiExtractionRun, run_id)
        assert run is not None
        assert run.dispatch_token == ai_api_context.dispatched[0][1]
        assert run.dispatched_at is not None
    assert after.status_code == 200
    assert after.json() == payload
    assert "storage_key" not in after.text
    assert "source_key" not in after.text


def test_ai_prefill_trigger_requires_admin_and_csrf(
    ai_api_context: AiApiContext,
) -> None:
    admin_csrf = ai_api_context.login(
        "ai.prefill.admin", "AI prefill Admin password 2026!"
    )
    del admin_csrf
    missing_csrf = ai_api_context.client.post(
        f"/api/v2/admin/papers/{ai_api_context.database.paper_id}/ai-prefill"
    )
    reviewer_csrf = ai_api_context.login(
        "ai.prefill.reviewer", "AI prefill Reviewer password 2026!"
    )
    reviewer = ai_api_context.client.post(
        f"/api/v2/admin/papers/{ai_api_context.database.paper_id}/ai-prefill",
        headers={"X-CSRF-Token": reviewer_csrf},
    )

    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["code"] == "CSRF_VALIDATION_FAILED"
    assert reviewer.status_code == 403
    assert reviewer.json()["code"] == "PERMISSION_DENIED"
    assert ai_api_context.dispatched == []


def test_human_modified_workspace_rejects_ai_prefill_without_dispatch(
    ai_api_context: AiApiContext,
) -> None:
    reviewer_csrf = ai_api_context.login(
        "ai.prefill.reviewer", "AI prefill Reviewer password 2026!"
    )
    edited = ai_api_context.client.patch(
        f"/api/v2/workspaces/{ai_api_context.database.workspace_id}/bibliography",
        headers={"X-CSRF-Token": reviewer_csrf},
        json={
            "expected_workspace_version": 1,
            "title": "Reviewer-owned title",
        },
    )
    assert edited.status_code == 200
    admin_csrf = ai_api_context.login(
        "ai.prefill.admin", "AI prefill Admin password 2026!"
    )

    response = ai_api_context.client.post(
        f"/api/v2/admin/papers/{ai_api_context.database.paper_id}/ai-prefill",
        headers={"X-CSRF-Token": admin_csrf},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "AI_PREFILL_UNAVAILABLE"
    assert ai_api_context.dispatched == []


def test_failed_run_can_be_retried_as_a_new_run(
    ai_api_context: AiApiContext,
) -> None:
    csrf = ai_api_context.login(
        "ai.prefill.admin", "AI prefill Admin password 2026!"
    )
    first = ai_api_context.client.post(
        f"/api/v2/admin/papers/{ai_api_context.database.paper_id}/ai-prefill",
        headers={"X-CSRF-Token": csrf},
    )
    first_id = UUID(first.json()["run"]["id"])
    with ai_api_context.database.session_factory.begin() as session:
        run = session.get(AiExtractionRun, first_id)
        assert run is not None
        run.status = AiExtractionRunStatus.FAILED
        run.error_summary = "AI extraction failed"

    second = ai_api_context.client.post(
        f"/api/v2/admin/papers/{ai_api_context.database.paper_id}/ai-prefill",
        headers={"X-CSRF-Token": csrf},
    )

    assert second.status_code == 202
    second_id = UUID(second.json()["run"]["id"])
    assert second_id != first_id
    assert [run_id for run_id, _ in ai_api_context.dispatched] == [
        first_id,
        second_id,
    ]
    assert ai_api_context.dispatched[0][1] != ai_api_context.dispatched[1][1]


def test_repeated_start_dispatches_an_active_run_only_once(
    ai_api_context: AiApiContext,
) -> None:
    csrf = ai_api_context.login(
        "ai.prefill.admin", "AI prefill Admin password 2026!"
    )

    first = ai_api_context.client.post(
        f"/api/v2/admin/papers/{ai_api_context.database.paper_id}/ai-prefill",
        headers={"X-CSRF-Token": csrf},
    )
    second = ai_api_context.client.post(
        f"/api/v2/admin/papers/{ai_api_context.database.paper_id}/ai-prefill",
        headers={"X-CSRF-Token": csrf},
    )

    assert first.status_code == 202
    assert second.status_code == 202
    first_run_id = UUID(first.json()["run"]["id"])
    assert second.json()["run"]["id"] == str(first_run_id)
    assert [run_id for run_id, _ in ai_api_context.dispatched] == [first_run_id]
    with ai_api_context.database.session_factory() as session:
        runs = session.query(AiExtractionRun).all()
    assert [run.id for run in runs] == [first_run_id]


def test_dispatch_failure_releases_run_for_reconciliation(
    ai_api_context: AiApiContext,
) -> None:
    csrf = ai_api_context.login(
        "ai.prefill.admin", "AI prefill Admin password 2026!"
    )
    ai_api_context.dispatch_errors.append(ConnectionError("Redis unavailable"))

    response = ai_api_context.client.post(
        f"/api/v2/admin/papers/{ai_api_context.database.paper_id}/ai-prefill",
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "AI_PREFILL_DISPATCH_FAILED"
    with ai_api_context.database.session_factory() as session:
        run = session.query(AiExtractionRun).one()
        assert run.status is AiExtractionRunStatus.QUEUED
        assert run.error_summary == "AI task dispatch failed; queued for retry"
        assert run.dispatched_at is None
        assert run.completed_at is None


def test_uncertain_dispatch_failure_does_not_overwrite_worker_terminal_state(
    ai_api_context: AiApiContext,
) -> None:
    csrf = ai_api_context.login(
        "ai.prefill.admin", "AI prefill Admin password 2026!"
    )

    def worker_completed(run_id: UUID, _: UUID) -> None:
        with ai_api_context.database.session_factory.begin() as session:
            run = session.get(AiExtractionRun, run_id)
            assert run is not None
            run.status = AiExtractionRunStatus.SUCCEEDED

    ai_api_context.dispatch_actions.append(worker_completed)
    ai_api_context.dispatch_errors.append(ConnectionError("broker ack was lost"))

    response = ai_api_context.client.post(
        f"/api/v2/admin/papers/{ai_api_context.database.paper_id}/ai-prefill",
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 503
    with ai_api_context.database.session_factory() as session:
        run = session.query(AiExtractionRun).one()
        assert run.status is AiExtractionRunStatus.SUCCEEDED
