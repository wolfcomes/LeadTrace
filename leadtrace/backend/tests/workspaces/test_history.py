from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.papers.models import Paper
from app.users.models import User
from app.workspaces.history import MutationChange
from app.workspaces.models import ChangeEvent, PaperWorkspace
from app.workspaces.service import WorkspaceService


def test_bibliography_mutation_updates_version_and_appends_exact_history(
    workspace_fixture,
) -> None:
    service = WorkspaceService()
    with workspace_fixture.session_factory.begin() as session:
        reviewer = session.get(User, workspace_fixture.reviewer_id)
        assert reviewer is not None

        def update_title(context) -> MutationChange:
            before = {"title": context.paper.title}
            context.paper.title = "Reviewed title"
            return MutationChange(
                entity_type="paper",
                entity_id=context.paper.id,
                action="bibliography.update",
                before_value=before,
                after_value={"title": context.paper.title},
            )

        result = service.mutate(
            session,
            workspace_id=workspace_fixture.workspace_id,
            expected_version=1,
            actor=reviewer,
            mutation=update_title,
        )

        assert result.workspace.version == 2
        assert result.event.before_value == {"title": "Extracted title"}
        assert result.event.after_value == {"title": "Reviewed title"}
        assert result.event.actor_kind.value == "reviewer"
        assert result.event.actor_id == workspace_fixture.reviewer_id
        assert result.event.paper_id == workspace_fixture.paper_id
        assert result.event.workspace_id == workspace_fixture.workspace_id
        event_id = result.event.id

    with workspace_fixture.session_factory() as session:
        paper = session.get(Paper, workspace_fixture.paper_id)
        workspace = session.get(PaperWorkspace, workspace_fixture.workspace_id)
        events = list(session.scalars(select(ChangeEvent)))
        assert paper is not None
        assert workspace is not None
        assert paper.title == "Reviewed title"
        assert workspace.version == 2
        assert [event.id for event in events] == [event_id]


def test_mutation_data_version_and_history_roll_back_together_on_flush_failure(
    workspace_fixture,
) -> None:
    service = WorkspaceService()

    try:
        with workspace_fixture.session_factory.begin() as session:
            reviewer = session.get(User, workspace_fixture.reviewer_id)
            assert reviewer is not None

            def invalid_change(context) -> MutationChange:
                context.paper.title = "Must roll back"
                return MutationChange(
                    entity_type="paper",
                    entity_id=context.paper.id,
                    action="",
                    before_value={"title": "Extracted title"},
                    after_value={"title": "Must roll back"},
                )

            service.mutate(
                session,
                workspace_id=workspace_fixture.workspace_id,
                expected_version=1,
                actor=reviewer,
                mutation=invalid_change,
            )
    except IntegrityError:
        pass
    else:
        raise AssertionError("invalid history event should fail atomically")

    with workspace_fixture.session_factory() as session:
        paper = session.get(Paper, workspace_fixture.paper_id)
        workspace = session.get(PaperWorkspace, workspace_fixture.workspace_id)
        event_count = session.scalar(select(func.count()).select_from(ChangeEvent))
        assert paper is not None
        assert workspace is not None
        assert paper.title == "Extracted title"
        assert workspace.version == 1
        assert event_count == 0
