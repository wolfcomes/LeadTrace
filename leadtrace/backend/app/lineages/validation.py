from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


class LineageValidationError(ValueError):
    """Raised when a lineage edge would encode an invalid scientific relation."""


@dataclass(frozen=True, slots=True)
class LineageEdgeInput:
    paper_id: UUID
    parent_compound_id: UUID | None
    derived_compound_id: UUID
    relation_status: str
    relation_type: str
    evidence_ids: tuple[UUID, ...]
    confirmatory: bool
    blocking_codes: tuple[str, ...]


def validate_lineage_edge_input(
    *,
    paper_id: UUID,
    parent_compound_id: UUID | None,
    derived_compound_id: UUID,
    relation_status: str,
    relation_type: str,
    evidence_ids: tuple[UUID, ...] = (),
    pair_ready: bool | None = None,
) -> LineageEdgeInput:
    if pair_ready is not None:
        raise LineageValidationError("pair_ready is derived by the server")
    status = relation_status.strip().casefold()
    relation = relation_type.strip()
    if not relation:
        raise LineageValidationError("relation_type is required")
    if parent_compound_id is not None and parent_compound_id == derived_compound_id:
        raise LineageValidationError("Parent and derived compounds must be distinct")
    if len(set(evidence_ids)) != len(evidence_ids):
        raise LineageValidationError("Lineage evidence references must be unique")
    if status not in {"unresolved", "text_explicit", "figure_explicit", "human_confirmed"}:
        raise LineageValidationError("Unknown lineage relation status")
    blockers: list[str] = []
    if parent_compound_id is None:
        blockers.append("UNRESOLVED_PARENT")
    if not evidence_ids:
        blockers.append("MISSING_EVIDENCE")
    if status == "unresolved":
        blockers.append("UNCONFIRMED_RELATION")
    return LineageEdgeInput(
        paper_id=paper_id,
        parent_compound_id=parent_compound_id,
        derived_compound_id=derived_compound_id,
        relation_status=status,
        relation_type=relation,
        evidence_ids=tuple(evidence_ids),
        confirmatory=status != "unresolved",
        blocking_codes=tuple(dict.fromkeys(blockers)),
    )
