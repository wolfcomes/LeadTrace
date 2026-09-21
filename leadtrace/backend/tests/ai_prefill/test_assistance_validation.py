from datetime import UTC, datetime

from app.ai_prefill.assistance_contracts import CandidateEnvelope, CandidateRecipe, ProducerProvenance, SourceIdentity
from app.ai_prefill.assistance_validation import validate_candidate
from app.ai_prefill.contracts import AiPrefillPayload


def make(payload: AiPrefillPayload) -> CandidateEnvelope:
    return CandidateEnvelope(
        envelope_version=1, candidate_id="candidate:v1", experiment_id="experiment:test",
        source=SourceIdentity(paper_key="paper-1", source_sha256="a" * 64, byte_size=1, page_count=1),
        producer=ProducerProvenance(kind="local", engine="test", engine_version="1", generated_at=datetime(2026, 1, 1, tzinfo=UTC)),
        recipe=CandidateRecipe(guide_version="guide-v1"), payload=payload,
    )


def test_quality_issue_allows_preview() -> None:
    payload = AiPrefillPayload.model_validate({"schema_version": 1, "compounds": [{"ref": "c1", "compound_label": "1", "structure": {"smiles": "CCO"}}], "activities": [{"compound_ref": "c1", "assay_name": "assay", "metric": "IC50", "operator": "=", "value": "1"}]})
    report = validate_candidate(make(payload))
    assert report.status == "needs_review"
    assert report.can_apply
    assert any(issue.code == "ACTIVITY_WITHOUT_EVIDENCE" for issue in report.issues)


def test_invalid_structure_blocks_preview() -> None:
    payload = AiPrefillPayload.model_validate({"schema_version": 1, "compounds": [{"ref": "c1", "compound_label": "1", "structure": {"smiles": "not-a-smiles"}}]})
    report = validate_candidate(make(payload))
    assert report.status == "invalid"
    assert not report.can_apply


def test_visual_locator_without_quote_is_reviewable() -> None:
    payload = AiPrefillPayload.model_validate({"schema_version": 1, "evidence": [{"ref": "e1", "kind": "scheme", "page_number": 1, "bbox": {"x0": "0.1", "y0": "0.1", "x1": "0.9", "y1": "0.9"}}]})
    report = validate_candidate(make(payload))
    assert report.status == "needs_review"
    assert any(issue.code == "EVIDENCE_LOCATOR_ONLY" for issue in report.issues)


def test_quote_not_found_in_supplied_pdf_text_is_needs_review() -> None:
    payload = AiPrefillPayload.model_validate(
        {
            "schema_version": 1,
            "evidence": [
                {
                    "ref": "e1",
                    "kind": "text",
                    "page_number": 1,
                    "quoted_text": "IC50 < 1.20 nM",
                }
            ],
        }
    )

    report = validate_candidate(
        make(payload),
        page_texts={1: "The reported value was IC50 > 2.00 nM."},
    )

    assert report.status == "needs_review"
    assert any(issue.code == "EVIDENCE_QUOTE_NOT_FOUND" for issue in report.issues)


def test_source_doi_conflict_is_a_technical_error() -> None:
    payload = AiPrefillPayload.model_validate(
        {"schema_version": 1, "bibliography": {"doi": "10.1000/wrong"}}
    )

    report = validate_candidate(make(payload), expected_doi="10.1000/right")

    assert report.status == "invalid"
    assert any(issue.code == "SOURCE_DOI_MISMATCH" for issue in report.issues)


def test_edge_without_evidence_is_reviewable_and_keeps_ai_reasoning():
    from .test_contract import complete_payload
    raw = complete_payload()
    raw["edge_evidence_links"] = []
    raw["evidence"] = []
    raw["activities"] = []
    raw["structure_locators"] = []
    raw["lineages"][0]["edges"][0]["modification_summary"] = "AI inference: substituent change within the reported series"
    candidate = make(AiPrefillPayload.model_validate(raw))
    report = validate_candidate(candidate)
    assert report.status == "needs_review"
    assert report.can_apply
    issue = next(issue for issue in report.issues if issue.code == "EDGE_WITHOUT_SUPPORTING_EVIDENCE")
    assert issue.entity_ref == raw["lineages"][0]["edges"][0]["ref"]
    assert issue.severity == "needs_review"
    assert candidate.payload.evidence == []


def test_ref_path_collision_is_invalid_before_preview_apply():
    payload = AiPrefillPayload.model_validate({'schema_version': 1, 'compounds': [
        {'ref': 'x', 'compound_label': '1', 'structure': {'smiles': 'CCO'}},
        {'ref': 'x/structure', 'compound_label': '2', 'structure': {'smiles': 'CCN'}},
    ]})
    report = validate_candidate(make(payload))
    assert not report.can_apply
    assert any(x.code == 'UNSAFE_ENTITY_REF' and x.entity_ref == 'x/structure' for x in report.issues)


def test_lineage_ref_cannot_impersonate_nested_entity_path():
    payload = AiPrefillPayload.model_validate({'schema_version': 1, 'lineages': [
        {'ref': 'l/edges/e', 'lineage_label': 'series', 'lineage_type': 'sar'}]})
    report = validate_candidate(make(payload))
    assert not report.can_apply
    assert any(x.code == 'UNSAFE_ENTITY_REF' for x in report.issues)
