from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _manifest_entry(workspace: Path, path: Path) -> dict[str, object]:
    content = path.read_bytes()
    return {
        "path": path.relative_to(workspace).as_posix(),
        "byte_size": len(content),
        "mtime_ns": path.stat().st_mtime_ns,
        "sha256": hashlib.sha256(content).hexdigest(),
        "category": "pdf" if path.suffix == ".pdf" else "image",
    }


@pytest.fixture
def baseline_fixture(tmp_path: Path) -> dict[str, object]:
    workspace = tmp_path / "workspace"
    source_root = workspace / "source_pdfs" / "project"
    manifest_dir = source_root / "01_manifest"
    auto = source_root / "09_paper_review" / "auto_fill"
    article_dir = workspace / "source_pdfs" / "articles"
    duplicate_dir = workspace / "source_pdfs" / "other"
    crop_dir = auto / "molecule_review_crops"
    article_dir.mkdir(parents=True)
    duplicate_dir.mkdir(parents=True)
    crop_dir.mkdir(parents=True)
    paper_pdf = article_dir / "paper.pdf"
    paper_pdf.write_bytes(b"%PDF-1.4\nfixture paper\n%%EOF\n")
    duplicate_pdf = duplicate_dir / "paper.pdf"
    duplicate_pdf.write_bytes(b"%PDF-1.4\nwrong same basename\n%%EOF\n")
    crop = crop_dir / "OBJ-1.png"
    crop.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDAT\x08\xd7c\xf8\xcf\xc0\x00\x00\x03\x01"
        b"\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    _write_csv(
        manifest_dir / "all_volume67_papers.csv",
        [
            {
                "paper_id": "paper-1",
                "source_folder": "articles",
                "source_pdf": r"D:\legacy\articles\paper.pdf",
                "filename": "paper.pdf",
                "filename_year": "2026",
                "title_guess": "Fixture paper",
                "file_size_bytes": str(paper_pdf.stat().st_size),
            }
        ],
    )
    _write_csv(
        auto / "compound_entities.csv",
        [
            {
                "compound_entity_id": "CMP-1",
                "paper_id": "paper-1",
                "doi": "10.1000/fixture",
                "display_label": "26a′",
                "normalized_label": "26a′",
                "canonical_smiles": "CCO",
                "structure_status": "complete_structure_resolved",
                "structure_review_status": "structure_confirmed",
                "review_status": "unreviewed",
            },
            {
                "compound_entity_id": "CMP-2",
                "paper_id": "paper-1",
                "doi": "10.1000/fixture",
                "display_label": "26b",
                "normalized_label": "26b",
                "canonical_smiles": "CCN",
                "structure_status": "complete_structure_resolved",
                "structure_review_status": "structure_confirmed",
                "review_status": "unreviewed",
            },
        ],
    )
    _write_csv(
        auto / "compound_lineage_edges.csv",
        [
            {
                "lineage_edge_id": "EDGE-1",
                "lineage_id": "LINEAGE-1",
                "paper_id": "paper-1",
                "doi": "10.1000/fixture",
                "parent_entity_id": "CMP-1",
                "derived_entity_id": "CMP-2",
                "relation_type": "direct_optimization",
                "relation_status": "text_explicit",
                "evidence_ids": "EVID-1",
                "pair_eligible": "yes",
                "review_status": "unreviewed",
            }
        ],
    )
    _write_csv(
        auto / "compound_lineage_evidence.csv",
        [
            {
                "lineage_evidence_id": "EVID-1",
                "lineage_edge_id": "EDGE-1",
                "lineage_id": "LINEAGE-1",
                "paper_id": "paper-1",
                "evidence_text": "line one\nline two",
                "source_locator": "page=2",
                "review_status": "unreviewed",
            }
        ],
    )
    _write_csv(
        auto / "compound_activities.csv",
        [
            {
                "activity_id": "ACT-1",
                "paper_id": "paper-1",
                "compound_entity_id": "CMP-2",
                "metric": "IC50",
                "value": "12",
                "unit": "nM",
                "qualifier": "=",
                "source_locator": "table=1",
                "evidence_text": "IC50 = 12 nM",
                "review_status": "unreviewed",
            }
        ],
    )
    _write_csv(
        auto / "confirmed_compound_structures.csv",
        [
            {
                "confirmed_structure_id": "CONF-1",
                "paper_id": "paper-1",
                "compound_entity_id": "CMP-1",
                "compound_label": "26a′",
                "canonical_isomeric_smiles": "CCO",
                "confirmation_status": "structure_confirmed",
                "structure_source_file": "external://fixture/1",
            },
            {
                "confirmed_structure_id": "CONF-2",
                "paper_id": "paper-1",
                "compound_entity_id": "CMP-2",
                "compound_label": "26b",
                "canonical_isomeric_smiles": "CCN",
                "confirmation_status": "structure_confirmed",
                "structure_source_file": "external://fixture/2",
            },
        ],
    )
    _write_csv(
        auto / "first_page_molecule_objects.csv",
        [
            {
                "object_id": "OBJ-1",
                "paper_id": "paper-1",
                "source_pdf": str(paper_pdf),
                "page": "1",
                "object_type": "complete_molecule",
                "compound_label": "26a′",
                "source_crop_path": "--",
                "crop_path": str(crop),
                "review_status": "object_requires_human_review",
            }
        ],
    )
    _write_csv(
        auto / "structure_source_manifest.csv",
        [
            {
                "source_id": "external-1",
                "paper_id": "paper-1",
                "source_file": "external.json",
                "local_path": "--",
                "sha256": "",
                "download_status": "deferred",
            }
        ],
    )
    manifest_path = workspace / "docs" / "baseline" / "source-manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_files = [
        _manifest_entry(workspace, paper_pdf),
        _manifest_entry(workspace, duplicate_pdf),
        _manifest_entry(workspace, crop),
    ]
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": str(workspace),
                "file_count": len(manifest_files),
                "total_bytes": sum(item["byte_size"] for item in manifest_files),
                "source_roots": ["source_pdfs"],
                "files": manifest_files,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    expected = {
        "counts": {
            "corpus_papers": 1,
            "lineage_papers": 1,
            "lineages": 1,
            "compound_entities": 2,
            "lineage_edges": 1,
            "activity_rows": 1,
            "complete_structures": 2,
            "structure_confirmed": 2,
            "missing_or_non_unique": 0,
            "pair_ready_edges": 1,
            "papers_with_pair_ready": 1,
        },
        "integrity_expectations": {
            "self_loops": 0,
            "duplicate_directed_edges": 0,
            "unresolved_pair_ready_edges": 0,
            "dangling_entity_references": 0,
            "dangling_evidence_references": 0,
            "invalid_pair_endpoints": 0,
            "published_missing_or_corrupt_assets": 0,
        },
    }
    return {
        "workspace": workspace,
        "source_root": source_root,
        "manifest_path": manifest_path,
        "paper_pdf": paper_pdf,
        "duplicate_pdf": duplicate_pdf,
        "crop": crop,
        "expected": expected,
    }
