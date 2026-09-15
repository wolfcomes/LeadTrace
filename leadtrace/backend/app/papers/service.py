from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict
from math import ceil
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activities.models import Activity
from app.api.errors import APIError
from app.assets.models import Asset, AssetAccessLevel, AssetIntegrityState
from app.compounds.models import Compound
from app.evidence.models import Evidence
from app.lineages.models import Lineage, LineageEdge
from app.molecule_proposals.models import MoleculeProposal
from app.papers.repository import (
    PaperListFilters,
    PublishedPaperRow,
    get_published_paper,
    list_published_papers,
    release_items_for_paper,
)
from app.releases.models import Release
from app.releases.manifest import get_release_artifact_manifest
from app.releases.aggregate import paper_human_review_summary
from app.releases.service import release_verification_status
from app.revisions.models import (
    ActivityState,
    EvidenceState,
    ObjectKind,
    StructureState,
)
from app.structures.models import Structure
from app.visual_objects.models import VisualObject, VisualRegion


def _release_metadata(release: Release) -> dict[str, object]:
    return {
        "id": str(release.id),
        "key": release.release_key,
        "title": release.title,
        "published_at": release.published_at.isoformat(),
        "verification_status": release_verification_status(release),
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


def _safe_public_value(value: object) -> object:
    """Remove server-only path fields before a published projection is returned."""
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, nested in value.items():
            name = str(key)
            normalized = name.casefold()
            if (
                normalized in {"storage_key", "source_pdf", "crop_path", "source_crop_path"}
                or normalized.endswith("_path")
                or normalized.endswith("_filepath")
            ):
                continue
            result[name] = _safe_public_value(nested)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_safe_public_value(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    return value


def _visitor_asset(asset: Asset | None) -> dict[str, object] | None:
    """Return an asset only when the public content route can serve it."""
    if (
        asset is None
        or asset.integrity_state is not AssetIntegrityState.VERIFIED
        or asset.access_level is not AssetAccessLevel.VISITOR
    ):
        return None
    return {
        "id": str(asset.id),
        "url": f"/api/v1/assets/{asset.id}/content",
        "original_filename": asset.original_filename,
        "sha256": asset.sha256,
        "byte_size": asset.byte_size,
        "mime_type": asset.mime_type,
        "width": asset.width,
        "height": asset.height,
        "page_count": asset.page_count,
        "category": asset.category.value,
        "access_level": asset.access_level.value,
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


def _models_by_id(
    session: Session,
    model: type,
    ids: set[UUID],
    *,
    paper_id: UUID,
) -> dict[UUID, object]:
    if not ids:
        return {}
    return {
        item.id: item
        for item in session.scalars(
            select(model).where(model.id.in_(ids), model.paper_id == paper_id)
        )
    }


def paper_detail_payload(
    session: Session,
    release: Release,
    paper_id: UUID,
    *,
    request_id: str,
    include_review_entry: bool = False,
) -> dict[str, object]:
    paper = get_published_paper(session, release, paper_id)
    if paper is None:
        raise APIError(404, "RESOURCE_NOT_FOUND", "Resource not found")
    entries = release_items_for_paper(session, release.id, paper_id)
    ids_by_kind: dict[ObjectKind, set[UUID]] = {}
    for item, _ in entries:
        ids_by_kind.setdefault(item.object_kind, set()).add(item.object_id)
    compounds = {
        compound.id: compound
        for compound in session.scalars(
            select(Compound).where(
                Compound.id.in_(ids_by_kind.get(ObjectKind.COMPOUND, set())),
                Compound.paper_id == paper_id,
            )
        )
    }
    lineages = _models_by_id(
        session,
        Lineage,
        ids_by_kind.get(ObjectKind.LINEAGE, set()),
        paper_id=paper_id,
    )
    structures = _models_by_id(
        session,
        Structure,
        ids_by_kind.get(ObjectKind.STRUCTURE, set()),
        paper_id=paper_id,
    )
    visual_objects = _models_by_id(
        session,
        VisualObject,
        ids_by_kind.get(ObjectKind.VISUAL_OBJECT, set()),
        paper_id=paper_id,
    )
    regions = _models_by_id(
        session,
        VisualRegion,
        ids_by_kind.get(ObjectKind.VISUAL_REGION, set()),
        paper_id=paper_id,
    )
    proposals = _models_by_id(
        session,
        MoleculeProposal,
        ids_by_kind.get(ObjectKind.MOLECULE_PROPOSAL, set()),
        paper_id=paper_id,
    )
    evidence = _models_by_id(
        session,
        Evidence,
        ids_by_kind.get(ObjectKind.EVIDENCE, set()),
        paper_id=paper_id,
    )
    activities = _models_by_id(
        session,
        Activity,
        ids_by_kind.get(ObjectKind.ACTIVITY, set()),
        paper_id=paper_id,
    )
    edges = _models_by_id(
        session,
        LineageEdge,
        ids_by_kind.get(ObjectKind.LINEAGE_EDGE, set()),
        paper_id=paper_id,
    )

    compound_payload: list[dict[str, object]] = []
    lineage_payload: list[dict[str, object]] = []
    structure_payload: list[dict[str, object]] = []
    evidence_payload: list[dict[str, object]] = []
    activity_payload: list[dict[str, object]] = []
    edge_payload: list[dict[str, object]] = []
    region_payload: list[dict[str, object]] = []
    visual_object_payload: list[dict[str, object]] = []
    proposal_payload: list[dict[str, object]] = []
    source_locator_payload: list[dict[str, object]] = []
    confirmed_structure_ids = {
        structure.compound_id
        for item, revision in entries
        if item.object_kind is ObjectKind.STRUCTURE
        and (structure := structures.get(item.object_id)) is not None
        and revision.structure_state is StructureState.STRUCTURE_CONFIRMED
        and bool(revision.canonical_smiles)
    }
    artifact = get_release_artifact_manifest(session, release.id)
    frozen_bindings = artifact.snapshot.get("bindings") if artifact is not None else {}
    frozen_bindings = frozen_bindings if isinstance(frozen_bindings, Mapping) else {}
    region_by_visual: dict[UUID, UUID] = {}
    for binding in frozen_bindings.get("visual_object_regions", []):
        if not isinstance(binding, Mapping):
            continue
        try:
            region_by_visual[UUID(str(binding["visual_object_id"]))] = UUID(str(binding["region_id"]))
        except (KeyError, TypeError, ValueError):
            continue
    for item, revision in entries:
        normalized = revision.snapshot.get("normalized_values", {})
        if item.object_kind is ObjectKind.VISUAL_REGION:
            region = regions.get(item.object_id)
            if region is None:
                continue
            bounds = {
                "x0": revision.region_x0,
                "y0": revision.region_y0,
                "x1": revision.region_x1,
                "y1": revision.region_y1,
            }
            region_asset = session.get(Asset, region.asset_id) if region.asset_id else None
            region_payload.append({
                "id": str(region.id),
                "region_key": region.region_key,
                "revision_id": str(revision.id),
                "page_number": region.page_number,
                "bounds": bounds,
                "rotation": revision.region_rotation or 0,
                "asset": _visitor_asset(region_asset),
            })
        elif item.object_kind is ObjectKind.VISUAL_OBJECT:
            visual = visual_objects.get(item.object_id)
            if visual is None:
                continue
            visual_object_payload.append({
                "id": str(visual.id),
                "object_key": visual.object_key,
                "object_type": str(visual.object_type),
                "revision_id": str(revision.id),
                "snapshot": _safe_public_value(revision.snapshot),
                "region_id": str(region_by_visual[visual.id]) if visual.id in region_by_visual else None,
            })
        elif item.object_kind is ObjectKind.MOLECULE_PROPOSAL:
            proposal = proposals.get(item.object_id)
            if proposal is None:
                continue
            raw_values = revision.snapshot.get("raw_values", {})
            normalized_values = revision.snapshot.get("normalized_values", {})
            review = revision.snapshot.get("review", {})
            crop = session.get(Asset, proposal.crop_asset_id) if proposal.crop_asset_id else None
            proposal_payload.append({
                "id": str(proposal.id),
                "visual_object_id": str(proposal.visual_object_id),
                "proposal_key": proposal.proposal_key,
                "model_run_key": proposal.model_run_key,
                "revision_id": str(revision.id),
                "disposition": str(revision.proposal_disposition or "pending"),
                "machine": {
                    "raw_values": _safe_public_value(raw_values if isinstance(raw_values, Mapping) else {}),
                    "normalized_values": _safe_public_value(normalized_values if isinstance(normalized_values, Mapping) else {}),
                },
                "review": _safe_public_value(review if isinstance(review, Mapping) else {}),
                "crop_asset": _visitor_asset(crop),
                "source_region_id": str(proposal.source_region_id) if proposal.source_region_id else None,
            })
            source_region = regions.get(proposal.source_region_id) if proposal.source_region_id else None
            if source_region is not None:
                source_revision = next((candidate_revision for candidate_item, candidate_revision in entries if candidate_item.object_id == source_region.id and candidate_item.object_kind is ObjectKind.VISUAL_REGION), None)
                if source_revision is not None:
                    source_asset = session.get(Asset, source_region.asset_id) if source_region.asset_id else None
                    source_locator_payload.append({
                        "proposal_id": str(proposal.id),
                        "visual_object_id": str(proposal.visual_object_id),
                        "region": {
                            "id": str(source_region.id),
                            "page_number": source_region.page_number,
                            "bounds": {
                                "x0": source_revision.region_x0,
                                "y0": source_revision.region_y0,
                                "x1": source_revision.region_x1,
                                "y1": source_revision.region_y1,
                            },
                            "rotation": source_revision.region_rotation or 0,
                        },
                        "crop_asset": _visitor_asset(crop),
                        "source_asset": _visitor_asset(source_asset),
                    })
        elif item.object_kind is ObjectKind.COMPOUND:
            compound = compounds.get(item.object_id)
            if compound is None:
                continue
            compound_payload.append(
                {
                    "id": str(compound.id),
                    "revision_id": str(revision.id),
                    "local_identity": compound.local_identity,
                    "label": compound.display_label,
                }
            )
        elif item.object_kind is ObjectKind.LINEAGE:
            lineage = lineages.get(item.object_id)
            if lineage is None:
                continue
            lineage_payload.append(
                {
                    "id": str(lineage.id),
                    "revision_id": str(revision.id),
                    "lineage_key": lineage.lineage_key,
                }
            )
        elif item.object_kind is ObjectKind.STRUCTURE:
            structure = structures.get(item.object_id)
            if structure is None:
                continue
            structure_row: dict[str, object] = {
                "id": str(structure.id),
                "revision_id": str(revision.id),
                "compound_id": str(structure.compound_id),
                "state": revision.structure_state.value
                if revision.structure_state
                else None,
                "canonical_smiles": revision.canonical_smiles,
            }
            drawing_asset_id = (
                revision.snapshot.get("drawing_asset_id")
                if isinstance(revision.snapshot, Mapping)
                else None
            )
            if drawing_asset_id:
                try:
                    drawing_asset = _visitor_asset(
                        session.get(Asset, UUID(str(drawing_asset_id)))
                    )
                except (TypeError, ValueError):
                    drawing_asset = None
                if drawing_asset is not None:
                    structure_row["drawing_asset"] = drawing_asset
            structure_payload.append(structure_row)
        elif item.object_kind is ObjectKind.EVIDENCE:
            evidence_record = evidence.get(item.object_id)
            if evidence_record is None or revision.evidence_state is not EvidenceState.CONFIRMED:
                continue
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
            activity = activities.get(item.object_id)
            if activity is None or revision.activity_state is not ActivityState.CONFIRMED:
                continue
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
            edge = edges.get(item.object_id)
            if edge is None:
                continue
            parent_id = edge.parent_compound_id
            derived_id = edge.derived_compound_id
            # Pair readiness is derived from release-pinned, confirmed data;
            # a snapshot hint alone can never promote a pair.
            pair_blockers: list[str] = []
            if not isinstance(normalized, dict) or normalized.get("pair_eligible") != "yes":
                pair_blockers.append("not_marked_eligible")
            if revision.relation_status in {None, "unresolved", "invalid"}:
                pair_blockers.append("relation_unresolved")
            if parent_id is None:
                pair_blockers.append("parent_missing")
            elif parent_id == derived_id:
                pair_blockers.append("self_loop")
            elif parent_id not in compounds:
                pair_blockers.append("parent_not_in_paper")
            if derived_id not in compounds:
                pair_blockers.append("derived_not_in_paper")
            if parent_id is not None and parent_id not in confirmed_structure_ids:
                pair_blockers.append("parent_structure_unconfirmed")
            if derived_id not in confirmed_structure_ids:
                pair_blockers.append("derived_structure_unconfirmed")
            pair_eligible = not pair_blockers
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
                    "pair_blockers": pair_blockers,
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
    paper_release_item = next(
        item for item, _ in entries if item.object_kind is ObjectKind.PAPER
    )
    paper_review = paper_human_review_summary(
        session,
        release_id=release.id,
        item=paper_release_item,
    )
    release_status = release_verification_status(release)
    payload = {
        "request_id": request_id,
        "release": _release_metadata(release),
        "paper": _paper_summary(paper),
        "compounds": compound_payload,
        "lineages": lineage_payload,
        "lineage_edges": edge_payload,
        "structures": structure_payload,
        "regions": region_payload,
        "visual_objects": visual_object_payload,
        "molecule_proposals": proposal_payload,
        "source_locators": source_locator_payload,
        "evidence": evidence_payload,
        "activities": activity_payload,
        "quality_summary": {
            "relations": {"resolved": resolved_relations, "total": len(edge_payload)},
            "structures": {
                "confirmed": confirmed_structures,
                "total": len(structure_payload),
            },
            "pair_ready": {"eligible": pair_ready, "total": len(edge_payload)},
            "human_review": paper_review,
        },
        "verification": {
            "ai_baseline": "published",
            "human_verified": paper_review["verified"] is True,
            "release_status": release_status,
        },
    }
    if include_review_entry:
        payload["review_entry"] = {
            "href": f"/review/tasks?paper_id={paper_id}",
            "label": "进入 Reviewer 核查任务",
        }
    return payload
