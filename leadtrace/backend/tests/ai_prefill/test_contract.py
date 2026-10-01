from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.ai_prefill.contracts import AiPrefillPayload


def complete_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "bibliography": {
            "title": "AI normalized lead optimization study",
            "doi": "10.1021/acs.jmedchem.4c00001",
        },
        "compounds": [
            {
                "ref": "compound:lead-1",
                "compound_label": "Lead 1",
                "display_name": "Starting lead",
                "description": "Initial hit",
                "structure": {"smiles": "CCO", "molfile": None},
            },
            {
                "ref": "compound:18",
                "compound_label": "Compound 18",
                "display_name": "Optimized compound",
                "description": None,
                "structure": {"smiles": "CCN", "molfile": None},
            },
        ],
        "structure_locators": [
            {
                "ref": "structure-image:lead-1",
                "compound_ref": "compound:lead-1",
                "page_number": 3,
                "bbox": {"x0": 0.1, "y0": 0.2, "x1": 0.4, "y1": 0.6},
                "source_context": "Scheme 1",
                "label": "Lead 1",
            }
        ],
        "lineages": [
            {
                "ref": "lineage:series-a",
                "lineage_label": "Series A",
                "description": "Lead optimization series",
                "members": [
                    {"compound_ref": "compound:lead-1", "role": "root"},
                    {"compound_ref": "compound:18", "role": "terminal"},
                ],
                "edges": [
                    {
                        "ref": "edge:lead-1-to-18",
                        "parent_compound_ref": "compound:lead-1",
                        "child_compound_ref": "compound:18",
                        "relation_type": "lead_optimization",
                        "modification_summary": "Polar amine replacement",
                    }
                ],
            }
        ],
        "evidence": [
            {
                "ref": "evidence:scheme-2",
                "kind": "scheme",
                "page_number": 4,
                "bbox": {"x0": 0.15, "y0": 0.25, "x1": 0.75, "y1": 0.85},
                "quoted_text": "Lead 1 was optimized to compound 18.",
                "caption": "Scheme 2",
            }
        ],
        "edge_evidence_links": [
            {
                "edge_ref": "edge:lead-1-to-18",
                "evidence_ref": "evidence:scheme-2",
                "role": "supports",
            }
        ],
        "activities": [
            {
                "compound_ref": "compound:18",
                "evidence_ref": "evidence:scheme-2",
                "assay_name": "Cell potency",
                "metric": "IC50",
                "operator": "=",
                "value": "12.5",
                "unit": "nM",
                "context": "Human cells",
            }
        ],
    }


def test_accepts_one_normalized_structure_per_compound() -> None:
    payload = AiPrefillPayload.model_validate(complete_payload())

    assert payload.schema_version == 1
    assert [item.compound_label for item in payload.compounds] == [
        "Lead 1",
        "Compound 18",
    ]
    assert payload.compounds[0].structure.smiles == "CCO"
    assert payload.lineages[0].members[0].role == "root"
    assert payload.edge_evidence_links[0].role == "supports"
    assert str(payload.activities[0].value) == "12.5"


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("compounds", 0, "structure", "confidence"), 0.91),
        (
            ("compounds", 0, "structure_candidates"),
            [{"smiles": "CCO"}, {"smiles": "CCN"}],
        ),
        (("evidence", 0, "confidence"), 0.77),
    ],
)
def test_rejects_confidence_and_candidate_fields(
    path: tuple[str | int, ...],
    value: object,
) -> None:
    candidate = deepcopy(complete_payload())
    target: object = candidate
    for part in path[:-1]:
        target = target[part]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]

    with pytest.raises(ValidationError, match="extra_forbidden"):
        AiPrefillPayload.model_validate(candidate)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (
            ("lineages", 0, "members", 1, "compound_ref"),
            "compound:missing",
            "unknown Compound",
        ),
        (
            ("edge_evidence_links", 0, "edge_ref"),
            "edge:missing",
            "unknown Edge",
        ),
        (
            ("activities", 0, "evidence_ref"),
            "evidence:missing",
            "unknown Evidence",
        ),
    ],
)
def test_rejects_cross_reference_before_database_write(
    path: tuple[str | int, ...],
    value: object,
    message: str,
) -> None:
    candidate = deepcopy(complete_payload())
    target: object = candidate
    for part in path[:-1]:
        target = target[part]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]

    with pytest.raises(ValidationError, match=message):
        AiPrefillPayload.model_validate(candidate)


def test_review_hints_round_trip_and_preserve_legacy_serialization() -> None:
    original = complete_payload()
    legacy = AiPrefillPayload.model_validate(original).model_dump(mode='json')
    hinted = deepcopy(original)
    records = [hinted['compounds'][0], hinted['activities'][0], hinted['lineages'][0]['edges'][0]]
    for item in records:
        item['review_hint'] = '  Source-supported candidate; verify correspondence.  '
    payload = AiPrefillPayload.model_validate(hinted)
    encoded = payload.model_dump(mode='json')
    for item in [encoded['compounds'][0], encoded['activities'][0], encoded['lineages'][0]['edges'][0]]:
        assert item.pop('review_hint') == 'Source-supported candidate; verify correspondence.'
    assert encoded == legacy
    for item in records:
        item['review_hint'] = '   '
    assert AiPrefillPayload.model_validate(hinted).model_dump(mode='json') == legacy
    assert 'review_hint' not in legacy['compounds'][1]


@pytest.mark.parametrize('structure', [None, {}, {'smiles': None, 'molfile': None}])
def test_review_hint_does_not_allow_structureless_compounds(structure) -> None:
    candidate = complete_payload()
    candidate['compounds'][0]['review_hint'] = 'No structure found'
    candidate['compounds'][0]['structure'] = structure
    with pytest.raises(ValidationError):
        AiPrefillPayload.model_validate(candidate)


def test_review_hints_are_short() -> None:
    candidate = complete_payload()
    candidate['activities'][0]['review_hint'] = 'x' * 1001
    with pytest.raises(ValidationError):
        AiPrefillPayload.model_validate(candidate)
