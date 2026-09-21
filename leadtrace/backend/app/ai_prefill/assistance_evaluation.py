"""Structured human evaluation rules for AI-prefill candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

from app.ai_prefill.assistance_contracts import Evaluation


SectionState = Literal["reviewed", "partial", "not_reviewed", "not_applicable"]
SECTIONS = (
    "bibliography",
    "compounds",
    "structures",
    "lineages",
    "edge_evidence",
    "activities",
)


class EvaluationValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ValidatedEvaluation:
    evaluation: Evaluation
    section_coverage: dict[str, SectionState]
    reviewed_workspace_version: int
    applied_workspace_version: int


def validate_evaluation(
    evaluation: Evaluation,
    *,
    section_coverage: Mapping[str, SectionState],
    reviewed_workspace_version: int,
    applied_workspace_version: int,
) -> ValidatedEvaluation:
    if set(section_coverage) != set(SECTIONS):
        raise EvaluationValidationError(
            "section coverage must contain all six required sections"
        )
    if reviewed_workspace_version < 1 or applied_workspace_version < 1:
        raise EvaluationValidationError("workspace versions must be positive")
    coverage = dict(section_coverage)
    if evaluation.decision == "accepted":
        if any(value not in {"reviewed", "not_applicable"} for value in coverage.values()):
            raise EvaluationValidationError(
                "accepted evaluation requires complete section coverage"
            )
        if reviewed_workspace_version != applied_workspace_version:
            raise EvaluationValidationError(
                "edited workspace cannot be accepted as the original AI result"
            )
    return ValidatedEvaluation(
        evaluation=evaluation,
        section_coverage=coverage,
        reviewed_workspace_version=reviewed_workspace_version,
        applied_workspace_version=applied_workspace_version,
    )


def build_evaluation_summary(value: ValidatedEvaluation) -> str:
    evaluation = value.evaluation
    lines = [
        f"# Evaluation {evaluation.evaluation_id}",
        "",
        f"- Decision: `{evaluation.decision}`",
        f"- Candidate: `{evaluation.candidate_id}`",
        f"- Reviewer: `{evaluation.reviewer}`",
        f"- Workspace version: `{value.reviewed_workspace_version}`",
        "",
        "## Section Coverage",
    ]
    lines.extend(
        f"- {section}: `{value.section_coverage[section]}`" for section in SECTIONS
    )
    if evaluation.issue_codes:
        lines.extend(["", "## Issues", *[f"- `{code}`" for code in evaluation.issue_codes]])
    if evaluation.notes:
        lines.extend(["", "## Notes", evaluation.notes])
    return "\n".join(lines) + "\n"


__all__ = [
    "EvaluationValidationError",
    "SECTIONS",
    "ValidatedEvaluation",
    "build_evaluation_summary",
    "validate_evaluation",
]
