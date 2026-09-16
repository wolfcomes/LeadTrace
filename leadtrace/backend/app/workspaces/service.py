from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.models import PaperSource
from app.papers.models import Paper
from app.security.policies import Principal
from app.users.models import User, UserRole
from app.workspaces.history import WorkspaceMutation, lock_workspace
from app.workspaces.models import (
    ChangeActorKind,
    ChangeEvent,
    PaperSection,
    PaperSectionReview,
    PaperWorkspace,
    ReviewTask,
    WorkspaceState,
)


class WorkspaceNotFoundError(LookupError):
    pass


class WorkspaceForbiddenError(PermissionError):
    pass


class WorkspaceVersionConflictError(RuntimeError):
    def __init__(self, expected_version: int, current_version: int) -> None:
        super().__init__("Workspace version changed")
        self.expected_version = expected_version
        self.current_version = current_version


class WorkspaceReadOnlyError(RuntimeError):
    def __init__(self, state: WorkspaceState, current_version: int) -> None:
        super().__init__("Workspace is read-only")
        self.state = state
        self.current_version = current_version


@dataclass(frozen=True, slots=True)
class MutationResult:
    workspace: PaperWorkspace
    event: ChangeEvent | None


@dataclass(frozen=True, slots=True)
class WorkspaceAggregate:
    workspace: PaperWorkspace
    task: ReviewTask
    paper: Paper
    source: PaperSource
    sections: list[PaperSectionReview]


@dataclass(frozen=True, slots=True)
class ReviewTaskAggregate:
    task: ReviewTask
    workspace: PaperWorkspace
    paper: Paper


WorkspaceActor = User | Principal


def _actor_identity(actor: WorkspaceActor) -> tuple[UUID, UserRole]:
    if isinstance(actor, User):
        return actor.id, actor.role
    return actor.user_id, actor.role


class WorkspaceService:
    @staticmethod
    def _authorize_read(
        *, actor_id: UUID, role: UserRole, assigned_reviewer_id: UUID
    ) -> None:
        if role is UserRole.VISITOR:
            raise WorkspaceForbiddenError("Permission denied")
        if role is UserRole.REVIEWER and assigned_reviewer_id != actor_id:
            raise WorkspaceNotFoundError("Resource not found")

    def mutate(
        self,
        session: Session,
        *,
        workspace_id: UUID,
        expected_version: int,
        actor: WorkspaceActor,
        mutation: WorkspaceMutation,
    ) -> MutationResult:
        actor_id, role = _actor_identity(actor)
        context = lock_workspace(session, workspace_id)
        if context is None:
            raise WorkspaceNotFoundError("Resource not found")
        if role is UserRole.REVIEWER:
            if context.task.assigned_reviewer_id != actor_id:
                raise WorkspaceNotFoundError("Resource not found")
        else:
            raise WorkspaceForbiddenError("Permission denied")
        if context.workspace.state is not WorkspaceState.EDITING:
            raise WorkspaceReadOnlyError(
                context.workspace.state,
                context.workspace.version,
            )
        if context.workspace.version != expected_version:
            raise WorkspaceVersionConflictError(
                expected_version,
                context.workspace.version,
            )

        change = mutation(context)
        if change.before_value == change.after_value:
            return MutationResult(workspace=context.workspace, event=None)
        event = ChangeEvent(
            paper_id=context.workspace.paper_id,
            workspace_id=context.workspace.id,
            entity_type=change.entity_type,
            entity_id=change.entity_id,
            action=change.action,
            before_value=change.before_value,
            after_value=change.after_value,
            actor_kind=ChangeActorKind.REVIEWER,
            actor_id=actor_id,
            ai_run_id=None,
        )
        context.workspace.version += 1
        session.add(event)
        session.flush()
        return MutationResult(workspace=context.workspace, event=event)

    def list_review_tasks(
        self,
        session: Session,
        *,
        actor: WorkspaceActor,
    ) -> list[ReviewTaskAggregate]:
        actor_id, role = _actor_identity(actor)
        if role is not UserRole.REVIEWER:
            raise WorkspaceForbiddenError("Permission denied")
        rows = session.execute(
            select(ReviewTask, PaperWorkspace, Paper)
            .join(
                PaperWorkspace,
                PaperWorkspace.review_task_id == ReviewTask.id,
            )
            .join(Paper, Paper.id == ReviewTask.paper_id)
            .where(ReviewTask.assigned_reviewer_id == actor_id)
            .order_by(ReviewTask.created_at, ReviewTask.id)
        ).all()
        return [
            ReviewTaskAggregate(task=task, workspace=workspace, paper=paper)
            for task, workspace, paper in rows
        ]

    def get_workspace(
        self,
        session: Session,
        *,
        workspace_id: UUID,
        actor: WorkspaceActor,
    ) -> WorkspaceAggregate:
        actor_id, role = _actor_identity(actor)
        row = session.execute(
            select(PaperWorkspace, ReviewTask, Paper, PaperSource)
            .join(ReviewTask, ReviewTask.id == PaperWorkspace.review_task_id)
            .join(Paper, Paper.id == PaperWorkspace.paper_id)
            .join(PaperSource, PaperSource.id == Paper.source_id)
            .where(PaperWorkspace.id == workspace_id)
        ).one_or_none()
        if row is None:
            raise WorkspaceNotFoundError("Resource not found")
        workspace, task, paper, source = row
        self._authorize_read(
            actor_id=actor_id,
            role=role,
            assigned_reviewer_id=task.assigned_reviewer_id,
        )
        section_rows = list(
            session.scalars(
                select(PaperSectionReview).where(
                    PaperSectionReview.workspace_id == workspace.id
                )
            )
        )
        sections_by_key = {section.section_key: section for section in section_rows}
        sections = [sections_by_key[key] for key in PaperSection]
        return WorkspaceAggregate(
            workspace=workspace,
            task=task,
            paper=paper,
            source=source,
            sections=sections,
        )


__all__ = [
    "MutationResult",
    "ReviewTaskAggregate",
    "WorkspaceAggregate",
    "WorkspaceForbiddenError",
    "WorkspaceNotFoundError",
    "WorkspaceReadOnlyError",
    "WorkspaceService",
    "WorkspaceVersionConflictError",
]
