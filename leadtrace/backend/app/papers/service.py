from __future__ import annotations

from dataclasses import asdict
from math import ceil
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activities.models import Activity
from app.api.errors import APIError
from app.evidence.models import Evidence
from app.lineages.models import Lineage, LineageEdge
from app.papers.repository import (
    PaperListFilters,
    PublishedPaperRow,
    compounds_by_ids,
    get_published_paper,
    list_published_papers,
    release_items_for_paper,
)
from app.releases.models import Release
from app.revisions.models import ObjectKind, StructureState
from app.structures.models import Structure


def _release_metadata(release: Release) -> dict[str, object]:
    return {
        "id": str(release.id),
        "key": release.release_key,
        "title": release.title,
        "published_at": release.published_at.isoformat(),
    }


def _paper_summary(row: PublishedPaperRow) -> dict[str, object]:
    return {
        "id": str(row.id),
        "revision_id": str(row.revision_id),
        "paper_key": row.paper_key,
        "doi": row.doi,
        "title": row.title,
        "year": row.year,
        "target": row.target,
        "review_status": row.review_status,
    }


def paper_list_payload(
    session: Session,
    release: Release,
    filters: PaperListFilters,
    *,
    page: int,
    page_size: int,
    request_id: str,
) -> dict[str, object]:
    rows, total = list_published_papers(
        session,
        release,
        filters,
        page=page,
        page_size=page_size,
    )
    return {
        "request_id": request_id,
        "release": _release_metadata(release),
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_items": total,
            "total_pages": ceil(total / page_size) if total else 0,
        },
        "filters": asdict(filters),
        "items": [_paper_summary(row) for row in rows],
    }


def _models_by_id(session: Session, model: type, ids: set[UUID]) -> dict[UUID, object]:
    if not ids:
        return {}
    return {item.id: item for item in session.scalars(select(model).where(model.id.in_(ids)))}


def paper_detail_payload(
    session: Session,
    release: Release,
    paper_id: UUID,
    *,
    request_id: str,
) -> dict[str, object]:
    paper = get_published_paper(session, release, paper_id)
    if paper is None:
        raise APIError(404, "RESOURCE_NOT_FOUND", "Resource not found")
    entries = release_items_for_paper(session, release.id, paper_id)
    ids_by_kind: dict[ObjectKind, set[UUID]] = {}
    for item, _ in entries:
        ids_by_kind.setdefault(item.object_kind, set()).add(item.object_id)
    compounds = compounds_by_ids(session, ids_by_kind.get(ObjectKind.COMPOUND, set()))
    lineages = _models_by_id(
        session,
        Lineage,
        ids_by_kind.get(ObjectKind.LINEAGE, set()),
    )
    structures = _models_by_id(
        session,
        Structure,
        ids_by_kind.get(ObjectKind.STRUCTURE, set()),
    )
    evidence = _models_by_id(
        session,
        Evidence,
        ids_by_kind.get(ObjectKind.EVIDENCE, set()),
    )
    activities = _models_by_id(
        session,
        Activity,
        ids_by_kind.get(ObjectKind.ACTIVITY, set()),
    )
    edges = _models_by_id(
        session,
        LineageEdge,
        ids_by_kind.get(ObjectKind.LINEAGE_EDGE, set()),
    )

    compound_payload: list[dict[str, object]] = []
    lineage_payload: list[dict[str, object]] = []
    structure_payload: list[dict[str, object]] = []
    evidence_payload: list[dict[str, object]] = []
    activity_payload: list[dict[str, object]] = []
    edge_payload: list[dict[str, object]] = []
    reviewed = 0
    for item, revision in entries:
        normalized = revision.snapshot.get("normalized_values", {})
        if isinstance(normalized, dict) and normalized.get("review_status") in {
            "reviewed",
            "approved",
            "confirmed",
        }:
            reviewed += 1
        if item.object_kind is ObjectKind.COMPOUND:
            compound = compounds[item.object_id]
            compound_payload.append(
                {
                    "id": str(compound.id),
                    "revision_id": str(revision.id),
                    "local_identity": compound.local_identity,
                    "label": compound.display_label,
                }
            )
        elif item.object_kind is ObjectKind.LINEAGE:
            lineage = lineages[item.object_id]
            assert isinstance(lineage, Lineage)
            lineage_payload.append(
                {
                    "id": str(lineage.id),
                    "revision_id": str(revision.id),
                    "lineage_key": lineage.lineage_key,
                }
            )
        elif item.object_kind is ObjectKind.STRUCTURE:
            structure = structures[item.object_id]
            assert isinstance(structure, Structure)
            structure_payload.append(
                {
                    "id": str(structure.id),
                    "revision_id": str(revision.id),
                    "compound_id": str(structure.compound_id),
                    "state": revision.structure_state.value
                    if revision.structure_state
                    else None,
                    "canonical_smiles": revision.canonical_smiles,
                }
            )
        elif item.object_kind is ObjectKind.EVIDENCE:
            evidence_record = evidence[item.object_id]
            assert isinstance(evidence_record, Evidence)
            evidence_payload.append(
                {
                    "id": str(evidence_record.id),
                    "revision_id": str(revision.id),
                    "state": revision.evidence_state.value
                    if revision.evidence_state
                    else None,
                    "text": revision.evidence_text,
                }
            )
        elif item.object_kind is ObjectKind.ACTIVITY:
            activity = activities[item.object_id]
            assert isinstance(activity, Activity)
            activity_payload.append(
                {
                    "id": str(activity.id),
                    "revision_id": str(revision.id),
                    "compound_id": str(activity.compound_id),
                    "state": revision.activity_state.value
                    if revision.activity_state
                    else None,
                    "metric": revision.activity_metric,
                    "value": revision.activity_value,
                    "unit": revision.activity_unit,
                    "qualifier": normalized.get("qualifier")
                    if isinstance(normalized, dict)
                    else None,
                }
            )
        elif item.object_kind is ObjectKind.LINEAGE_EDGE:
            edge = edges[item.object_id]
            assert isinstance(edge, LineageEdge)
            pair_eligible = (
                isinstance(normalized, dict)
                and normalized.get("pair_eligible") == "yes"
                and edge.parent_compound_id is not None
                and edge.parent_compound_id != edge.derived_compound_id
            )
            edge_payload.append(
                {
                    "id": str(edge.id),
                    "revision_id": str(revision.id),
                    "lineage_id": str(edge.lineage_id),
                    "parent_compound_id": str(edge.parent_compound_id)
                    if edge.parent_compound_id
                    else None,
                    "derived_compound_id": str(edge.derived_compound_id),
                    "relation_type": revision.relation_type,
                    "relation_status": revision.relation_status,
                    "pair_ready": pair_eligible,
                }
            )

    resolved_relations = sum(
        edge["relation_status"] not in {None, "unresolved", "invalid"}
        and edge["parent_compound_id"] is not None
        for edge in edge_payload
    )
    confirmed_structures = sum(
        structure["state"] == StructureState.STRUCTURE_CONFIRMED.value
        for structure in structure_payload
    )
    pair_ready = sum(bool(edge["pair_ready"]) for edge in edge_payload)
    return {
        "request_id": request_id,
        "release": _release_metadata(release),
        "paper": _paper_summary(paper),
        "compounds": compound_payload,
        "lineages": lineage_payload,
        "lineage_edges": edge_payload,
        "structures": structure_payload,
        "evidence": evidence_payload,
        "activities": activity_payload,
        "quality_summary": {
            "relations": {"resolved": resolved_relations, "total": len(edge_payload)},
            "structures": {
                "confirmed": confirmed_structures,
                "total": len(structure_payload),
            },
            "pair_ready": {"eligible": pair_ready, "total": len(edge_payload)},
            "human_review": {"reviewed": reviewed, "total": len(entries)},
        },
    }
