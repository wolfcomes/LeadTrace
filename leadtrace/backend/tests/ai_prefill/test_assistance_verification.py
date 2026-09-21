from datetime import UTC, datetime

import pytest

from app.ai_prefill.assistance_contracts import (
    CandidateEnvelope,
    CandidateRecipe,
    ProducerProvenance,
    SourceIdentity,
    with_computed_hashes,
)
from app.ai_prefill.assistance_validation import validate_candidate
from app.ai_prefill.assistance_verification import (
    PreviewApplicationValidationError,
    verify_candidate_for_application,
)
from app.ai_prefill.contracts import AiPrefillPayload


def candidate(payload: AiPrefillPayload) -> CandidateEnvelope:
    return with_computed_hashes(
        CandidateEnvelope(
            envelope_version=1,
            candidate_id="candidate:v1",
            experiment_id="experiment:test",
            source=SourceIdentity(
                paper_key="paper-1",
                source_sha256="a" * 64,
                byte_size=100,
                page_count=2,
            ),
            producer=ProducerProvenance(
                kind="local",
                engine="test",
                engine_version="1",
                generated_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
            recipe=CandidateRecipe(guide_version="guide-v1"),
            payload=payload,
        )
    )


def test_apply_rejects_report_for_a_different_candidate() -> None:
    value = candidate(AiPrefillPayload.model_validate({"schema_version": 1}))
    report = validate_candidate(value)
    other = candidate(
        AiPrefillPayload.model_validate(
            {
                "schema_version": 1,
                "bibliography": {"title": "different"},
            }
        )
    )

    with pytest.raises(PreviewApplicationValidationError, match="candidate hash"):
        verify_candidate_for_application(other, report)


def test_apply_recomputes_invalid_payload_even_when_report_claims_valid() -> None:
    value = candidate(
        AiPrefillPayload.model_validate(
            {
                "schema_version": 1,
                "compounds": [
                    {
                        "ref": "c1",
                        "compound_label": "1",
                        "structure": {"smiles": "not-a-smiles"},
                    }
                ],
            }
        )
    )
    forged = validate_candidate(
        candidate(AiPrefillPayload.model_validate({"schema_version": 1}))
    ).model_copy(
        update={
            "candidate_sha256": value.hashes.candidate_sha256,
            "payload_sha256": value.hashes.payload_sha256,
            "status": "valid",
            "issues": [],
        }
    )

    with pytest.raises(PreviewApplicationValidationError, match="technical"):
        verify_candidate_for_application(value, forged)


def test_needs_review_report_is_applyable_and_is_revalidated() -> None:
    value = candidate(
        AiPrefillPayload.model_validate(
            {
                "schema_version": 1,
                "compounds": [
                    {
                        "ref": "c1",
                        "compound_label": "1",
                        "structure": {"smiles": "CCO"},
                    }
                ],
                "activities": [
                    {
                        "compound_ref": "c1",
                        "assay_name": "binding",
                        "metric": "IC50",
                        "operator": "=",
                        "value": "1",
                    }
                ],
            }
        )
    )
    report = validate_candidate(value)

    result = verify_candidate_for_application(value, report)

    assert result.report.status == "needs_review"
    assert result.hashes == value.hashes


def test_request_digest_is_stable_for_the_same_application_request() -> None:
    from app.ai_prefill.preview_application import application_request_digest

    value = candidate(AiPrefillPayload.model_validate({"schema_version": 1}))
    report = validate_candidate(value)

    first = application_request_digest(
        instance_id="preview-1",
        idempotency_key="request-1",
        candidate=value,
        report=report,
        actor_id="actor-1",
        reviewer_id=None,
        paper_id="paper-1",
        workspace_id="workspace-1",
        run_id=None,
    )
    second = application_request_digest(
        instance_id="preview-1",
        idempotency_key="request-1",
        candidate=value,
        report=report,
        actor_id="actor-1",
        reviewer_id=None,
        paper_id="paper-1",
        workspace_id="workspace-1",
        run_id=None,
    )

    assert first == second
    assert len(first) == 64


def test_apply_preserves_advisory_pdf_findings_without_requiring_page_texts() -> None:
    value = candidate(AiPrefillPayload.model_validate({
        "schema_version": 1,
        "evidence": [{
            "ref": "quote:1", "kind": "text", "page_number": 1,
            "quoted_text": "Reported potency was 1 nM.",
        }],
    }))
    report = validate_candidate(value, page_texts={1: "Unrelated table"})
    assert report.status == "needs_review"
    result = verify_candidate_for_application(value, report)
    assert result.report.status == "needs_review"
    assert result.report.issues == report.issues


def test_apply_rejects_forged_valid_status_with_advisory_issues() -> None:
    value = candidate(AiPrefillPayload.model_validate({
        "schema_version": 1,
        "evidence": [{
            "ref": "quote:1", "kind": "text", "page_number": 1,
            "quoted_text": "Reported potency was 1 nM.",
        }],
    }))
    report = validate_candidate(value, page_texts={}).model_copy(update={"status": "valid"})
    with pytest.raises(PreviewApplicationValidationError):
        verify_candidate_for_application(value, report)


@pytest.mark.parametrize("tamper", ["remove", "alter"])
def test_pdf_advisory_does_not_exempt_candidate_derived_issues(tamper: str) -> None:
    value = candidate(AiPrefillPayload.model_validate({
        "schema_version": 1,
        "compounds": [{"ref": "c1", "compound_label": "1", "structure": {"smiles": "CCO"}}],
        "activities": [{
            "compound_ref": "c1", "assay_name": "binding", "metric": "IC50",
            "operator": "=", "value": "1",
        }],
        "evidence": [{
            "ref": "quote:1", "kind": "text", "page_number": 1,
            "quoted_text": "Reported potency was 1 nM.",
        }],
    }))
    report = validate_candidate(value, page_texts={})
    assert {issue.code for issue in report.issues} == {
        "ACTIVITY_WITHOUT_EVIDENCE", "EVIDENCE_TEXT_UNAVAILABLE",
    }
    assert verify_candidate_for_application(value, report).report.issues == report.issues
    altered = [issue for issue in report.issues if issue.code != "ACTIVITY_WITHOUT_EVIDENCE"]
    if tamper == "alter":
        activity_issue = next(issue for issue in report.issues if issue.code == "ACTIVITY_WITHOUT_EVIDENCE")
        altered.append(activity_issue.model_copy(update={"path": "payload.activities[99]"}))
    with pytest.raises(PreviewApplicationValidationError, match="issues"):
        verify_candidate_for_application(value, report.model_copy(update={"issues": altered}))
    with pytest.raises(PreviewApplicationValidationError, match="issues"):
        verify_candidate_for_application(value, report, page_texts={1: "Reported potency was 1 nM."})
