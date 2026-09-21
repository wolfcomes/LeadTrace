"""Bind review feedback to the actual applied Preview and a coherent snapshot."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Mapping
from uuid import UUID

from sqlalchemy.orm import Session

from app.ai_prefill.assistance_contracts import (
    CandidateEnvelope, Evaluation, ValidationReport, computed_hashes,
)
from app.ai_prefill.assistance_evaluation import (
    EvaluationValidationError, SectionState, validate_evaluation,
)
from app.ai_prefill.workspace_export import read_candidate_workspace_snapshot
from app.config import Settings
from app.workspaces.snapshot import canonical_snapshot_hash


@dataclass(frozen=True, slots=True)
class WorkspaceEvaluationResult:
    evaluation: Evaluation
    snapshot: dict[str, Any]
    snapshot_sha256: str


def record_workspace_evaluation(
    session: Session,
    *,
    settings: Settings,
    candidate: CandidateEnvelope,
    report: ValidationReport,
    application_id: UUID,
    expected_workspace_version: int,
    evaluation_id: str,
    reviewer: str,
    decision: Literal["accepted", "needs_revision", "rejected"],
    section_coverage: Mapping[str, SectionState],
    notes: str | None = None,
    issue_codes: list[str] | None = None,
) -> WorkspaceEvaluationResult:
    """Return bound immutable-artifact inputs without writing files or science.

    This works for incomplete or unrepresentable scientific content: reviewers
    must be able to request revisions even when Candidate export would refuse.
    The caller persists both returned evaluation and snapshot to its artifact
    store after this read transaction completes.
    """
    if not reviewer.strip() or not evaluation_id.strip():
        raise EvaluationValidationError("reviewer and evaluation_id are required")
    hashes = computed_hashes(candidate)
    if (
        report.experiment_id != candidate.experiment_id
        or report.candidate_id != candidate.candidate_id
        or report.candidate_sha256 != hashes.candidate_sha256
        or report.payload_sha256 != hashes.payload_sha256
    ):
        raise EvaluationValidationError("validation report does not belong to the Candidate")
    if decision == "accepted" and not report.can_apply:
        raise EvaluationValidationError("an invalid validation report cannot support accepted evaluation")
    receipt, snapshot = read_candidate_workspace_snapshot(
        session, candidate, application_id=application_id,
        expected_workspace_version=expected_workspace_version, settings=settings,
    )
    applied_version = receipt.initial_snapshot.get("after_apply", {}).get("workspace_version")
    if type(applied_version) is not int or applied_version < 1:
        raise EvaluationValidationError("application receipt has no verified applied Workspace version")
    digest = canonical_snapshot_hash(snapshot)
    evaluation = Evaluation(
        evaluation_id=evaluation_id,
        experiment_id=candidate.experiment_id,
        candidate_id=candidate.candidate_id,
        reviewer=reviewer,
        created_at=datetime.now(UTC),
        decision=decision,
        issue_codes=issue_codes or [],
        notes=notes,
        workspace_snapshot_id=f"sha256:{digest}",
        candidate_sha256=hashes.candidate_sha256,
        payload_sha256=hashes.payload_sha256,
        source_sha256=candidate.source.source_sha256,
        validation_report_id=report.report_id,
        application_id=receipt.application_id,
        workspace_version=snapshot["workspace_version"],
        applied_workspace_version=applied_version,
        workspace_snapshot_sha256=digest,
        section_coverage=dict(section_coverage),
    )
    validate_evaluation(
        evaluation,
        section_coverage=evaluation.section_coverage,
        reviewed_workspace_version=evaluation.workspace_version,
        applied_workspace_version=applied_version,
    )
    return WorkspaceEvaluationResult(evaluation, snapshot, digest)


__all__ = ["WorkspaceEvaluationResult", "record_workspace_evaluation"]
