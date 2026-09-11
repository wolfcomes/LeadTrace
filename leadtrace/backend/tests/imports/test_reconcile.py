from __future__ import annotations

import csv
from pathlib import Path

from app.imports.reconcile import (
    DEFAULT_EXPECTED_AGGREGATE,
    DEFAULT_SOURCE_MANIFEST,
    reconcile_baseline,
)


def _rewrite_csv(path: Path, transform: object) -> None:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        assert fieldnames is not None
        rows = list(reader)
    assert callable(transform)
    transform(rows)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_fixture_reconciliation_uses_exact_scientific_counts_and_paths(
    baseline_fixture: dict[str, object],
) -> None:
    source_root = baseline_fixture["source_root"]
    manifest_path = baseline_fixture["manifest_path"]
    expected = baseline_fixture["expected"]
    assert isinstance(source_root, Path)
    assert isinstance(manifest_path, Path)
    assert isinstance(expected, dict)

    report = reconcile_baseline(
        source_root,
        expected=expected,
        source_manifest_path=manifest_path,
    )

    assert report.matches_expected is True
    assert report.counts == expected["counts"]
    assert report.integrity == expected["integrity_expectations"]
    assert report.asset_linkage.resolved_references == 3
    assert report.asset_linkage.missing_references == 0
    assert report.asset_linkage.ambiguous_references == 0
    assert {item.manifest_path for item in report.asset_linkage.resolved} == {
        "source_pdfs/articles/paper.pdf",
        "source_pdfs/project/09_paper_review/auto_fill/molecule_review_crops/OBJ-1.png",
    }


def test_asset_linking_never_guesses_from_a_duplicate_basename(
    baseline_fixture: dict[str, object],
) -> None:
    source_root = baseline_fixture["source_root"]
    manifest_path = baseline_fixture["manifest_path"]
    paper_pdf = baseline_fixture["paper_pdf"]
    expected = baseline_fixture["expected"]
    assert isinstance(source_root, Path)
    assert isinstance(manifest_path, Path)
    assert isinstance(paper_pdf, Path)
    assert isinstance(expected, dict)
    paper_pdf.unlink()

    report = reconcile_baseline(
        source_root,
        expected=expected,
        source_manifest_path=manifest_path,
    )

    paper_issues = [
        item for item in report.asset_linkage.issues if item.original_id == "paper-1"
    ]
    assert paper_issues
    assert paper_issues[0].status == "missing"
    assert all(
        item.manifest_path != "source_pdfs/other/paper.pdf"
        for item in report.asset_linkage.resolved
        if item.original_id == "paper-1"
    )


def test_asset_reconciliation_detects_same_size_content_tampering(
    baseline_fixture: dict[str, object],
) -> None:
    source_root = baseline_fixture["source_root"]
    manifest_path = baseline_fixture["manifest_path"]
    paper_pdf = baseline_fixture["paper_pdf"]
    expected = baseline_fixture["expected"]
    assert isinstance(source_root, Path)
    assert isinstance(manifest_path, Path)
    assert isinstance(paper_pdf, Path)
    assert isinstance(expected, dict)
    original = paper_pdf.read_bytes()
    paper_pdf.write_bytes(original.replace(b"fixture", b"Fixture"))
    assert paper_pdf.stat().st_size == len(original)

    report = reconcile_baseline(
        source_root,
        expected=expected,
        source_manifest_path=manifest_path,
    )

    assert report.asset_linkage.corrupt_references == 2
    assert all(
        item.manifest_path != "source_pdfs/articles/paper.pdf"
        for item in report.asset_linkage.resolved
    )


def test_reconciliation_rejects_valid_ids_bound_to_another_paper(
    baseline_fixture: dict[str, object],
) -> None:
    source_root = baseline_fixture["source_root"]
    manifest_path = baseline_fixture["manifest_path"]
    expected = baseline_fixture["expected"]
    assert isinstance(source_root, Path)
    assert isinstance(manifest_path, Path)
    assert isinstance(expected, dict)

    def add_second_paper(rows: list[dict[str, str]]) -> None:
        second = dict(rows[0])
        second["paper_id"] = "paper-2"
        rows.append(second)

    _rewrite_csv(
        source_root / "01_manifest" / "all_volume67_papers.csv",
        add_second_paper,
    )

    def move_compound(rows: list[dict[str, str]]) -> None:
        rows[1]["paper_id"] = "paper-2"
        rows[1]["doi"] = "10.1000/fixture-2"

    _rewrite_csv(
        source_root / "09_paper_review" / "auto_fill" / "compound_entities.csv",
        move_compound,
    )
    expected = {
        **expected,
        "counts": {**expected["counts"], "corpus_papers": 2},
    }

    report = reconcile_baseline(
        source_root,
        expected=expected,
        source_manifest_path=manifest_path,
    )

    assert report.matches_expected is False
    assert report.integrity["dangling_entity_references"] > 0
    assert report.integrity["invalid_pair_endpoints"] > 0


def test_full_authoritative_baseline_reconciles_to_fixed_acceptance_counts() -> None:
    source_root = Path(
        "../../source_pdfs/分子修改提取_2024_JMC"
    ).resolve()

    report = reconcile_baseline(
        source_root,
        expected_path=DEFAULT_EXPECTED_AGGREGATE,
        source_manifest_path=DEFAULT_SOURCE_MANIFEST,
    )

    assert report.matches_expected is True
    assert report.counts == {
        "corpus_papers": 672,
        "lineage_papers": 138,
        "lineages": 193,
        "compound_entities": 4301,
        "lineage_edges": 4144,
        "activity_rows": 620,
        "complete_structures": 4012,
        "structure_confirmed": 4011,
        "missing_or_non_unique": 289,
        "pair_ready_edges": 1730,
        "papers_with_pair_ready": 131,
    }
    assert set(report.integrity.values()) == {0}
