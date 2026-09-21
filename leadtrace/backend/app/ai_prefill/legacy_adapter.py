from __future__ import annotations

import csv
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath

from app.ai_prefill.contracts import AiPrefillPayload
from app.ai_prefill.extractor import ProtectedPdfReference


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _value(row: dict[str, str], key: str) -> str | None:
    value = row.get(key, "").strip()
    return None if not value or value == "--" else value


def _page(row: dict[str, str], page_count: int) -> int | None:
    raw = _value(row, "page")
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if 0 < value <= page_count else None


def _decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value.replace(",", ""))
    except InvalidOperation:
        return None


def _operator(row: dict[str, str]) -> str | None:
    raw = (_value(row, "qualifier") or _value(row, "comparator") or "=").strip()
    return raw if raw in {"=", "<", "<=", ">", ">=", "~"} else None


class LegacyPipelineAdapter:
    engine = "legacy_pipeline"
    engine_version = "pilot-v2"

    def __init__(self, legacy_root: Path) -> None:
        self.legacy_root = legacy_root
        self.manifest_root = legacy_root / "01_manifest"
        self.output_root = legacy_root / "09_paper_review" / "auto_fill"

    def _legacy_paper_id(self, source_key: str) -> str:
        normalized = PurePosixPath("source_pdfs", source_key).as_posix()
        matches = [
            row["paper_id"]
            for row in _rows(self.manifest_root / "all_volume67_papers.csv")
            if row.get("source_pdf", "").strip() == normalized
        ]
        if len(matches) != 1:
            raise ValueError("Legacy artifacts do not identify this Source PDF")
        return matches[0]

    def extract(self, source: ProtectedPdfReference) -> AiPrefillPayload:
        paper_id = self._legacy_paper_id(source.source_key)
        entity_rows = {
            row["compound_entity_id"]: row
            for row in _rows(self.output_root / "compound_entities.csv")
            if row.get("paper_id") == paper_id
        }
        confirmed = {
            row["compound_entity_id"]: row
            for row in _rows(
                self.output_root / "confirmed_compound_structures.csv"
            )
            if row.get("paper_id") == paper_id
            and _value(row, "canonical_isomeric_smiles") is not None
            and row.get("confirmation_status") == "structure_confirmed"
        }

        edge_rows = [
            row
            for row in _rows(self.output_root / "compound_lineage_edges.csv")
            if row.get("paper_id") == paper_id
            # pair_eligible is an old materialized structure-readiness flag.
            # Recheck endpoints against confirmed structures instead of requiring
            # that stale flag or an accompanying text quotation.
            and row.get("relation_status") in {
                "text_explicit", "figure_explicit", "human_confirmed", "ai_inferred"
            }
            and row.get("review_status") not in {"rejected", "invalid"}
            and _value(row, "relation_type") is not None
            and _value(row, "parent_entity_id") != _value(row, "derived_entity_id")
            and _value(row, "parent_entity_id") in confirmed
            and _value(row, "derived_entity_id") in confirmed
        ]
        evidence_rows = {
            row["lineage_evidence_id"]: row
            for row in _rows(self.output_root / "compound_lineage_evidence.csv")
            if row.get("paper_id") == paper_id
            and _page(row, source.page_count) is not None
            and _value(row, "evidence_text") is not None
        }
        valid_edges = edge_rows
        edges_without_evidence = {
            row["lineage_edge_id"]
            for row in valid_edges
            if not any(
                ref in evidence_rows
                for ref in (row.get("evidence_ids") or "").split("|")
            )
        }

        activity_rows: list[tuple[dict[str, str], Decimal, str, int]] = []
        for row in _rows(self.output_root / "compound_activities.csv"):
            if row.get("paper_id") != paper_id:
                continue
            compound_ref = _value(row, "compound_entity_id")
            value = _decimal(_value(row, "value"))
            operator = _operator(row)
            page = _page(row, source.page_count)
            if (
                compound_ref in confirmed
                and value is not None
                and operator is not None
                and page is not None
                and _value(row, "assay") is not None
                and _value(row, "metric") is not None
                and _value(row, "evidence_text") is not None
            ):
                activity_rows.append((row, value, operator, page))

        selected_refs: set[str] = set()
        for row in valid_edges:
            selected_refs.add(row["parent_entity_id"])
            selected_refs.add(row["derived_entity_id"])
        selected_refs.update(row[0]["compound_entity_id"] for row in activity_rows)
        compounds = []
        for ref in entity_rows:
            if ref not in selected_refs or ref not in confirmed:
                continue
            entity = entity_rows[ref]
            structure = confirmed[ref]
            compounds.append(
                {
                    "ref": ref,
                    "compound_label": (
                        _value(entity, "display_label")
                        or _value(entity, "normalized_label")
                        or ref
                    ),
                    "display_name": _value(entity, "preferred_name"),
                    "description": None,
                    "structure": {
                        "smiles": structure["canonical_isomeric_smiles"],
                        "molfile": None,
                    },
                }
            )

        grouped_edges: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in valid_edges:
            grouped_edges[row["lineage_id"]].append(row)
        lineages = []
        accepted_edge_refs: set[str] = set()
        for lineage_ref, rows in grouped_edges.items():
            member_refs: list[str] = []
            incoming: set[str] = set()
            outgoing: set[str] = set()
            for row in rows:
                parent = row["parent_entity_id"]
                child = row["derived_entity_id"]
                if parent not in member_refs:
                    member_refs.append(parent)
                if child not in member_refs:
                    member_refs.append(child)
                outgoing.add(parent)
                incoming.add(child)
                accepted_edge_refs.add(row["lineage_edge_id"])
            members = []
            for ref in member_refs:
                role = (
                    "root"
                    if ref not in incoming
                    else "terminal"
                    if ref not in outgoing
                    else "intermediate"
                )
                members.append({"compound_ref": ref, "role": role})
            lineages.append(
                {
                    "ref": lineage_ref,
                    "lineage_label": lineage_ref,
                    "description": None,
                    "members": members,
                    "edges": [
                        {
                            "ref": row["lineage_edge_id"],
                            "parent_compound_ref": row["parent_entity_id"],
                            "child_compound_ref": row["derived_entity_id"],
                            "relation_type": row["relation_type"],
                            "modification_summary": "; ".join(
                                value
                                for value in (
                                    (
                                        "AI-proposed relationship; no linked Evidence; "
                                        f"legacy status: {row['relation_status']}; pending review"
                                        if row["lineage_edge_id"] in edges_without_evidence
                                        else None
                                    ),
                                    _value(row, "modification_site"),
                                    (
                                        f"{_value(row, 'from_group')} -> "
                                        f"{_value(row, 'to_group')}"
                                        if _value(row, "from_group")
                                        and _value(row, "to_group")
                                        else None
                                    ),
                                )
                                if value is not None
                            )
                            or None,
                        }
                        for row in rows
                    ],
                }
            )

        evidence = []
        edge_links = []
        included_evidence: set[str] = set()
        for row in valid_edges:
            for ref in (row.get("evidence_ids") or "").split("|"):
                evidence_row = evidence_rows.get(ref)
                if evidence_row is None:
                    continue
                if ref not in included_evidence:
                    included_evidence.add(ref)
                    evidence.append(
                        {
                            "ref": ref,
                            "kind": (
                                evidence_row.get("evidence_type")
                                if evidence_row.get("evidence_type")
                                in {"text", "table", "scheme", "image"}
                                else "text"
                            ),
                            "page_number": _page(evidence_row, source.page_count),
                            "bbox": None,
                            "quoted_text": _value(evidence_row, "evidence_text"),
                            "caption": _value(evidence_row, "source_locator"),
                        }
                    )
                edge_links.append(
                    {
                        "edge_ref": row["lineage_edge_id"],
                        "evidence_ref": ref,
                        "role": "supports",
                    }
                )

        activities = []
        for row, value, operator, page in activity_rows:
            evidence_ref = f"activity-evidence:{row['activity_id']}"
            evidence.append(
                {
                    "ref": evidence_ref,
                    "kind": "table",
                    "page_number": page,
                    "bbox": None,
                    "quoted_text": _value(row, "evidence_text"),
                    "caption": _value(row, "source_locator"),
                }
            )
            activities.append(
                {
                    "compound_ref": row["compound_entity_id"],
                    "evidence_ref": evidence_ref,
                    "assay_name": row["assay"],
                    "metric": row["metric"],
                    "operator": operator,
                    "value": value,
                    "unit": _value(row, "unit"),
                    "context": _value(row, "target"),
                }
            )

        doi = next(
            (
                value
                for row in (*entity_rows.values(), *valid_edges)
                if (value := _value(row, "doi")) is not None
            ),
            None,
        )
        return AiPrefillPayload.model_validate(
            {
                "schema_version": 1,
                "bibliography": {"doi": doi},
                "compounds": compounds,
                "structure_locators": [],
                "lineages": lineages,
                "evidence": evidence,
                "edge_evidence_links": edge_links,
                "activities": activities,
            }
        )


__all__ = ["LegacyPipelineAdapter"]
