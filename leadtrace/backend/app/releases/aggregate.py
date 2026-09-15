from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.activities.models import Activity
from app.approvals.models import ApprovalDecision
from app.assets.storage import LocalAssetStore
from app.compounds.models import Compound
from app.evidence.models import Evidence
from app.lineages.models import Lineage, LineageEdge
from app.molecule_proposals.models import MoleculeProposal
from app.papers.models import Paper
from app.releases.manifest import canonical_hash, get_release_artifact_manifest
from app.releases.models import Release, ReleaseItem
from app.releases.validation import ReleaseValidationResult, validate_release
from app.revisions.models import ObjectKind, ObjectRevision, StructureState
from app.reviews.attestations import (
    AttestationValidationError,
    validate_frozen_attestation,
)
from app.reviews.models import Changeset
from app.structures.models import Structure
from app.users.models import User, UserRole
from app.visual_objects.models import VisualObject, VisualRegion


OVERVIEW_METRIC_KEYS = (
    "corpus",
    "lineage",
    "relation",
    "structure",
    "pair",
    "human_review",
)


def overview_metrics_from_counts(
    counts: Mapping[str, object],
) -> dict[str, dict[str, int | str]]:
    """Convert fixed corpus counts to the Visitor overview contract."""

    def required_count(name: str) -> int:
        value = counts.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
        return value

    corpus_papers = required_count("corpus_papers")
    lineage_papers = required_count("lineage_papers")
    lineage_edges = required_count("lineage_edges")
    structure_confirmed = required_count("structure_confirmed")
    compound_entities = required_count("compound_entities")
    pair_ready_edges = required_count("pair_ready_edges")
    return {
        "corpus": {
            "numerator": corpus_papers,
            "denominator": corpus_papers,
            "unit": "papers",
        },
        "lineage": {
            "numerator": lineage_papers,
            "denominator": corpus_papers,
            "unit": "papers",
        },
        "relation": {
            "numerator": lineage_edges,
            "denominator": lineage_edges,
            "unit": "edges",
        },
        "structure": {
            "numerator": structure_confirmed,
            "denominator": compound_entities,
            "unit": "compounds",
        },
        "pair": {
            "numerator": pair_ready_edges,
            "denominator": lineage_edges,
            "unit": "edges",
        },
        "human_review": {
            "numerator": 0,
            "denominator": corpus_papers,
            "unit": "papers",
        },
    }


@dataclass(frozen=True, slots=True)
class ReleaseAggregate:
    counts: dict[str, int]
    integrity: dict[str, int]
    physical_counts: dict[str, int]

    def as_dict(self) -> dict[str, object]:
        return {
            "counts": self.counts,
            "integrity": self.integrity,
            "physical_counts": self.physical_counts,
        }


@dataclass(frozen=True, slots=True)
class _Entry:
    item: ReleaseItem
    revision: ObjectRevision | None
    record: object | None


@dataclass(frozen=True, slots=True)
class PaperVerificationEvidence:
    paper_revision_id: UUID
    attestation_id: UUID


ReleaseItemInput = ReleaseItem | tuple[UUID, UUID, UUID, ObjectKind, int]


_MODEL_BY_KIND = {
    ObjectKind.PAPER: Paper,
    ObjectKind.COMPOUND: Compound,
    ObjectKind.STRUCTURE: Structure,
    ObjectKind.EVIDENCE: Evidence,
    ObjectKind.ACTIVITY: Activity,
    ObjectKind.LINEAGE: Lineage,
    ObjectKind.LINEAGE_EDGE: LineageEdge,
    ObjectKind.VISUAL_REGION: VisualRegion,
    ObjectKind.VISUAL_OBJECT: VisualObject,
    ObjectKind.MOLECULE_PROPOSAL: MoleculeProposal,
}


def _release_item_values(
    item: ReleaseItemInput,
) -> tuple[UUID, UUID, UUID, ObjectKind]:
    if isinstance(item, ReleaseItem):
        return item.object_id, item.revision_id, item.paper_id, item.object_kind
    object_id, revision_id, paper_id, object_kind, _ = item
    return object_id, revision_id, paper_id, object_kind


def paper_verification_evidence(
    session: Session,
    item: ReleaseItemInput,
) -> PaperVerificationEvidence | None:
    """Resolve the evidence chain that authorizes one verified Paper revision."""

    object_id, revision_id, paper_id, object_kind = _release_item_values(item)
    if object_kind is not ObjectKind.PAPER or object_id != paper_id:
        return None
    revision = session.get(ObjectRevision, revision_id)
    if revision is None or revision.object_id != object_id:
        return None
    normalized = revision.snapshot.get("normalized_values")
    if not isinstance(normalized, Mapping) or normalized.get("review_status") != "reviewed":
        return None
    if revision.changeset_id is None:
        return None
    changeset = session.get(Changeset, revision.changeset_id)
    if changeset is None or changeset.paper_id != paper_id:
        return None
    try:
        attestation = validate_frozen_attestation(session, changeset=changeset)
    except AttestationValidationError:
        return None
    if attestation is None or attestation.paper_revision_id != revision.id:
        return None
    if changeset.submitted_content_hash is None:
        return None
    approval = session.scalar(
        select(ApprovalDecision)
        .where(
            ApprovalDecision.changeset_id == changeset.id,
            ApprovalDecision.decision == "approve",
            ApprovalDecision.snapshot_hash == changeset.submitted_content_hash,
        )
        .order_by(ApprovalDecision.created_at.desc(), ApprovalDecision.id)
        .limit(1)
    )
    if approval is None or approval.snapshot != changeset.submitted_snapshot:
        return None
    admin = session.get(User, approval.actor_id)
    if (
        admin is None
        or not admin.is_enabled
        or admin.role is not UserRole.ADMIN
        or admin.id == changeset.owner_id
    ):
        return None
    return PaperVerificationEvidence(
        paper_revision_id=revision.id,
        attestation_id=attestation.id,
    )


def human_review_metric(
    session: Session,
    release_items: Iterable[ReleaseItemInput],
) -> dict[str, int | str]:
    """Compute Paper-level human verification from immutable review evidence."""

    papers = [
        item
        for item in release_items
        if _release_item_values(item)[3] is ObjectKind.PAPER
    ]
    return {
        "numerator": sum(
            paper_verification_evidence(session, item) is not None for item in papers
        ),
        "denominator": len(papers),
        "unit": "papers",
    }


def paper_human_review_summary(
    session: Session,
    *,
    release_id: UUID,
    item: ReleaseItem,
) -> dict[str, object]:
    evidence = paper_verification_evidence(session, item)
    return {
        "reviewed": int(evidence is not None),
        "total": 1,
        "status": "human_verified" if evidence is not None else "unverified",
        "verified": evidence is not None,
        "release_id": str(release_id),
        "paper_revision_id": str(item.revision_id),
        "attestation_id": (
            str(evidence.attestation_id) if evidence is not None else None
        ),
    }


def _snapshot_value(revision: ObjectRevision | None, *names: str) -> object | None:
    if revision is None:
        return None
    for name in names:
        if name in revision.snapshot:
            return revision.snapshot[name]
    normalized = revision.snapshot.get("normalized_values")
    if isinstance(normalized, Mapping):
        for name in names:
            if name in normalized:
                return normalized[name]
    return None


def _candidate_values(value: object | None) -> tuple[object, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(value)
    if isinstance(value, str) and "|" in value:
        return tuple(part.strip() for part in value.split("|") if part.strip())
    return (value,)


def _reference_ids(
    value: object | None,
    *,
    keys: Mapping[tuple[UUID, str], UUID],
    paper_id: UUID,
) -> tuple[UUID | None, ...]:
    found: list[UUID | None] = []
    for candidate in _candidate_values(value):
        try:
            identifier = UUID(str(candidate))
        except (TypeError, ValueError, AttributeError):
            identifier = keys.get((paper_id, str(candidate)))
        found.append(identifier)
    return tuple(found)


def _pair_ready(revision: ObjectRevision | None) -> bool:
    value = _snapshot_value(revision, "pair_ready", "pair_eligible")
    return value is True or (isinstance(value, str) and value.casefold() == "yes")


def _frozen_reference(
    artifact: Mapping[str, object],
    object_id: UUID,
    field: str,
) -> tuple[bool, UUID | None]:
    references = artifact.get("object_references")
    if not isinstance(references, Mapping):
        return False, None
    row = references.get(str(object_id))
    if not isinstance(row, Mapping) or field not in row:
        return False, None
    value = row.get(field)
    if value in (None, ""):
        return True, None
    try:
        return True, UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return True, None


def _physical_counts(session: Session, release_id: UUID) -> dict[str, int]:
    models = {
        "papers": Paper,
        "compounds": Compound,
        "structures": Structure,
        "lineages": Lineage,
        "lineage_edges": LineageEdge,
        "evidence_records": Evidence,
        "activity_records": Activity,
        "releases": Release,
    }
    counts = {
        name: int(session.scalar(select(func.count()).select_from(model)) or 0)
        for name, model in models.items()
    }
    counts["current_release_items"] = int(
        session.scalar(
            select(func.count())
            .select_from(ReleaseItem)
            .where(ReleaseItem.release_id == release_id)
        )
        or 0
    )
    return counts


def recompute_release_aggregate(
    session: Session,
    release: Release,
    *,
    asset_store: LocalAssetStore | None = None,
    validation: ReleaseValidationResult | None = None,
) -> ReleaseAggregate:
    items = list(
        session.scalars(
            select(ReleaseItem)
            .where(ReleaseItem.release_id == release.id)
            .order_by(ReleaseItem.manifest_order, ReleaseItem.id)
        )
    )
    entries: list[_Entry] = []
    for item in items:
        revision = session.get(ObjectRevision, item.revision_id)
        model = _MODEL_BY_KIND.get(item.object_kind)
        record = session.get(model, item.object_id) if model is not None else None
        entries.append(_Entry(item, revision, record))

    by_kind = {
        kind: [entry for entry in entries if entry.item.object_kind is kind]
        for kind in ObjectKind
    }
    papers = {
        entry.item.object_id: entry.record
        for entry in by_kind[ObjectKind.PAPER]
        if isinstance(entry.record, Paper)
    }
    compounds = {
        entry.item.object_id: entry.record
        for entry in by_kind[ObjectKind.COMPOUND]
        if isinstance(entry.record, Compound)
    }
    evidence = {
        entry.item.object_id: entry.record
        for entry in by_kind[ObjectKind.EVIDENCE]
        if isinstance(entry.record, Evidence)
    }
    lineages = {
        entry.item.object_id: entry.record
        for entry in by_kind[ObjectKind.LINEAGE]
        if isinstance(entry.record, Lineage)
    }
    edges = {
        entry.item.object_id: entry.record
        for entry in by_kind[ObjectKind.LINEAGE_EDGE]
        if isinstance(entry.record, LineageEdge)
    }
    compound_keys = {
        (record.paper_id, record.local_identity): object_id
        for object_id, record in compounds.items()
    }
    evidence_keys = {
        (record.paper_id, record.evidence_key): object_id
        for object_id, record in evidence.items()
    }
    lineage_keys = {
        (record.paper_id, record.lineage_key): object_id
        for object_id, record in lineages.items()
    }
    edge_keys = {
        (record.paper_id, record.edge_key): object_id
        for object_id, record in edges.items()
    }

    artifact_model = get_release_artifact_manifest(session, release.id)
    artifact: Mapping[str, object] = (
        artifact_model.snapshot if artifact_model is not None else {}
    )
    dangling_entities = 0
    dangling_evidence = 0
    for entry in entries:
        item = entry.item
        if (
            entry.revision is None
            or entry.revision.object_id != item.object_id
            or entry.record is None
        ):
            dangling_entities += 1
            continue
        actual_paper_id = (
            entry.record.id
            if isinstance(entry.record, Paper)
            else getattr(entry.record, "paper_id", None)
        )
        if actual_paper_id != item.paper_id or item.paper_id not in papers:
            dangling_entities += 1

    complete_compound_ids: set[UUID] = set()
    confirmed_compound_ids: set[UUID] = set()
    for entry in by_kind[ObjectKind.STRUCTURE]:
        structure = entry.record
        revision = entry.revision
        if not isinstance(structure, Structure) or revision is None:
            continue
        if structure.compound_id not in compounds or compounds[structure.compound_id].paper_id != structure.paper_id:
            dangling_entities += 1
        frozen, frozen_compound_id = _frozen_reference(
            artifact, entry.item.object_id, "compound_id"
        )
        if frozen and frozen_compound_id != structure.compound_id:
            dangling_entities += 1
        if revision.canonical_smiles:
            complete_compound_ids.add(structure.compound_id)
        if revision.structure_state is StructureState.STRUCTURE_CONFIRMED:
            confirmed_compound_ids.add(structure.compound_id)

    for entry in by_kind[ObjectKind.ACTIVITY]:
        activity = entry.record
        if not isinstance(activity, Activity):
            continue
        if activity.compound_id not in compounds or compounds[activity.compound_id].paper_id != activity.paper_id:
            dangling_entities += 1
        frozen, frozen_compound_id = _frozen_reference(
            artifact, entry.item.object_id, "compound_id"
        )
        if frozen and frozen_compound_id != activity.compound_id:
            dangling_entities += 1
        for evidence_id in _reference_ids(
            _snapshot_value(entry.revision, "evidence_ids"),
            keys=evidence_keys,
            paper_id=activity.paper_id,
        ):
            target = evidence.get(evidence_id)
            if target is None or target.paper_id != activity.paper_id:
                dangling_evidence += 1

    for entry in by_kind[ObjectKind.EVIDENCE]:
        record = entry.record
        if not isinstance(record, Evidence):
            continue
        for compound_id in _reference_ids(
            _snapshot_value(entry.revision, "compound_ids"),
            keys=compound_keys,
            paper_id=record.paper_id,
        ):
            target = compounds.get(compound_id)
            if target is None or target.paper_id != record.paper_id:
                dangling_entities += 1
        source_edge_ids = _reference_ids(
            _snapshot_value(entry.revision, "lineage_edge_id"),
            keys=edge_keys,
            paper_id=record.paper_id,
        )
        source_lineage_ids = _reference_ids(
            _snapshot_value(entry.revision, "lineage_id"),
            keys=lineage_keys,
            paper_id=record.paper_id,
        )
        if source_edge_ids and any(
            edge_id not in edges or edges[edge_id].paper_id != record.paper_id
            for edge_id in source_edge_ids
        ):
            dangling_evidence += 1
        if source_lineage_ids and any(
            lineage_id not in lineages
            or lineages[lineage_id].paper_id != record.paper_id
            for lineage_id in source_lineage_ids
        ):
            dangling_evidence += 1

    pair_ready_entries = [
        entry for entry in by_kind[ObjectKind.LINEAGE_EDGE] if _pair_ready(entry.revision)
    ]
    directed_edges: Counter[tuple[UUID, UUID | None, UUID]] = Counter()
    self_loops = 0
    unresolved_pair_ready = 0
    invalid_pair_endpoints = 0
    for entry in by_kind[ObjectKind.LINEAGE_EDGE]:
        edge = entry.record
        if not isinstance(edge, LineageEdge):
            continue
        directed_edges[(edge.lineage_id, edge.parent_compound_id, edge.derived_compound_id)] += 1
        if edge.parent_compound_id == edge.derived_compound_id:
            self_loops += 1
        lineage = lineages.get(edge.lineage_id)
        parent = compounds.get(edge.parent_compound_id) if edge.parent_compound_id else None
        derived = compounds.get(edge.derived_compound_id)
        if lineage is None or lineage.paper_id != edge.paper_id:
            dangling_entities += 1
        if edge.parent_compound_id is not None and (
            parent is None or parent.paper_id != edge.paper_id
        ):
            dangling_entities += 1
        if derived is None or derived.paper_id != edge.paper_id:
            dangling_entities += 1
        for evidence_id in _reference_ids(
            _snapshot_value(entry.revision, "evidence_ids"),
            keys=evidence_keys,
            paper_id=edge.paper_id,
        ):
            target = evidence.get(evidence_id)
            if target is None or target.paper_id != edge.paper_id:
                dangling_evidence += 1

        relationship_changed = False
        for field, live_value in (
            ("lineage_id", edge.lineage_id),
            ("parent_compound_id", edge.parent_compound_id),
            ("derived_compound_id", edge.derived_compound_id),
        ):
            frozen, frozen_value = _frozen_reference(artifact, entry.item.object_id, field)
            relationship_changed |= frozen and frozen_value != live_value
        if not _pair_ready(entry.revision):
            continue
        status = entry.revision.relation_status if entry.revision else None
        status = status or _snapshot_value(entry.revision, "relation_status")
        if edge.parent_compound_id is None or status in {None, "unresolved", "invalid"}:
            unresolved_pair_ready += 1
        if (
            relationship_changed
            or parent is None
            or derived is None
            or parent.paper_id != edge.paper_id
            or derived.paper_id != edge.paper_id
            or edge.parent_compound_id == edge.derived_compound_id
            or edge.parent_compound_id not in confirmed_compound_ids
            or edge.derived_compound_id not in confirmed_compound_ids
        ):
            invalid_pair_endpoints += 1

    active_validation = validation or validate_release(
        session, release.id, asset_store=asset_store
    )
    asset_issue_codes = {
        "artifact_hash_mismatch",
        "artifact_manifest_missing",
        "asset_manifest_mismatch",
        "invalid_asset",
        "missing_asset",
    }
    asset_defects = len(
        {
            (issue.code, issue.object_id)
            for issue in active_validation.issues
            if issue.code in asset_issue_codes
        }
    )
    if artifact_model is not None and artifact_model.content_hash != canonical_hash(artifact):
        asset_defects = max(asset_defects, 1)

    compound_count = len(by_kind[ObjectKind.COMPOUND])
    counts = {
        "corpus_papers": len(by_kind[ObjectKind.PAPER]),
        "lineage_papers": len(
            {entry.item.paper_id for entry in by_kind[ObjectKind.LINEAGE]}
        ),
        "lineages": len(by_kind[ObjectKind.LINEAGE]),
        "compound_entities": compound_count,
        "lineage_edges": len(by_kind[ObjectKind.LINEAGE_EDGE]),
        "activity_rows": len(by_kind[ObjectKind.ACTIVITY]),
        "complete_structures": len(complete_compound_ids & compounds.keys()),
        "structure_confirmed": sum(
            entry.revision is not None
            and entry.revision.structure_state is StructureState.STRUCTURE_CONFIRMED
            for entry in by_kind[ObjectKind.STRUCTURE]
        ),
        "missing_or_non_unique": compound_count
        - len(complete_compound_ids & compounds.keys()),
        "pair_ready_edges": len(pair_ready_entries),
        "papers_with_pair_ready": len(
            {entry.item.paper_id for entry in pair_ready_entries}
        ),
    }
    integrity = {
        "self_loops": self_loops,
        "duplicate_directed_edges": sum(
            count - 1 for count in directed_edges.values() if count > 1
        ),
        "unresolved_pair_ready_edges": unresolved_pair_ready,
        "dangling_entity_references": dangling_entities,
        "dangling_evidence_references": dangling_evidence,
        "invalid_pair_endpoints": invalid_pair_endpoints,
        "published_missing_or_corrupt_assets": asset_defects,
    }
    return ReleaseAggregate(
        counts,
        integrity,
        _physical_counts(session, release.id),
    )


__all__ = [
    "OVERVIEW_METRIC_KEYS",
    "ReleaseAggregate",
    "overview_metrics_from_counts",
    "recompute_release_aggregate",
]
