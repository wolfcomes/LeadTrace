from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activities.models import Activity
from app.catalog.models import PaperSource
from app.compounds.models import Compound
from app.evidence.models import EdgeEvidenceLink, Evidence
from app.lineages.models import Lineage, LineageEdge, LineageMember
from app.papers.models import Paper
from app.structure_images.models import StructureSourceImage
from app.structures.models import Structure
from app.workspaces.models import PaperSectionReview, PaperWorkspace


def _value(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_value(item) for item in value]
    return value


def _row(row: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: _value(getattr(row, field)) for field in fields}


def build_paper_snapshot(session: Session, workspace_id: UUID) -> dict[str, Any]:
    workspace = session.get(PaperWorkspace, workspace_id)
    if workspace is None:
        raise ValueError("Workspace not found")
    paper = session.get(Paper, workspace.paper_id)
    if paper is None:
        raise ValueError("Paper not found")
    source = session.scalar(
        select(PaperSource).where(PaperSource.id == paper.source_id)
    )
    if source is None:
        raise ValueError("Paper Source not found")

    compounds = list(
        session.scalars(
            select(Compound)
            .where(Compound.workspace_id == workspace_id)
            .order_by(Compound.id)
        )
    )
    structures = list(
        session.scalars(
            select(Structure)
            .where(Structure.workspace_id == workspace_id)
            .order_by(Structure.compound_id, Structure.id)
        )
    )
    source_images = list(
        session.scalars(
            select(StructureSourceImage)
            .where(StructureSourceImage.workspace_id == workspace_id)
            .order_by(StructureSourceImage.compound_id, StructureSourceImage.id)
        )
    )
    lineages = list(
        session.scalars(
            select(Lineage)
            .where(Lineage.workspace_id == workspace_id)
            .order_by(Lineage.sort_order, Lineage.id)
        )
    )
    members = list(
        session.scalars(
            select(LineageMember)
            .where(LineageMember.workspace_id == workspace_id)
            .order_by(LineageMember.lineage_id, LineageMember.sort_order, LineageMember.id)
        )
    )
    edges = list(
        session.scalars(
            select(LineageEdge)
            .where(LineageEdge.workspace_id == workspace_id)
            .order_by(LineageEdge.lineage_id, LineageEdge.sort_order, LineageEdge.id)
        )
    )
    evidence = list(
        session.scalars(
            select(Evidence)
            .where(Evidence.workspace_id == workspace_id)
            .order_by(Evidence.page_number, Evidence.id)
        )
    )
    links = list(
        session.scalars(
            select(EdgeEvidenceLink)
            .where(EdgeEvidenceLink.workspace_id == workspace_id)
            .order_by(EdgeEvidenceLink.edge_id, EdgeEvidenceLink.evidence_id, EdgeEvidenceLink.id)
        )
    )
    activities = list(
        session.scalars(
            select(Activity)
            .where(Activity.workspace_id == workspace_id)
            .order_by(Activity.compound_id, Activity.sort_order, Activity.id)
        )
    )
    sections = list(
        session.scalars(
            select(PaperSectionReview)
            .where(PaperSectionReview.workspace_id == workspace_id)
            .order_by(PaperSectionReview.section_key)
        )
    )

    return {
        "schema_version": 1,
        "paper": _row(
            paper,
            (
                "id",
                "paper_key",
                "title",
                "journal",
                "publication_year",
                "volume",
                "issue",
                "doi",
                "catalog_state",
            ),
        ),
        "source": {
            "asset_id": str(source.asset_id),
            "source_root_key": source.source_root_key,
            "source_key": source.source_key,
            "sha256": source.sha256,
            "page_count": source.page_count,
        },
        "workspace_version": workspace.version,
        "sections": [
            _row(section, ("section_key", "state", "note")) for section in sections
        ],
        "compounds": [
            _row(
                compound,
                (
                    "id",
                    "paper_id",
                    "workspace_id",
                    "compound_label",
                    "display_name",
                    "description",
                    "sort_order",
                    "created_by_kind",
                ),
            )
            for compound in compounds
        ],
        "structures": [
            _row(
                structure,
                (
                    "id",
                    "paper_id",
                    "workspace_id",
                    "compound_id",
                    "smiles",
                    "canonical_smiles",
                    "molfile",
                    "inchi",
                    "inchikey",
                    "depiction_asset_id",
                    "status",
                    "input_method",
                ),
            )
            for structure in structures
        ],
        "structure_source_images": [
            _row(
                image,
                (
                    "id",
                    "paper_id",
                    "workspace_id",
                    "compound_id",
                    "source_sha256",
                    "page_number",
                    "x0",
                    "y0",
                    "x1",
                    "y1",
                    "source_context",
                    "label",
                    "reviewer_note",
                    "crop_status",
                    "crop_asset_id",
                ),
            )
            for image in source_images
        ],
        "lineages": [
            _row(
                lineage,
                (
                    "id",
                    "paper_id",
                    "workspace_id",
                    "lineage_label",
                    "description",
                    "sort_order",
                ),
            )
            for lineage in lineages
        ],
        "lineage_members": [
            _row(
                member,
                (
                    "id",
                    "paper_id",
                    "workspace_id",
                    "lineage_id",
                    "compound_id",
                    "role",
                    "sort_order",
                ),
            )
            for member in members
        ],
        "lineage_edges": [
            _row(
                edge,
                (
                    "id",
                    "paper_id",
                    "workspace_id",
                    "lineage_id",
                    "parent_compound_id",
                    "child_compound_id",
                    "relation_type",
                    "modification_summary",
                    "review_status",
                    "sort_order",
                ),
            )
            for edge in edges
        ],
        "evidence": [
            _row(
                item,
                (
                    "id",
                    "paper_id",
                    "workspace_id",
                    "kind",
                    "source_sha256",
                    "page_number",
                    "x0",
                    "y0",
                    "x1",
                    "y1",
                    "quoted_text",
                    "caption",
                    "crop_asset_id",
                    "reviewer_note",
                ),
            )
            for item in evidence
        ],
        "edge_evidence_links": [
            _row(link, ("id", "paper_id", "workspace_id", "edge_id", "evidence_id", "role"))
            for link in links
        ],
        "activities": [
            _row(
                activity,
                (
                    "id",
                    "paper_id",
                    "workspace_id",
                    "compound_id",
                    "evidence_id",
                    "assay_name",
                    "metric",
                    "operator",
                    "value",
                    "unit",
                    "context",
                    "sort_order",
                ),
            )
            for activity in activities
        ],
    }


def canonical_json(value: Any) -> str:
    return json.dumps(
        _value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_snapshot_hash(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(snapshot).encode("utf-8")).hexdigest()


__all__ = [
    "build_paper_snapshot",
    "canonical_json",
    "canonical_snapshot_hash",
]
