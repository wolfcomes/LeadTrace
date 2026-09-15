from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Iterable


class QueueState(StrEnum):
    LOCALIZATION_OR_SPLIT = "localization_or_split"
    NEEDS_OCSR = "needs_ocsr"
    PROPOSAL_REVIEW = "proposal_review"
    SOURCE_OR_ATTACHMENT = "source_or_attachment"
    STRUCTURE_ASSEMBLY = "structure_assembly"
    COMPLETE = "complete"


_TERMINAL = frozenset({"accepted", "corrected", "rejected", "not_applicable"})


@dataclass(frozen=True, slots=True)
class ObjectCompleteness:
    state: QueueState
    blocking: bool
    resolved: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)


def assess_object(
    *,
    object_kind: str,
    review_blockers: Iterable[str] = (),
    requires_ocsr: bool,
    proposal_dispositions: Iterable[str] = (),
    source_ready: bool,
    structure_ready: bool,
) -> ObjectCompleteness:
    """Derive exactly one highest-priority unresolved queue state.

    This function is intentionally independent of ORM models so imports,
    queue projections, and submission gates share the same deterministic rules.
    ``object_kind`` is retained as an input for callers and future semantic
    policies; current priority is driven by evidence completeness.
    """

    blockers = tuple(str(item) for item in review_blockers if str(item).strip())
    if blockers:
        return ObjectCompleteness(
            QueueState.LOCALIZATION_OR_SPLIT,
            blocking=True,
            resolved=False,
            reasons=blockers,
        )
    dispositions = tuple(str(item) for item in proposal_dispositions)
    if requires_ocsr and not dispositions:
        return ObjectCompleteness(
            QueueState.NEEDS_OCSR,
            blocking=True,
            resolved=False,
            reasons=("proposal_missing",),
        )
    if requires_ocsr and any(item == "pending" for item in dispositions):
        return ObjectCompleteness(
            QueueState.PROPOSAL_REVIEW,
            blocking=True,
            resolved=False,
            reasons=("proposal_pending",),
        )
    if not source_ready:
        return ObjectCompleteness(
            QueueState.SOURCE_OR_ATTACHMENT,
            blocking=True,
            resolved=False,
            reasons=("source_or_attachment_missing",),
        )
    requires_structure = requires_ocsr and any(
        item in {"accepted", "corrected"} for item in dispositions
    )
    if requires_structure and not structure_ready:
        return ObjectCompleteness(
            QueueState.STRUCTURE_ASSEMBLY,
            blocking=True,
            resolved=False,
            reasons=("resulting_structure_missing",),
        )
    return ObjectCompleteness(QueueState.COMPLETE, blocking=False, resolved=True)

