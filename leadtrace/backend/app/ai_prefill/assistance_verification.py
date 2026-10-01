"""Apply-time verification for portable AI-prefill candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping
from uuid import UUID

from app.ai_prefill.assistance_contracts import (
    CandidateEnvelope,
    CandidateHashes,
    ValidationReport,
    computed_hashes,
)
from app.ai_prefill.assistance_validation import validate_candidate
from app.ai_prefill.models import AiExtractionRun, AiExtractionRunStatus
from app.activities.models import Activity
from app.compounds.models import Compound, CompoundHighlight
from app.evidence.models import EdgeEvidenceLink, Evidence
from app.lineages.models import Lineage, LineageEdge, LineageMember
from app.structure_images.models import StructureSourceImage
from app.structures.models import Structure
from app.workspaces.models import ChangeActorKind, ChangeEvent, PaperWorkspace


class PreviewApplicationValidationError(ValueError):
    """Raised when a candidate cannot be safely applied to a Preview workspace."""


@dataclass(frozen=True, slots=True)
class ApplicationVerification:
    candidate: CandidateEnvelope
    report: ValidationReport
    hashes: CandidateHashes


@dataclass(frozen=True, slots=True)
class ReceiptVerification:
    status: Literal["committed", "changed_since_apply", "integrity_failure"]
    details: dict[str, object]


_ENTITY_MODELS: tuple[tuple[str, type[object]], ...] = (
    ("/compounds/", Compound),
    ("/compound_highlights/", CompoundHighlight),
    ("/structure_locators/", StructureSourceImage),
    ("/lineages/", Lineage),
    ("/evidence/", Evidence),
    ("/edge_evidence_links/", EdgeEvidenceLink),
    ("/activities/", Activity),
)


def _entity_model(path: str) -> type[object] | None:
    if path.startswith("/compounds/") and path.endswith("/structure"):
        return Structure
    if path.startswith("/lineages/") and "/members/" in path:
        return LineageMember
    if path.startswith("/lineages/") and "/edges/" in path:
        return LineageEdge
    for prefix, model in _ENTITY_MODELS:
        if path.startswith(prefix):
            return model
    return None


def verify_application_receipt(
    session: object,
    receipt: object,
) -> ReceiptVerification:
    """Verify a committed receipt without mutating the database.

    The function deliberately accepts a narrow Session-like object so it can be
    used by offline verification tooling and tested without opening a database
    connection.  It only calls ``get`` and ``scalar``.
    """

    workspace_id = getattr(receipt, "workspace_id", None)
    paper_id = getattr(receipt, "paper_id", None)
    run_id = getattr(receipt, "run_id", None)
    workspace = session.get(PaperWorkspace, workspace_id)  # type: ignore[attr-defined]
    run = session.get(AiExtractionRun, run_id) if run_id is not None else None  # type: ignore[attr-defined]
    if workspace is None or run is None:
        return ReceiptVerification(
            "integrity_failure",
            {"reason": "workspace_or_run_missing"},
        )
    if (
        workspace.paper_id != paper_id
        or run.paper_id != paper_id
        or run.workspace_id != workspace_id
        or run.status is not AiExtractionRunStatus.SUCCEEDED
    ):
        return ReceiptVerification(
            "integrity_failure",
            {"reason": "workspace_or_run_identity_mismatch"},
        )

    entity_map = getattr(receipt, "entity_map", {}) or {}
    for path, raw_id in entity_map.items():
        model = _entity_model(str(path))
        if model is None:
            return ReceiptVerification(
                "integrity_failure",
                {"reason": "unknown_entity_path", "path": str(path)},
            )
        try:
            entity_id = UUID(str(raw_id))
        except (TypeError, ValueError):
            return ReceiptVerification(
                "integrity_failure",
                {"reason": "invalid_entity_id", "path": str(path)},
            )
        entity = session.get(model, entity_id)  # type: ignore[attr-defined]
        if entity is None:
            return ReceiptVerification(
                "integrity_failure",
                {"reason": "entity_missing", "missing_entity": str(path)},
            )
        if (
            getattr(entity, "workspace_id", None) != workspace_id
            or getattr(entity, "paper_id", None) != paper_id
        ):
            return ReceiptVerification(
                "integrity_failure",
                {"reason": "entity_identity_mismatch", "path": str(path)},
            )

    event_count = session.scalar(  # type: ignore[attr-defined]
        select_count_ai_events(run_id, workspace_id, paper_id)
    )
    expected_event_count = int(
        (getattr(receipt, "initial_snapshot", {}) or {})
        .get("after_apply", {})
        .get("ai_event_count", 0)
    )
    if int(event_count or 0) < expected_event_count:
        return ReceiptVerification(
            "integrity_failure",
            {
                "reason": "ai_event_history_incomplete",
                "expected_event_count": expected_event_count,
                "actual_event_count": int(event_count or 0),
            },
        )

    expected_version = int(
        (getattr(receipt, "initial_snapshot", {}) or {})
        .get("after_apply", {})
        .get("workspace_version", 0)
    )
    details = {
        "workspace_version": workspace.version,
        "expected_workspace_version": expected_version,
        "ai_event_count": int(event_count or 0),
        "entity_count": len(entity_map),
    }
    if workspace.version < expected_version:
        return ReceiptVerification(
            "integrity_failure",
            {**details, "reason": "workspace_version_regressed"},
        )
    if workspace.version > expected_version:
        return ReceiptVerification("changed_since_apply", details)
    return ReceiptVerification("committed", details)


def select_count_ai_events(run_id: UUID, workspace_id: UUID, paper_id: UUID) -> object:
    """Build the read-only event count query in one place for verification."""

    from sqlalchemy import func, select

    return (
        select(func.count())
        .select_from(ChangeEvent)
        .where(
            ChangeEvent.ai_run_id == run_id,
            ChangeEvent.workspace_id == workspace_id,
            ChangeEvent.paper_id == paper_id,
            ChangeEvent.actor_kind == ChangeActorKind.AI,
        )
    )


def verify_candidate_for_application(
    candidate: CandidateEnvelope,
    report: ValidationReport,
    *,
    expected_source_sha256: str | None = None,
    expected_page_count: int | None = None,
    expected_doi: str | None = None,
    page_texts: Mapping[int, str] | None = None,
) -> ApplicationVerification:
    """Recompute all apply identities and technical checks.

    A stored validation report is evidence for the operator workflow, not an
    authorization token.  The candidate is validated again from the bytes
    supplied to this call so a forged status or a changed artifact cannot
    bypass technical checks.
    """

    hashes = computed_hashes(candidate)
    if candidate.hashes is not None and candidate.hashes != hashes:
        raise PreviewApplicationValidationError(
            "declared candidate hashes do not match candidate content"
        )
    if report.candidate_id != candidate.candidate_id:
        raise PreviewApplicationValidationError("validation report candidate id mismatch")
    if report.experiment_id != candidate.experiment_id:
        raise PreviewApplicationValidationError("validation report experiment id mismatch")
    if report.candidate_sha256 != hashes.candidate_sha256:
        raise PreviewApplicationValidationError("validation report candidate hash mismatch")
    if report.payload_sha256 != hashes.payload_sha256:
        raise PreviewApplicationValidationError("validation report payload hash mismatch")

    live_report = validate_candidate(
        candidate,
        report_id=report.report_id,
        profile_version=report.profile_version,
        validator_version=report.validator_version,
        expected_source_sha256=expected_source_sha256,
        expected_page_count=expected_page_count,
        expected_doi=expected_doi,
        page_texts=page_texts,
    )
    if any(issue.severity == "error" for issue in live_report.issues):
        raise PreviewApplicationValidationError(
            "technical validation errors prevent Preview application"
        )

    # PDF text is optional during apply. Its advisory findings remain visible,
    # while every technical and candidate-only check is recomputed below.
    advisory_codes = {"EVIDENCE_TEXT_UNAVAILABLE", "EVIDENCE_QUOTE_NOT_FOUND"}
    advisory_issues = [
        issue for issue in report.issues
        if page_texts is None
        and issue.code in advisory_codes
        and issue.severity == "needs_review"
    ]
    comparable_issues = [issue for issue in report.issues if issue not in advisory_issues]
    expected_status = "needs_review" if live_report.issues or advisory_issues else "valid"
    if expected_status != report.status:
        raise PreviewApplicationValidationError(
            "validation report status does not match current technical validation"
        )
    if live_report.issues != comparable_issues:
        raise PreviewApplicationValidationError(
            "validation report issues do not match current technical validation"
        )
    if advisory_issues:
        live_report = live_report.model_copy(
            update={"status": expected_status, "issues": report.issues}
        )
    return ApplicationVerification(candidate, live_report, hashes)


__all__ = [
    "ApplicationVerification",
    "PreviewApplicationValidationError",
    "ReceiptVerification",
    "verify_candidate_for_application",
    "verify_application_receipt",
]
