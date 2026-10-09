from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.papers.models import Paper
from app.workspaces.models import PaperWorkspace, ReviewTask


@dataclass(frozen=True, slots=True)
class LockedWorkspace:
    workspace: PaperWorkspace
    task: ReviewTask
    paper: Paper


@dataclass(frozen=True, slots=True)
class MutationChange:
    entity_type: str
    entity_id: UUID
    action: str
    before_value: dict[str, object] | None
    after_value: dict[str, object] | None


class WorkspaceMutation(Protocol):
    def __call__(self, context: LockedWorkspace) -> MutationChange: ...


def lock_workspace(session: Session, workspace_id: UUID) -> LockedWorkspace | None:
    # Follow the lifecycle/AI delivery order: paper, workspace, assignment task.
    # Bibliography changes also write Paper; taking it last can deadlock reset.
    paper_id = session.scalar(select(PaperWorkspace.paper_id).where(PaperWorkspace.id == workspace_id))
    if paper_id is None:
        return None
    session.scalar(select(Paper).where(Paper.id == paper_id).with_for_update())
    row = session.execute(
        select(PaperWorkspace, ReviewTask, Paper)
        .join(ReviewTask, ReviewTask.id == PaperWorkspace.review_task_id)
        .join(Paper, Paper.id == PaperWorkspace.paper_id)
        .where(PaperWorkspace.id == workspace_id)
        .with_for_update(of=PaperWorkspace)
    ).one_or_none()
    if row is None:
        return None
    workspace, task, paper = row
    # Refresh task assignment after any wait for the workspace lock (stale tabs).
    task = session.scalar(select(ReviewTask).where(ReviewTask.id == task.id).with_for_update().execution_options(populate_existing=True))
    return LockedWorkspace(workspace=workspace, task=task, paper=paper)


__all__ = [
    "LockedWorkspace",
    "MutationChange",
    "WorkspaceMutation",
    "lock_workspace",
]
