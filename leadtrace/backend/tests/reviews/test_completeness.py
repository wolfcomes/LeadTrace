from __future__ import annotations

from app.reviews.completeness import QueueState, assess_object


def test_completeness_uses_highest_priority_unresolved_state() -> None:
    result = assess_object(
        object_kind="visual_object",
        review_blockers=["localization"],
        requires_ocsr=True,
        proposal_dispositions=["pending"],
        source_ready=False,
        structure_ready=False,
    )
    assert result.state is QueueState.LOCALIZATION_OR_SPLIT
    assert result.blocking is True


def test_completeness_advances_from_pending_proposal_to_structure() -> None:
    result = assess_object(
        object_kind="visual_object",
        review_blockers=[],
        requires_ocsr=True,
        proposal_dispositions=["accepted"],
        source_ready=True,
        structure_ready=False,
    )
    assert result.state is QueueState.STRUCTURE_ASSEMBLY


def test_non_chemical_object_without_blockers_is_complete() -> None:
    result = assess_object(
        object_kind="visual_object",
        review_blockers=[],
        requires_ocsr=False,
        proposal_dispositions=[],
        source_ready=True,
        structure_ready=True,
    )
    assert result.state is QueueState.COMPLETE
    assert result.resolved is True
