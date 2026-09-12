from __future__ import annotations

from uuid import uuid4

import pytest

from app.lineages.validation import (
    LineageValidationError,
    validate_lineage_edge_input,
)


def test_unresolved_lineage_relation_never_invents_an_immediate_parent() -> None:
    result = validate_lineage_edge_input(
        paper_id=uuid4(),
        parent_compound_id=None,
        derived_compound_id=uuid4(),
        relation_status="unresolved",
        relation_type="optimization",
        evidence_ids=(),
    )

    assert result.parent_compound_id is None
    assert result.confirmatory is False
    assert "UNRESOLVED_PARENT" in result.blocking_codes


def test_lineage_validation_rejects_same_parent_and_derived_endpoint() -> None:
    compound_id = uuid4()

    with pytest.raises(LineageValidationError, match="distinct"):
        validate_lineage_edge_input(
            paper_id=uuid4(),
            parent_compound_id=compound_id,
            derived_compound_id=compound_id,
            relation_status="text_explicit",
            relation_type="optimization",
            evidence_ids=(),
        )


def test_lineage_validation_rejects_client_controlled_pair_ready_flag() -> None:
    with pytest.raises(LineageValidationError, match="pair_ready"):
        validate_lineage_edge_input(
            paper_id=uuid4(),
            parent_compound_id=uuid4(),
            derived_compound_id=uuid4(),
            relation_status="text_explicit",
            relation_type="optimization",
            evidence_ids=(),
            pair_ready=True,
        )


def test_evidence_binding_requires_stable_ids_and_retains_original_text() -> None:
    from app.evidence.service import EvidenceDraft, validate_evidence_draft

    draft = validate_evidence_draft(
        EvidenceDraft(
            evidence_key="ev-1",
            original_text="Compound 3 showed improved potency.",
            source_locator="Table 1",
            compound_ids=(uuid4(),),
        )
    )

    assert draft.original_text == "Compound 3 showed improved potency."
    assert len(draft.compound_ids) == 1


def test_activity_fields_are_kept_separate() -> None:
    from app.activities.service import ActivityDraft, validate_activity_draft

    draft = validate_activity_draft(
        ActivityDraft(
            activity_key="assay-1",
            compound_id=uuid4(),
            assay="cAMP accumulation",
            metric="pEC50",
            value="7.4",
            unit="nM",
            qualifier="=",
            evidence_text="Compound 3 retained activity.",
            evidence_ids=(uuid4(),),
        )
    )

    assert draft.assay == "cAMP accumulation"
    assert draft.metric == "pEC50"
    assert draft.value == "7.4"
    assert draft.unit == "nM"
    assert draft.qualifier == "="
