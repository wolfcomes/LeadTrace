"""Export scientific Workspace rows and retain review state in a separate snapshot."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_prefill.assistance_contracts import (
    CandidateEnvelope, CandidateOmission, ProducerProvenance, computed_hashes,
    validate_declared_hashes, with_computed_hashes,
)
from app.ai_prefill.assistance_validation import validate_candidate
from app.ai_prefill.contracts import AiPrefillPayload
from app.ai_prefill.preview_identity import verify_preview_connection
from app.ai_prefill.preview_models import ApplicationReceipt
from app.catalog.models import PaperSource
from app.config import Settings
from app.papers.models import Paper
from app.workspaces.models import PaperWorkspace
from app.workspaces.snapshot import build_paper_snapshot, canonical_snapshot_hash


class WorkspaceExportConflictError(ValueError):
    pass


class WorkspaceExportUnrepresentableError(ValueError):
    def __init__(self, issues: list[dict[str, str]]) -> None:
        self.issues = issues
        super().__init__("Workspace cannot be represented by Candidate v1: " + "; ".join(
            f"{issue['path']}: {issue['message']}" for issue in issues
        ))


@dataclass(frozen=True, slots=True)
class WorkspaceCandidateExport:
    candidate: CandidateEnvelope
    snapshot: dict[str, Any]
    snapshot_sha256: str
    workspace_version: int
    entity_refs: dict[str, str]
    review_metadata: list[dict[str, Any]]


def export_candidate_revision(
    parent: CandidateEnvelope, *, payload: AiPrefillPayload, candidate_id: str,
    evaluation_id: str, reviewer: str, expected_workspace_version: int | None = None,
    current_workspace_version: int | None = None,
) -> CandidateEnvelope:
    """Wrap caller-edited payload; this does not read or verify database state."""
    if not reviewer.strip():
        raise ValueError("reviewer is required")
    if expected_workspace_version is not None and current_workspace_version != expected_workspace_version:
        raise WorkspaceExportConflictError("workspace version changed during export")
    if not evaluation_id.strip():
        raise ValueError("evaluation_id is required")
    if candidate_id == parent.candidate_id:
        raise ValueError("child candidate_id must differ from its parent")
    validate_declared_hashes(parent)
    return with_computed_hashes(CandidateEnvelope(
        envelope_version=parent.envelope_version, candidate_id=candidate_id,
        experiment_id=parent.experiment_id, source=parent.source,
        producer=ProducerProvenance(kind="human-assisted", engine=f"reviewer:{reviewer}",
            engine_version="payload-export-v1", generated_at=datetime.now(UTC)),
        recipe=parent.recipe, parent_candidate_id=parent.candidate_id,
        input_evaluation_ids=list(dict.fromkeys([*parent.input_evaluation_ids, evaluation_id])),
        omissions=parent.omissions, payload=payload,
    ))


def _payload_from_snapshot(
    parent: CandidateEnvelope,
    snapshot: dict[str, Any],
    entity_map: dict[str, object],
    initial_paper: dict[str, Any],
) -> tuple[AiPrefillPayload, dict[str, str], list[dict[str, Any]]]:
    """Explicit field mapping, never deserialize an internal snapshot as payload."""
    issues: list[dict[str, str]] = []
    review_metadata: list[dict[str, Any]] = []
    entity_refs: dict[str, str] = {}

    def issue(path, message):
        issues.append({"path": path, "message": message})

    def refs(rows, originals, prefix, kind):
        existing = {}
        mapped = {}
        for original in originals:
            identifier = entity_map.get(f"{prefix}/{original.ref}")
            if identifier:
                mapped.setdefault(str(identifier), []).append(original)
        row_ids = {row["id"] for row in rows}
        for identifier, aliases in mapped.items():
            # Only source locators may intentionally alias one stored occurrence.
            # Use the same database precision as apply, not approximate geometry.
            same_occurrence = False
            if len(aliases) > 1 and kind == "locator":
                from app.ai_prefill.occurrences import occurrence_groups
                same_occurrence = len(occurrence_groups(aliases)) == 1
            if len(aliases) > 1 and not same_occurrence:
                issue(prefix, "Application receipt maps multiple refs to one row")
            existing[identifier] = aliases[0].ref
            if same_occurrence and identifier in row_ids:
                review_metadata.append({
                    "path": f"structure_locators/{aliases[0].ref}",
                    "locator_aliases": [item.ref for item in aliases],
                    "original_annotations": [
                        {"ref": item.ref, "label": item.label, "source_context": item.source_context}
                        for item in aliases
                    ],
                })
        reserved = {original.ref for original in originals}
        result = {}
        for row in rows:
            ref = existing.get(row["id"])
            if ref is None:
                ref = f"human:{kind}:{UUID(row['id']).hex}"
                while ref in reserved:
                    ref += ":new"
            reserved.add(ref)
            result[row["id"]] = ref
            entity_refs[row["id"]] = ref
        return result

    def ordered(name):
        return sorted(snapshot[name], key=lambda row: (row.get("sort_order", 0), row["id"]))

    def fields(row, names):
        return {name: row[name] for name in names}

    def bbox(row):
        if all(row[name] is None for name in ("x0", "y0", "x1", "y1")):
            return None
        return fields(row, ("x0", "y0", "x1", "y1"))

    compounds = ordered("compounds")
    lineages = ordered("lineages")
    evidence = ordered("evidence")
    locators = ordered("structure_source_images")
    compound_refs = refs(compounds, parent.payload.compounds, "/compounds", "compound")
    lineage_refs = refs(lineages, parent.payload.lineages, "/lineages", "lineage")
    evidence_refs = refs(evidence, parent.payload.evidence, "/evidence", "evidence")
    locator_refs = refs(locators, parent.payload.structure_locators, "/structure_locators", "locator")
    edge_refs = {}
    for lineage in lineages:
        original = next((item for item in parent.payload.lineages if item.ref == lineage_refs[lineage["id"]]), None)
        edge_refs.update(refs(
            [row for row in ordered("lineage_edges") if row["lineage_id"] == lineage["id"]],
            original.edges if original else [], f"/lineages/{lineage_refs[lineage['id']]}/edges", "edge"))

    def reference(mapping, identifier, path):
        if identifier not in mapping:
            issue(path, "Reference points outside exported Workspace")
            return "invalid:missing"
        return mapping[identifier]

    structures = {row["compound_id"]: row for row in snapshot["structures"]}
    payload: dict[str, Any] = {
        "schema_version": 1,
        "bibliography": fields(snapshot["paper"], ("title", "journal", "publication_year", "volume", "issue", "doi")),
        "compounds": [], "structure_locators": [], "lineages": [], "evidence": [],
        "edge_evidence_links": [], "activities": [],
    }
    for field in ('abstract', 'abstract_source', 'pdb_references'):
        if snapshot['paper'].get(field) or initial_paper.get(field):
            payload['bibliography'][field] = snapshot['paper'].get(field, [] if field == 'pdb_references' else None)
    for name, value in payload["bibliography"].items():
        if name not in ('abstract', 'abstract_source', 'pdb_references') and value is None and (name not in initial_paper or initial_paper[name] is not None):
            issue(f"bibliography/{name}", "Candidate v1 cannot express clearing a baseline value; a known null baseline is required")
    for compound in compounds:
        structure = structures.get(compound["id"])
        path = f"compounds/{compound_refs[compound['id']]}/structure"
        if structure is None or not (structure["smiles"] or structure["molfile"]):
            issue(path, "Candidate v1 requires a resolved SMILES or Molfile for every Compound")
            continue
        if structure["status"] in {"unresolved", "not_reported"}:
            issue(path, "Unresolved or not-reported Structure cannot be represented as a resolved Candidate Structure")
        # RDKit stores both derived forms. Keep the actual input, not both.
        use_molfile = structure["input_method"] == "structure_editor" or not structure["smiles"]
        representation = {"molfile": structure["molfile"]} if use_molfile else {"smiles": structure["smiles"]}
        payload["compounds"].append({"ref": compound_refs[compound["id"]],
            **fields(compound, ("compound_label", "display_name", "description")), "review_hint": compound.get("review_hint"), "structure": representation})
        review_metadata.append({"path": path, **fields(structure, ("status", "input_method"))})
    for image in locators:
        if image["reviewer_note"]:
            issue(f"structure_locators/{locator_refs[image['id']]}/reviewer_note", "Candidate v1 cannot carry a structure locator reviewer note")
        if image["source_sha256"] != parent.source.source_sha256:
            issue(f"structure_locators/{locator_refs[image['id']]}", "Source hash differs from parent Candidate")
        payload["structure_locators"].append({"ref": locator_refs[image["id"]],
            "compound_ref": reference(compound_refs, image["compound_id"], "structure_locators"),
            "bbox": bbox(image), **fields(image, ("page_number", "source_context", "label"))})
    for lineage in lineages:
        members, edges = [], []
        for row in ordered("lineage_members"):
            if row["lineage_id"] == lineage["id"]:
                members.append({"compound_ref": reference(compound_refs, row["compound_id"], "lineage_members"), "role": row["role"]})
        for row in ordered("lineage_edges"):
            if row["lineage_id"] != lineage["id"]:
                continue
            if row["review_status"] == "unresolved":
                issue(f"lineages/{lineage_refs[lineage['id']]}/edges/{edge_refs[row['id']]}", "Unresolved lineage relation cannot be represented by Candidate v1")
            review_metadata.append({"path": f"edges/{edge_refs[row['id']]}", "review_status": row["review_status"]})
            edges.append({"ref": edge_refs[row["id"]],
                "parent_compound_ref": reference(compound_refs, row["parent_compound_id"], "lineage_edges"),
                "child_compound_ref": reference(compound_refs, row["child_compound_id"], "lineage_edges"),
                **fields(row, ("relation_type", "modification_summary")), "review_hint": row.get("review_hint")})
        payload["lineages"].append({"ref": lineage_refs[lineage["id"]], **fields(lineage, ("lineage_label", "description")), "lineage_type": lineage.get("lineage_type", "unspecified"), "members": members, "edges": edges})
    for row in evidence:
        if row["reviewer_note"]:
            issue(f"evidence/{evidence_refs[row['id']]}/reviewer_note", "Candidate v1 cannot carry an Evidence reviewer note")
        if row["source_sha256"] != parent.source.source_sha256:
            issue(f"evidence/{evidence_refs[row['id']]}", "Source hash differs from parent Candidate")
        payload["evidence"].append({"ref": evidence_refs[row["id"]], "bbox": bbox(row), **fields(row, ("kind", "page_number", "quoted_text", "caption"))})
    for row in ordered("edge_evidence_links"):
        payload["edge_evidence_links"].append({
            "edge_ref": reference(edge_refs, row["edge_id"], "edge_evidence_links"),
            "evidence_ref": reference(evidence_refs, row["evidence_id"], "edge_evidence_links"), "role": row["role"]})
    for row in ordered("activities"):
        payload["activities"].append({
            "compound_ref": reference(compound_refs, row["compound_id"], "activities"),
            "evidence_ref": reference(evidence_refs, row["evidence_id"], "activities") if row["evidence_id"] else None,
            **fields(row, ("assay_name", "metric", "operator", "value", "unit", "context")), "review_hint": row.get("review_hint")})
    highlights = snapshot.get('compound_highlights', [])
    highlight_refs = refs(highlights, parent.payload.compound_highlights, '/compound_highlights', 'highlight')
    if highlights:
        payload['compound_highlights'] = []
    for row in highlights:
        ref = highlight_refs[row['id']]
        payload['compound_highlights'].append({'ref': ref,
            'compound_ref': reference(compound_refs, row['compound_id'], 'compound_highlights'),
            'evidence_ref': reference(evidence_refs, row['evidence_id'], 'compound_highlights'),
            **fields(row, ('role','scope','rationale')), 'review_hint': row.get('review_hint')})
        review_metadata.append({'path': f'compound_highlights/{ref}', 'review_status': row['review_status']})
    review_metadata.extend({"path": f"sections/{row['section_key']}", **fields(row, ("state", "note"))} for row in snapshot["sections"])
    if issues:
        raise WorkspaceExportUnrepresentableError(issues)
    try:
        return AiPrefillPayload.model_validate(payload), entity_refs, review_metadata
    except ValidationError as exc:
        raise WorkspaceExportUnrepresentableError([
            {"path": "/".join(str(part) for part in item["loc"]), "message": item["msg"]}
            for item in exc.errors()]) from exc


def read_candidate_workspace_snapshot(
    session: Session, parent: CandidateEnvelope, *, application_id: UUID,
    expected_workspace_version: int, settings: Settings,
) -> tuple[ApplicationReceipt, dict[str, Any]]:
    """Read one coherent applied Workspace under its normal mutation lock.

    Export and evaluation share this identity/version boundary. The caller owns
    the transaction; every lock remains held until that transaction finishes.
    """
    if type(expected_workspace_version) is not int or expected_workspace_version < 1:
        raise ValueError("expected_workspace_version must be a positive integer")
    if session.new or session.dirty or session.deleted:
        raise WorkspaceExportConflictError("export requires a clean session without pending edits")
    validate_declared_hashes(parent)
    verify_preview_connection(settings, session.connection(), lock=True)
    receipt = session.scalar(select(ApplicationReceipt).where(
        ApplicationReceipt.application_id == application_id,
        ApplicationReceipt.instance_id == settings.preview_instance_id,
    ).execution_options(populate_existing=True))
    hashes = computed_hashes(parent)
    if receipt is None or (receipt.candidate_sha256, receipt.payload_sha256, receipt.source_sha256) != (
        hashes.candidate_sha256, hashes.payload_sha256, parent.source.source_sha256):
        raise WorkspaceExportConflictError("application does not belong to the parent Candidate in this Preview")
    workspace = session.scalar(select(PaperWorkspace).where(
        PaperWorkspace.id == receipt.workspace_id, PaperWorkspace.paper_id == receipt.paper_id,
    ).with_for_update().execution_options(populate_existing=True))
    if workspace is None or workspace.version != expected_workspace_version:
        raise WorkspaceExportConflictError("workspace version changed during export")
    paper = session.scalar(select(Paper).where(Paper.id == receipt.paper_id).with_for_update().execution_options(populate_existing=True))
    source = session.scalar(select(PaperSource).where(PaperSource.id == paper.source_id).with_for_update().execution_options(populate_existing=True))
    if source is None or (paper.paper_key, source.sha256, source.byte_size, source.page_count) != (
        parent.source.paper_key, parent.source.source_sha256, parent.source.byte_size, parent.source.page_count):
        raise WorkspaceExportConflictError("Workspace Source differs from parent Candidate")
    # Reload any cached scientific rows now that the aggregate is locked.
    session.expire_all()
    snapshot = build_paper_snapshot(session, workspace.id)
    return receipt, snapshot


def export_workspace_candidate(
    session: Session, parent: CandidateEnvelope, *, application_id: UUID,
    expected_workspace_version: int, candidate_id: str, evaluation_id: str,
    reviewer: str, settings: Settings,
) -> WorkspaceCandidateExport:
    """Read under the lock used by ordinary reviewer edits; caller owns transaction.

    Save both Candidate and snapshot. Review confirmations remain in the latter;
    applying the child begins a fresh review. This function changes no science.
    """
    receipt, snapshot = read_candidate_workspace_snapshot(
        session, parent, application_id=application_id,
        expected_workspace_version=expected_workspace_version, settings=settings,
    )
    digest = canonical_snapshot_hash(snapshot)
    payload, entity_refs, review_metadata = _payload_from_snapshot(parent, snapshot, receipt.entity_map, receipt.initial_snapshot.get("paper", {}))
    child = export_candidate_revision(parent, payload=payload, candidate_id=candidate_id,
        evaluation_id=evaluation_id, reviewer=reviewer,
        expected_workspace_version=expected_workspace_version,
        current_workspace_version=snapshot["workspace_version"])
    child = child.model_copy(update={
        "producer": child.producer.model_copy(update={"engine_version": "workspace-export-v1"}),
        "omissions": [*child.omissions, CandidateOmission(path="/workspace_review_metadata",
            reason=f"Review confirmations and section states are retained in Workspace snapshot SHA-256 {digest}; they are not automatically reapplied as approval in a new Preview.")],
    })
    child = with_computed_hashes(child)
    report = validate_candidate(child)
    errors = [{"path": issue.path, "message": issue.message} for issue in report.issues if issue.severity == "error"]
    if errors:
        raise WorkspaceExportUnrepresentableError(errors)
    return WorkspaceCandidateExport(child, snapshot, digest, snapshot["workspace_version"], entity_refs, review_metadata)


__all__ = ["WorkspaceCandidateExport", "WorkspaceExportConflictError", "WorkspaceExportUnrepresentableError", "export_candidate_revision", "export_workspace_candidate", "read_candidate_workspace_snapshot"]
