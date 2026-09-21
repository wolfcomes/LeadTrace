from datetime import UTC, datetime

import pytest

from app.ai_prefill.assistance_evaluation import (
    EvaluationValidationError,
    build_evaluation_summary,
    validate_evaluation,
)
from app.ai_prefill.assistance_contracts import Evaluation


def evaluation(**overrides: object) -> Evaluation:
    value = {
        "evaluation_id": "evaluation:1",
        "experiment_id": "experiment:test",
        "candidate_id": "candidate:v1",
        "reviewer": "reviewer@example.test",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "decision": "accepted",
        "issue_codes": [],
        "notes": "looks good",
        "workspace_snapshot_id": "snapshot:1",
    }
    value.update(overrides)
    return Evaluation.model_validate(value)


def test_evaluation_requires_full_section_coverage_for_accepted_result() -> None:
    with pytest.raises(EvaluationValidationError, match="coverage"):
        validate_evaluation(
            evaluation(),
            section_coverage={"bibliography": "reviewed"},
            reviewed_workspace_version=2,
            applied_workspace_version=2,
        )


def test_edited_workspace_cannot_be_recorded_as_original_ai_acceptance() -> None:
    with pytest.raises(EvaluationValidationError, match="edited"):
        validate_evaluation(
            evaluation(),
            section_coverage={section: "reviewed" for section in (
                "bibliography", "compounds", "structures", "lineages", "edge_evidence", "activities"
            )},
            reviewed_workspace_version=3,
            applied_workspace_version=2,
        )


def test_evaluation_summary_is_plain_markdown_and_retains_decision() -> None:
    result = validate_evaluation(
        evaluation(decision="needs_revision", issue_codes=["EVIDENCE_QUOTE_NOT_FOUND"]),
        section_coverage={section: "partial" for section in (
            "bibliography", "compounds", "structures", "lineages", "edge_evidence", "activities"
        )},
        reviewed_workspace_version=2,
        applied_workspace_version=2,
    )

    summary = build_evaluation_summary(result)

    assert "needs_revision" in summary
    assert "EVIDENCE_QUOTE_NOT_FOUND" in summary
