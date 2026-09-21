"""Shared validation for portable AI-prefill candidates."""

from __future__ import annotations

from datetime import UTC, datetime
import re
import unicodedata
from uuid import uuid4
from collections.abc import Mapping

from app.ai_prefill.assistance_contracts import (
    CandidateEnvelope,
    ValidationIssue,
    ValidationReport,
    computed_hashes,
)
from app.structures.service import _parse_molfile, _parse_smiles


def _issue(code: str, severity: str, path: str, message: str, **kwargs: object) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        severity=severity,  # type: ignore[arg-type]
        path=path,
        message=message,
        entity_ref=kwargs.get("entity_ref"),
        details=kwargs.get("details", {}),  # type: ignore[arg-type]
    )


def _normalize_quote(value: str) -> str:
    """Normalize layout whitespace while retaining scientific punctuation."""

    normalized = unicodedata.normalize("NFKC", value)
    normalized = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def validate_candidate(
    candidate: CandidateEnvelope,
    *,
    report_id: str | None = None,
    profile_version: str = "core-v1",
    validator_version: str = "assistance-validation-v1",
    expected_source_sha256: str | None = None,
    expected_page_count: int | None = None,
    expected_doi: str | None = None,
    page_texts: Mapping[int, str] | None = None,
) -> ValidationReport:
    """Return a report; never writes scientific records or touches a database."""

    issues: list[ValidationIssue] = []
    # Receipts encode references as path segments. Reject ambiguous segments at
    # the assistance boundary without changing legacy payload serialization.
    references = [
        (f"payload.{name}[{index}].ref", item.ref)
        for name in ("compounds", "structure_locators", "lineages", "evidence")
        for index, item in enumerate(getattr(candidate.payload, name))
    ]
    references.extend(
        (f"payload.lineages[{li}].edges[{ei}].ref", edge.ref)
        for li, lineage in enumerate(candidate.payload.lineages)
        for ei, edge in enumerate(lineage.edges)
    )
    for path, ref in references:
        if "/" in ref:
            issues.append(_issue("UNSAFE_ENTITY_REF", "error", path,
                                 "Entity refs cannot contain '/' because receipt paths use it as a separator",
                                 entity_ref=ref))
    hashes = computed_hashes(candidate)
    if candidate.hashes is not None and candidate.hashes != hashes:
        issues.append(_issue("HASH_MISMATCH", "error", "hashes", "Declared hashes do not match candidate content"))
    if expected_source_sha256 is not None and candidate.source.source_sha256 != expected_source_sha256:
        issues.append(_issue("SOURCE_DRIFT", "error", "source.source_sha256", "Candidate source hash differs from the selected PDF"))
    candidate_doi = candidate.payload.bibliography.doi
    if expected_doi is not None and candidate_doi is not None and candidate_doi.casefold() != expected_doi.casefold():
        issues.append(_issue("SOURCE_DOI_MISMATCH", "error", "payload.bibliography.doi", "Candidate DOI conflicts with the selected source"))
    page_count = expected_page_count or candidate.source.page_count
    for collection_name in ("structure_locators", "evidence"):
        for index, item in enumerate(getattr(candidate.payload, collection_name)):
            if item.page_number > page_count:
                issues.append(_issue("PAGE_OUT_OF_RANGE", "error", f"payload.{collection_name}[{index}].page_number", "Page is outside the source PDF", entity_ref=item.ref))
            bbox = getattr(item, "bbox", None)
            if bbox is not None and not (0 <= bbox.x0 < bbox.x1 <= 1 and 0 <= bbox.y0 < bbox.y1 <= 1):
                issues.append(_issue("BBOX_INVALID", "error", f"payload.{collection_name}[{index}].bbox", "Bounding box must have positive normalized area", entity_ref=item.ref))
            if collection_name == "evidence" and not item.quoted_text and not item.caption:
                issues.append(_issue("EVIDENCE_LOCATOR_ONLY", "needs_review", f"payload.evidence[{index}]", "Evidence has only a visual locator; inspect the PDF manually", entity_ref=item.ref))
            if collection_name == "evidence" and item.quoted_text and page_texts is not None:
                page_text = page_texts.get(item.page_number, "")
                if not page_text:
                    issues.append(_issue("EVIDENCE_TEXT_UNAVAILABLE", "needs_review", f"payload.evidence[{index}].quoted_text", "The declared PDF page has no extractable text; inspect it manually", entity_ref=item.ref))
                elif _normalize_quote(item.quoted_text) not in _normalize_quote(page_text):
                    issues.append(_issue("EVIDENCE_QUOTE_NOT_FOUND", "needs_review", f"payload.evidence[{index}].quoted_text", "Quoted text was not found on the declared PDF page", entity_ref=item.ref))
            if collection_name == "evidence" and item.quoted_text and item.kind != "text":
                issues.append(_issue("EVIDENCE_VISUAL_QUOTE", "needs_review", f"payload.evidence[{index}].quoted_text", "Quote accompanies a visual evidence item; verify both", entity_ref=item.ref))
    for index, compound in enumerate(candidate.payload.compounds):
        structure = compound.structure
        if bool(structure.smiles) == bool(structure.molfile):
            issues.append(_issue("STRUCTURE_REPRESENTATION", "error", f"payload.compounds[{index}].structure", "Exactly one of smiles or molfile is required", entity_ref=compound.ref))
            continue
        parsed = _parse_smiles(structure.smiles) if structure.smiles else _parse_molfile(structure.molfile or "")
        if not parsed.parseable:
            issues.append(_issue("STRUCTURE_INVALID", "error", f"payload.compounds[{index}].structure", "Structure cannot be parsed by the shared RDKit validator", entity_ref=compound.ref))
    supported_edge_refs = {
        link.edge_ref for link in candidate.payload.edge_evidence_links
        if link.role == "supports"
    }
    for lineage_index, lineage in enumerate(candidate.payload.lineages):
        for edge_index, edge in enumerate(lineage.edges):
            if edge.ref not in supported_edge_refs:
                issues.append(_issue(
                    "EDGE_WITHOUT_SUPPORTING_EVIDENCE", "needs_review",
                    f"payload.lineages[{lineage_index}].edges[{edge_index}]",
                    "Edge is allowed without supporting Evidence; verify the AI reasoning and relationship manually",
                    entity_ref=edge.ref,
                ))
    evidence_refs = {item.ref for item in candidate.payload.evidence}
    for index, activity in enumerate(candidate.payload.activities):
        if activity.evidence_ref is None:
            issues.append(_issue("ACTIVITY_WITHOUT_EVIDENCE", "needs_review", f"payload.activities[{index}]", "Activity has no linked Evidence", entity_ref=activity.compound_ref))
        elif activity.evidence_ref not in evidence_refs:
            issues.append(_issue("ACTIVITY_EVIDENCE_MISSING", "error", f"payload.activities[{index}].evidence_ref", "Activity references missing Evidence", entity_ref=activity.compound_ref))
    status = "invalid" if any(item.severity == "error" for item in issues) else ("needs_review" if issues else "valid")
    return ValidationReport(
        report_id=report_id or f"validation:{uuid4().hex}",
        experiment_id=candidate.experiment_id,
        candidate_id=candidate.candidate_id,
        candidate_sha256=hashes.candidate_sha256,
        payload_sha256=hashes.payload_sha256,
        profile_version=profile_version,
        validator_version=validator_version,
        status=status,
        issues=issues,
        created_at=datetime.now(UTC),
    )


__all__ = ["validate_candidate"]
