from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from leadtrace.ops.baseline.migrate_unique_papers import (
    MigrationError,
    build_migration,
    rewrite_csv,
)


FIELDS = [
    "paper_id",
    "source_folder",
    "source_pdf",
    "filename",
    "filename_year",
    "title_guess",
    "file_size_bytes",
]


def _pdf(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _manifest_entry(path: str, content: bytes) -> dict[str, object]:
    return {
        "path": path,
        "byte_size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def test_build_migration_keeps_legacy_id_matching_current_pdf_hash(tmp_path: Path) -> None:
    current = _pdf(tmp_path / "source_pdfs/volume67 issue9/shared.pdf", b"winner")
    rows = [
        dict(zip(FIELDS, ["OLD", "case2", "old", "shared.pdf", "2024", "Title", "5"])),
        dict(zip(FIELDS, ["KEEP", "case4", "old", "shared.pdf", "2024", "Title", "6"])),
    ]
    manifest = {
        "files": [
            _manifest_entry("source_pdfs/case2/shared.pdf", b"loser"),
            _manifest_entry("source_pdfs/case4/shared.pdf", b"winner"),
        ]
    }

    result = build_migration(rows, manifest, [current], workspace_root=tmp_path)

    assert result.id_map == {"OLD": "KEEP"}
    assert len(result.paper_rows) == 1
    assert result.paper_rows[0]["paper_id"] == "KEEP"
    assert result.paper_rows[0]["source_folder"] == "volume67 issue9"
    assert result.paper_rows[0]["source_pdf"] == "source_pdfs/volume67 issue9/shared.pdf"
    assert result.paper_rows[0]["file_size_bytes"] == "6"


def test_build_migration_rejects_duplicate_without_one_hash_match(tmp_path: Path) -> None:
    current = _pdf(tmp_path / "source_pdfs/volume67 issue9/shared.pdf", b"current")
    rows = [
        dict(zip(FIELDS, ["A", "one", "old", "shared.pdf", "2024", "Title", "3"])),
        dict(zip(FIELDS, ["B", "two", "old", "shared.pdf", "2024", "Title", "3"])),
    ]
    manifest = {"files": [
        _manifest_entry("source_pdfs/one/shared.pdf", b"old-a"),
        _manifest_entry("source_pdfs/two/shared.pdf", b"old-b"),
    ]}

    with pytest.raises(MigrationError, match="exactly one legacy hash"):
        build_migration(rows, manifest, [current], workspace_root=tmp_path)


def test_rewrite_csv_updates_paper_id_and_pdf_path(tmp_path: Path) -> None:
    path = tmp_path / "objects.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["object_id", "paper_id", "source_pdf"])
        writer.writeheader()
        writer.writerow({"object_id": "O1", "paper_id": "OLD", "source_pdf": "/old/shared.pdf"})

    changed = rewrite_csv(
        path,
        id_map={"OLD": "KEEP"},
        pdf_paths={"shared.pdf": "source_pdfs/volume67 issue9/shared.pdf"},
        apply=True,
    )

    assert changed == 1
    with path.open(encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row == {
        "object_id": "O1",
        "paper_id": "KEEP",
        "source_pdf": "source_pdfs/volume67 issue9/shared.pdf",
    }


def test_rewrite_csv_rejects_duplicate_primary_keys_after_merge(tmp_path: Path) -> None:
    path = tmp_path / "objects.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["object_id", "paper_id"])
        writer.writeheader()
        writer.writerows([
            {"object_id": "O1", "paper_id": "OLD"},
            {"object_id": "O1", "paper_id": "KEEP"},
        ])

    with pytest.raises(MigrationError, match="duplicate records"):
        rewrite_csv(path, id_map={"OLD": "KEEP"}, pdf_paths={}, apply=False)
