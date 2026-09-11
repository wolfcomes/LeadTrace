from __future__ import annotations

import pytest

from app.reviews.state_machine import InvalidTransition, transition_state
from app.security.policies import WorkflowState


ALLOWED_EDGES = {
    (WorkflowState.DRAFT, WorkflowState.SUBMITTED),
    (WorkflowState.SUBMITTED, WorkflowState.CHANGES_REQUESTED),
    (WorkflowState.SUBMITTED, WorkflowState.REJECTED),
    (WorkflowState.SUBMITTED, WorkflowState.APPROVED),
    (WorkflowState.CHANGES_REQUESTED, WorkflowState.REVISED_DRAFT),
    (WorkflowState.APPROVED, WorkflowState.PUBLISHED),
    (WorkflowState.PUBLISHED, WorkflowState.SUPERSEDED),
    (WorkflowState.REVISED_DRAFT, WorkflowState.SUBMITTED),
}


@pytest.mark.parametrize(
    ("current", "next_state"),
    [
        (current, next_state)
        for current in WorkflowState
        for next_state in WorkflowState
    ],
)
def test_transition_matrix_covers_every_state_pair(
    current: WorkflowState,
    next_state: WorkflowState,
) -> None:
    if (current, next_state) in ALLOWED_EDGES:
        assert transition_state(current, next_state) is next_state
        return
    with pytest.raises(InvalidTransition):
        transition_state(current, next_state)


def test_submitted_and_terminal_states_are_content_immutable() -> None:
    from app.reviews.state_machine import content_mutable

    assert content_mutable(WorkflowState.DRAFT)
    assert content_mutable(WorkflowState.REVISED_DRAFT)
    for state in (
        WorkflowState.SUBMITTED,
        WorkflowState.CHANGES_REQUESTED,
        WorkflowState.APPROVED,
        WorkflowState.PUBLISHED,
        WorkflowState.SUPERSEDED,
        WorkflowState.REJECTED,
    ):
        assert not content_mutable(state)
