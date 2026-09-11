from __future__ import annotations

from pathlib import Path

from app.imports.readers.manifest import StagedSourceRecord, read_csv_records


AUTO_FILL = "09_paper_review/auto_fill"


def read_compound_records(source_root: Path) -> list[StagedSourceRecord]:
    return read_csv_records(
        source_root,
        f"{AUTO_FILL}/compound_entities.csv",
        record_type="compound",
        id_field="compound_entity_id",
    )


def read_edge_records(source_root: Path) -> list[StagedSourceRecord]:
    return read_csv_records(
        source_root,
        f"{AUTO_FILL}/compound_lineage_edges.csv",
        record_type="lineage_edge",
        id_field="lineage_edge_id",
    )


def read_evidence_records(source_root: Path) -> list[StagedSourceRecord]:
    return read_csv_records(
        source_root,
        f"{AUTO_FILL}/compound_lineage_evidence.csv",
        record_type="evidence",
        id_field="lineage_evidence_id",
    )


def read_activity_records(source_root: Path) -> list[StagedSourceRecord]:
    return read_csv_records(
        source_root,
        f"{AUTO_FILL}/compound_activities.csv",
        record_type="activity",
        id_field="activity_id",
    )


def derive_lineage_records(
    edge_records: list[StagedSourceRecord],
) -> list[StagedSourceRecord]:
    """Create one traceable stable-lineage fact from its first source edge."""

    records: dict[str, StagedSourceRecord] = {}
    for edge in edge_records:
        lineage_id = edge.normalized_values.get("lineage_id")
        if not isinstance(lineage_id, str) or not lineage_id:
            raise ValueError(
                f"Edge {edge.original_id!r} does not identify a lineage"
            )
        if lineage_id in records:
            continue
        raw_values = {
            "lineage_id": edge.raw_values.get("lineage_id"),
            "paper_id": edge.raw_values.get("paper_id"),
            "doi": edge.raw_values.get("doi"),
            "source_edge_id": edge.raw_values.get("lineage_edge_id"),
            "annotation_version": edge.raw_values.get("annotation_version"),
        }
        normalized_values = {
            "lineage_id": lineage_id,
            "paper_id": edge.normalized_values.get("paper_id"),
            "doi": edge.normalized_values.get("doi"),
            "source_edge_id": edge.original_id,
            "annotation_version": edge.normalized_values.get("annotation_version"),
        }
        records[lineage_id] = StagedSourceRecord(
            record_type="lineage",
            original_id=lineage_id,
            source_file=edge.source_file,
            source_row_locator=edge.source_row_locator,
            source_hash=edge.source_hash,
            raw_values=raw_values,
            normalized_values=normalized_values,
        )
    return list(records.values())
