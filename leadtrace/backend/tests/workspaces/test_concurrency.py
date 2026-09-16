from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import func, select

from app.papers.models import Paper
from app.users.models import User
from app.workspaces.history import MutationChange
from app.workspaces.models import ChangeEvent, PaperWorkspace, WorkspaceState
from app.workspaces.service import (
    WorkspaceReadOnlyError,
    WorkspaceService,
    WorkspaceVersionConflictError,
)


def _title_change(title: str):
    def mutation(context) -> MutationChange:
        before = {"title": context.paper.title}
        context.paper.title = title
        return MutationChange(
            entity_type="paper",
            entity_id=context.paper.id,
            action="bibliography.update",
            before_value=before,
            after_value={"title": title},
        )

    return mutation


def test_stale_workspace_version_returns_current_version_without_writes(
    workspace_fixture,
) -> None:
    csrf = workspace_fixture.login("workspace.reviewer")
    first = workspace_fixture.client.patch(
        f"/api/v2/workspaces/{workspace_fixture.workspace_id}/bibliography",
        headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": 1, "title": "First writer"},
    )
    stale = workspace_fixture.client.patch(
        f"/api/v2/workspaces/{workspace_fixture.workspace_id}/bibliography",
        headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": 1, "title": "Stale writer"},
    )

    assert first.status_code == 200
    assert stale.status_code == 409
    assert stale.json()["code"] == "WORKSPACE_VERSION_CONFLICT"
    assert stale.json()["details"] == {
        "expected_workspace_version": 1,
        "current_workspace_version": 2,
    }
    with workspace_fixture.session_factory() as session:
        paper = session.get(Paper, workspace_fixture.paper_id)
        workspace = session.get(PaperWorkspace, workspace_fixture.workspace_id)
        count = session.scalar(select(func.count()).select_from(ChangeEvent))
        assert paper is not None
        assert workspace is not None
        assert paper.title == "First writer"
        assert workspace.version == 2
        assert count == 1


@pytest.mark.parametrize("state", [WorkspaceState.SUBMITTED, WorkspaceState.APPROVED])
def test_submitted_and_approved_workspaces_reject_writes(
    workspace_fixture,
    state: WorkspaceState,
) -> None:
    with workspace_fixture.session_factory.begin() as session:
        workspace = session.get(PaperWorkspace, workspace_fixture.workspace_id)
        assert workspace is not None
        workspace.state = state

    with workspace_fixture.session_factory() as session:
        with pytest.raises(WorkspaceReadOnlyError) as error:
            with session.begin():
                reviewer = session.get(User, workspace_fixture.reviewer_id)
                assert reviewer is not None
                WorkspaceService().mutate(
                    session,
                    workspace_id=workspace_fixture.workspace_id,
                    expected_version=1,
                    actor=reviewer,
                    mutation=_title_change("Rejected title"),
                )
        assert error.value.state is state
        assert error.value.current_version == 1

    with workspace_fixture.session_factory() as session:
        paper = session.get(Paper, workspace_fixture.paper_id)
        count = session.scalar(select(func.count()).select_from(ChangeEvent))
        assert paper is not None
        assert paper.title == "Extracted title"
        assert count == 0


def test_competing_writers_are_serialized_by_workspace_row_lock(
    workspace_fixture,
) -> None:
    start = Barrier(2)

    def write(title: str) -> tuple[str, int]:
        with workspace_fixture.session_factory() as session:
            start.wait(timeout=5)
            try:
                with session.begin():
                    reviewer = session.get(User, workspace_fixture.reviewer_id)
                    assert reviewer is not None
                    result = WorkspaceService().mutate(
                        session,
                        workspace_id=workspace_fixture.workspace_id,
                        expected_version=1,
                        actor=reviewer,
                        mutation=_title_change(title),
                    )
                return "success", result.workspace.version
            except WorkspaceVersionConflictError as error:
                return "conflict", error.current_version

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(write, ["Writer A", "Writer B"]))

    assert sorted(results) == [("conflict", 2), ("success", 2)]
    with workspace_fixture.session_factory() as session:
        workspace = session.get(PaperWorkspace, workspace_fixture.workspace_id)
        event_count = session.scalar(select(func.count()).select_from(ChangeEvent))
        assert workspace is not None
        assert workspace.version == 2
        assert event_count == 1
