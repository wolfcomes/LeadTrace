from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

from app.imports.readers.lineages import (
    derive_lineage_records,
    read_activity_records,
    read_compound_records,
    read_edge_records,
    read_evidence_records,
)
from app.imports.readers.manifest import (
    StagedSourceRecord,
    read_csv_records,
)
from app.imports.readers.structures import (
    read_confirmed_structure_records,
    read_structure_source_records,
)
from app.imports.readers.visuals import read_visual_object_records


_HERE = Path(__file__).resolve()
_LEADTRACE_ROOT = _HERE.parents[3]
_WORKSPACE_ROOT = _LEADTRACE_ROOT.parent
DEFAULT_EXPECTED_AGGREGATE = (
    _LEADTRACE_ROOT / "ops" / "baseline" / "expected_aggregate.json"
)
DEFAULT_SOURCE_MANIFEST = (
    _WORKSPACE_ROOT / "docs" / "baseline" / "2026-09-10-source-manifest.json"
)
PAPER_MANIFEST = "01_manifest/all_volume67_papers.csv"


@dataclass(frozen=True, slots=True)
class BaselineSourceData:
    papers: list[StagedSourceRecord]
    compounds: list[StagedSourceRecord]
    lineages: list[StagedSourceRecord]
    edges: list[StagedSourceRecord]
    evidence: list[StagedSourceRecord]
    activities: list[StagedSourceRecord]
    structures: list[StagedSourceRecord]
    confirmed_structures: list[StagedSourceRecord]
    visual_objects: list[StagedSourceRecord]
    structure_sources: list[StagedSourceRecord]

    @property
    def object_records(self) -> list[StagedSourceRecord]:
        return [
            *self.papers,
            *self.compounds,
            *self.lineages,
            *self.edges,
            *self.evidence,
            *self.activities,
            *self.structures,
            *self.visual_objects,
        ]

    @property
    def fingerprint_records(self) -> list[StagedSourceRecord]:
        return [*self.object_records, *self.structure_sources]


@dataclass(frozen=True, slots=True)
class ResolvedAssetReference:
    record_type: str
    original_id: str
    link_role: str
    manifest_path: str
    sha256: str
    byte_size: int


@dataclass(frozen=True, slots=True)
class AssetLinkageIssue:
    record_type: str
    original_id: str
    link_role: str
    status: str


@dataclass(slots=True)
class AssetLinkageReport:
    resolved_references: int = 0
    missing_references: int = 0
    ambiguous_references: int = 0
    corrupt_references: int = 0
    resolved: list[ResolvedAssetReference] = field(default_factory=list)
    issues: list[AssetLinkageIssue] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    source_fingerprint: str
    counts: dict[str, int]
    integrity: dict[str, int]
    matches_expected: bool
    differences: dict[str, dict[str, int | None]]
    asset_linkage: AssetLinkageReport

    def as_dict(self) -> dict[str, object]:
        return {
            "source_fingerprint": self.source_fingerprint,
            "counts": self.counts,
            "integrity": self.integrity,
            "matches_expected": self.matches_expected,
            "differences": self.differences,
            "asset_linkage": self.asset_linkage.as_dict(),
        }


def _derived_structure_record(compound: StagedSourceRecord) -> StagedSourceRecord:
    compound_id = compound.original_id
    original_id = f"BASELINE-STRUCTURE-{compound_id}"
    raw_values = {
        "confirmed_structure_id": original_id,
        "paper_id": compound.raw_values.get("paper_id"),
        "compound_entity_id": compound.raw_values.get("compound_entity_id"),
        "compound_label": compound.raw_values.get("display_label"),
        "canonical_isomeric_smiles": compound.raw_values.get("canonical_smiles"),
        "confirmation_status": compound.raw_values.get("structure_review_status"),
        "structure_source_type": compound.raw_values.get("structure_source_type"),
        "structure_source_file": compound.raw_values.get("structure_source_file"),
        "structure_source_locator": compound.raw_values.get(
            "structure_source_locator"
        ),
        "derived_from_compound_record": compound_id,
    }
    normalized_values = {
        "confirmed_structure_id": original_id,
        "paper_id": compound.normalized_values.get("paper_id"),
        "compound_entity_id": compound_id,
        "compound_label": compound.normalized_values.get("display_label"),
        "canonical_isomeric_smiles": compound.normalized_values.get(
            "canonical_smiles"
        ),
        "confirmation_status": compound.normalized_values.get(
            "structure_review_status"
        ),
        "structure_source_type": compound.normalized_values.get(
            "structure_source_type"
        ),
        "structure_source_file": compound.normalized_values.get(
            "structure_source_file"
        ),
        "structure_source_locator": compound.normalized_values.get(
            "structure_source_locator"
        ),
        "derived_from_compound_record": compound_id,
    }
    return StagedSourceRecord(
        record_type="structure",
        original_id=original_id,
        source_file=compound.source_file,
        source_row_locator=compound.source_row_locator,
        source_hash=compound.source_hash,
        raw_values=raw_values,
        normalized_values=normalized_values,
    )


def load_baseline_source(source_root: Path) -> BaselineSourceData:
    papers = read_csv_records(
        source_root,
        PAPER_MANIFEST,
        record_type="paper",
        id_field="paper_id",
    )
    compounds = read_compound_records(source_root)
    edges = read_edge_records(source_root)
    confirmed_structures = read_confirmed_structure_records(source_root)
    confirmed_compound_ids = {
        record.normalized_values.get("compound_entity_id")
        for record in confirmed_structures
    }
    structures = list(confirmed_structures)
    structures.extend(
        _derived_structure_record(compound)
        for compound in compounds
        if compound.normalized_values.get("structure_status")
        == "complete_structure_resolved"
        and compound.original_id not in confirmed_compound_ids
    )
    return BaselineSourceData(
        papers=papers,
        compounds=compounds,
        lineages=derive_lineage_records(edges),
        edges=edges,
        evidence=read_evidence_records(source_root),
        activities=read_activity_records(source_root),
        structures=structures,
        confirmed_structures=confirmed_structures,
        visual_objects=read_visual_object_records(source_root),
        structure_sources=read_structure_source_records(source_root),
    )


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload


def _load_expected(
    *,
    expected: dict[str, object] | None,
    expected_path: Path | None,
) -> tuple[dict[str, int], dict[str, int]]:
    payload = expected
    if payload is None:
        payload = _load_json_object(
            (expected_path or DEFAULT_EXPECTED_AGGREGATE).resolve(),
            label="Expected aggregate",
        )
    raw_counts = payload.get("counts")
    raw_integrity = payload.get("integrity_expectations")
    if not isinstance(raw_counts, dict) or not isinstance(raw_integrity, dict):
        raise ValueError(
            "Expected aggregate requires counts and integrity_expectations objects"
        )
    if not all(isinstance(value, int) for value in raw_counts.values()):
        raise ValueError("Expected aggregate counts must be integers")
    if not all(isinstance(value, int) for value in raw_integrity.values()):
        raise ValueError("Expected integrity values must be integers")
    return dict(raw_counts), dict(raw_integrity)


def _source_fingerprint(
    data: BaselineSourceData,
    source_manifest_path: Path,
) -> str:
    source_files = {
        record.source_file: record.source_hash
        for record in data.fingerprint_records
    }
    manifest_hash = hashlib.sha256(source_manifest_path.read_bytes()).hexdigest()
    payload = {
        "fact_files": sorted(source_files.items()),
        "source_manifest_sha256": manifest_hash,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _counts(data: BaselineSourceData) -> dict[str, int]:
    complete_structures = sum(
        record.normalized_values.get("structure_status")
        == "complete_structure_resolved"
        for record in data.compounds
    )
    pair_ready = [
        record
        for record in data.edges
        if record.normalized_values.get("pair_eligible") == "yes"
    ]
    return {
        "corpus_papers": len(data.papers),
        "lineage_papers": len(
            {
                record.normalized_values.get("paper_id")
                for record in data.lineages
            }
        ),
        "lineages": len(data.lineages),
        "compound_entities": len(data.compounds),
        "lineage_edges": len(data.edges),
        "activity_rows": len(data.activities),
        "complete_structures": complete_structures,
        "structure_confirmed": sum(
            record.normalized_values.get("confirmation_status")
            == "structure_confirmed"
            for record in data.confirmed_structures
        ),
        "missing_or_non_unique": len(data.compounds) - complete_structures,
        "pair_ready_edges": len(pair_ready),
        "papers_with_pair_ready": len(
            {
                record.normalized_values.get("paper_id")
                for record in pair_ready
            }
        ),
    }


def _integrity(data: BaselineSourceData) -> dict[str, int]:
    compounds = {
        record.original_id: record.normalized_values for record in data.compounds
    }
    edge_ids = {record.original_id for record in data.edges}
    evidence_ids = {record.original_id for record in data.evidence}
    directed_edges = Counter(
        (
            record.normalized_values.get("lineage_id"),
            record.normalized_values.get("parent_entity_id"),
            record.normalized_values.get("derived_entity_id"),
        )
        for record in data.edges
    )
    self_loops = 0
    unresolved_pair_ready = 0
    dangling_entities = 0
    dangling_evidence = 0
    invalid_pair_endpoints = 0
    for edge in data.edges:
        values = edge.normalized_values
        parent_id = values.get("parent_entity_id")
        derived_id = values.get("derived_entity_id")
        if parent_id is not None and parent_id == derived_id:
            self_loops += 1
        if parent_id is not None and parent_id not in compounds:
            dangling_entities += 1
        if derived_id not in compounds:
            dangling_entities += 1
        evidence_id = values.get("evidence_ids")
        if evidence_id is not None and evidence_id not in evidence_ids:
            dangling_evidence += 1
        if values.get("pair_eligible") != "yes":
            continue
        if parent_id is None or derived_id is None:
            unresolved_pair_ready += 1
            continue
        parent = compounds.get(parent_id)
        derived = compounds.get(derived_id)
        endpoints = (parent, derived)
        if parent_id == derived_id or any(
            endpoint is None
            or endpoint.get("structure_status") != "complete_structure_resolved"
            or endpoint.get("structure_review_status") != "structure_confirmed"
            for endpoint in endpoints
        ):
            invalid_pair_endpoints += 1
    dangling_entities += sum(
        record.normalized_values.get("compound_entity_id") not in compounds
        for record in data.activities
    )
    dangling_entities += sum(
        record.normalized_values.get("compound_entity_id") not in compounds
        for record in data.structures
    )
    dangling_evidence += sum(
        record.normalized_values.get("lineage_edge_id") not in edge_ids
        for record in data.evidence
    )
    return {
        "self_loops": self_loops,
        "duplicate_directed_edges": sum(
            occurrence_count - 1
            for occurrence_count in directed_edges.values()
            if occurrence_count > 1
        ),
        "unresolved_pair_ready_edges": unresolved_pair_ready,
        "dangling_entity_references": dangling_entities,
        "dangling_evidence_references": dangling_evidence,
        "invalid_pair_endpoints": invalid_pair_endpoints,
        # Baseline candidates are never published by the importer.
        "published_missing_or_corrupt_assets": 0,
    }


def _safe_manifest_key(value: str) -> str | None:
    pure_path = PurePosixPath(value)
    if (
        pure_path.is_absolute()
        or "\\" in value
        or any(part in {"", ".", ".."} for part in pure_path.parts)
    ):
        return None
    return pure_path.as_posix()


class _AssetResolver:
    def __init__(
        self,
        *,
        source_root: Path,
        source_manifest_path: Path,
        data: BaselineSourceData,
    ) -> None:
        payload = _load_json_object(source_manifest_path, label="Source manifest")
        raw_workspace_root = payload.get("workspace_root")
        raw_files = payload.get("files")
        if not isinstance(raw_workspace_root, str) or not isinstance(raw_files, list):
            raise ValueError("Source manifest requires workspace_root and files")
        self.workspace_root = Path(raw_workspace_root).resolve()
        self.source_root = source_root.resolve()
        try:
            self.source_root_key = self.source_root.relative_to(
                self.workspace_root
            ).as_posix()
        except ValueError as error:
            raise ValueError("Source root is outside the manifested workspace") from error
        self.entries: dict[str, list[dict[str, object]]] = defaultdict(list)
        for raw_entry in raw_files:
            if not isinstance(raw_entry, dict):
                raise ValueError("Source manifest file entries must be objects")
            raw_path = raw_entry.get("path")
            if not isinstance(raw_path, str):
                raise ValueError("Source manifest file entry is missing path")
            manifest_key = _safe_manifest_key(raw_path)
            if manifest_key is None:
                raise ValueError("Source manifest contains an unsafe path")
            self.entries[manifest_key].append(raw_entry)
        self.report = AssetLinkageReport()
        self.paper_paths = {
            record.original_id: self._paper_manifest_path(record)
            for record in data.papers
        }
        self.structure_paths: dict[tuple[str, str], list[str]] = defaultdict(list)
        for record in data.structure_sources:
            values = record.normalized_values
            paper_id = values.get("paper_id")
            source_file = values.get("source_file")
            local_path = values.get("local_path")
            if not all(isinstance(value, str) for value in (paper_id, source_file)):
                continue
            if isinstance(local_path, str):
                self.structure_paths[(paper_id, source_file)].append(local_path)

    def _paper_manifest_path(self, record: StagedSourceRecord) -> str | None:
        source_folder = record.normalized_values.get("source_folder")
        filename = record.normalized_values.get("filename")
        if not isinstance(source_folder, str) or not isinstance(filename, str):
            return None
        return _safe_manifest_key(
            PurePosixPath("source_pdfs", source_folder, filename).as_posix()
        )

    def _issue(
        self,
        record: StagedSourceRecord,
        link_role: str,
        status: str,
    ) -> None:
        if status == "ambiguous":
            self.report.ambiguous_references += 1
        elif status == "corrupt":
            self.report.corrupt_references += 1
        else:
            self.report.missing_references += 1
        self.report.issues.append(
            AssetLinkageIssue(
                record_type=record.record_type,
                original_id=record.original_id,
                link_role=link_role,
                status=status,
            )
        )

    def _add_exact(
        self,
        record: StagedSourceRecord,
        link_role: str,
        manifest_path: str | None,
    ) -> None:
        if manifest_path is None:
            self._issue(record, link_role, "missing")
            return
        entries = self.entries.get(manifest_path, [])
        if not entries:
            self._issue(record, link_role, "missing")
            return
        if len(entries) > 1:
            self._issue(record, link_role, "ambiguous")
            return
        target = (self.workspace_root / manifest_path).resolve(strict=False)
        try:
            target.relative_to(self.workspace_root)
        except ValueError:
            self._issue(record, link_role, "missing")
            return
        entry = entries[0]
        if not target.is_file():
            self._issue(record, link_role, "missing")
            return
        byte_size = entry.get("byte_size")
        sha256 = entry.get("sha256")
        if (
            not isinstance(byte_size, int)
            or not isinstance(sha256, str)
            or target.stat().st_size != byte_size
        ):
            self._issue(record, link_role, "corrupt")
            return
        self.report.resolved_references += 1
        self.report.resolved.append(
            ResolvedAssetReference(
                record_type=record.record_type,
                original_id=record.original_id,
                link_role=link_role,
                manifest_path=manifest_path,
                sha256=sha256,
                byte_size=byte_size,
            )
        )

    def _path_value(self, value: str) -> str | None:
        parsed = urlparse(value)
        if parsed.scheme and parsed.scheme not in {"file"}:
            return None
        candidate = Path(value)
        if candidate.is_absolute():
            resolved = candidate.resolve(strict=False)
            try:
                return resolved.relative_to(self.workspace_root).as_posix()
            except ValueError:
                return None
        safe_value = _safe_manifest_key(value)
        if safe_value is None:
            return None
        if safe_value.startswith("source_pdfs/"):
            return safe_value
        return _safe_manifest_key(
            PurePosixPath(self.source_root_key, safe_value).as_posix()
        )

    def add_papers(self, records: list[StagedSourceRecord]) -> None:
        for record in records:
            self._add_exact(
                record,
                "article_pdf",
                self.paper_paths.get(record.original_id),
            )

    def add_visuals(self, records: list[StagedSourceRecord]) -> None:
        for record in records:
            for source_field, link_role in (
                ("source_pdf", "visual_source_pdf"),
                ("source_crop_path", "visual_source_crop"),
                ("crop_path", "visual_crop"),
            ):
                value = record.normalized_values.get(source_field)
                if not isinstance(value, str):
                    continue
                self._add_exact(record, link_role, self._path_value(value))

    def add_structures(self, records: list[StagedSourceRecord]) -> None:
        for record in records:
            values = record.normalized_values
            paper_id = values.get("paper_id")
            source_value = values.get("structure_source_file")
            if not isinstance(paper_id, str) or not isinstance(source_value, str):
                continue
            parsed = urlparse(source_value)
            if parsed.scheme and parsed.scheme not in {"file"}:
                continue
            for token in (part.strip() for part in source_value.split(";")):
                if not token:
                    continue
                if "/" in token or Path(token).is_absolute():
                    self._add_exact(
                        record,
                        "structure_source",
                        self._path_value(token),
                    )
                    continue
                candidates = sorted(
                    set(self.structure_paths.get((paper_id, token), []))
                )
                if not candidates:
                    self._issue(record, "structure_source", "missing")
                elif len(candidates) > 1:
                    self._issue(record, "structure_source", "ambiguous")
                else:
                    self._add_exact(
                        record,
                        "structure_source",
                        self._path_value(candidates[0]),
                    )


def _asset_linkage(
    source_root: Path,
    source_manifest_path: Path,
    data: BaselineSourceData,
) -> AssetLinkageReport:
    resolver = _AssetResolver(
        source_root=source_root,
        source_manifest_path=source_manifest_path,
        data=data,
    )
    resolver.add_papers(data.papers)
    resolver.add_visuals(data.visual_objects)
    resolver.add_structures(data.structures)
    return resolver.report


def _differences(
    actual_counts: dict[str, int],
    expected_counts: dict[str, int],
    actual_integrity: dict[str, int],
    expected_integrity: dict[str, int],
) -> dict[str, dict[str, int | None]]:
    differences: dict[str, dict[str, int | None]] = {}
    for prefix, actual, expected in (
        ("count", actual_counts, expected_counts),
        ("integrity", actual_integrity, expected_integrity),
    ):
        for key in sorted(set(actual) | set(expected)):
            if actual.get(key) == expected.get(key):
                continue
            differences[f"{prefix}.{key}"] = {
                "expected": expected.get(key),
                "actual": actual.get(key),
            }
    return differences


def reconcile_baseline(
    source_root: Path,
    *,
    expected: dict[str, object] | None = None,
    expected_path: Path | None = None,
    source_manifest_path: Path = DEFAULT_SOURCE_MANIFEST,
) -> ReconciliationReport:
    """Read all baseline facts and produce a path-safe, write-free comparison."""

    resolved_source_root = source_root.resolve()
    resolved_manifest_path = source_manifest_path.resolve()
    data = load_baseline_source(resolved_source_root)
    expected_counts, expected_integrity = _load_expected(
        expected=expected,
        expected_path=expected_path,
    )
    actual_counts = _counts(data)
    actual_integrity = _integrity(data)
    differences = _differences(
        actual_counts,
        expected_counts,
        actual_integrity,
        expected_integrity,
    )
    return ReconciliationReport(
        source_fingerprint=_source_fingerprint(data, resolved_manifest_path),
        counts=actual_counts,
        integrity=actual_integrity,
        matches_expected=not differences,
        differences=differences,
        asset_linkage=_asset_linkage(
            resolved_source_root,
            resolved_manifest_path,
            data,
        ),
    )
