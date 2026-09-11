from __future__ import annotations

from app.security.policies import WorkflowState


class InvalidTransition(ValueError):
    """Raised when a review workflow transition is not permitted."""


_ALLOWED: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.DRAFT: frozenset({WorkflowState.SUBMITTED}),
    WorkflowState.SUBMITTED: frozenset(
        {
            WorkflowState.CHANGES_REQUESTED,
            WorkflowState.REJECTED,
            WorkflowState.APPROVED,
        }
    ),
    WorkflowState.CHANGES_REQUESTED: frozenset({WorkflowState.REVISED_DRAFT}),
    WorkflowState.APPROVED: frozenset({WorkflowState.PUBLISHED}),
    WorkflowState.PUBLISHED: frozenset({WorkflowState.SUPERSEDED}),
    WorkflowState.REVISED_DRAFT: frozenset({WorkflowState.SUBMITTED}),
    WorkflowState.REJECTED: frozenset(),
    WorkflowState.SUPERSEDED: frozenset(),
}


def transition_state(
    current: WorkflowState,
    next_state: WorkflowState,
) -> WorkflowState:
    if next_state not in _ALLOWED.get(current, frozenset()):
        raise InvalidTransition(
            f"Cannot transition review state from {current.value} to {next_state.value}"
        )
    return next_state


def content_mutable(state: WorkflowState) -> bool:
    return state in {WorkflowState.DRAFT, WorkflowState.REVISED_DRAFT}
