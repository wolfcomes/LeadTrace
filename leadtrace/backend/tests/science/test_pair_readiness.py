from __future__ import annotations

from app.lineages.service import PairReadinessService


def test_pair_readiness_is_derived_and_exposes_blocking_codes() -> None:
    readiness = PairReadinessService.from_facts(
        relation_status="unresolved",
        parent_id=None,
        derived_id="derived-1",
        parent_structure_state=None,
        derived_structure_state="structure_confirmed",
        parent_smiles=None,
        derived_smiles="CCO",
        evidence_ids=(),
    )

    assert readiness.eligible is False
    assert {
        "UNRESOLVED_PARENT",
        "MISSING_PARENT_STRUCTURE",
        "MISSING_EVIDENCE",
    }.issubset(readiness.blocking_codes)


def test_pair_readiness_requires_two_distinct_confirmed_structures_and_evidence() -> None:
    readiness = PairReadinessService.from_facts(
        relation_status="text_explicit",
        parent_id="parent-1",
        derived_id="derived-1",
        parent_structure_state="structure_confirmed",
        derived_structure_state="structure_confirmed",
        parent_smiles="CCO",
        derived_smiles="CCN",
        evidence_ids=("evidence-1",),
    )

    assert readiness.eligible is True
    assert readiness.blocking_codes == ()
