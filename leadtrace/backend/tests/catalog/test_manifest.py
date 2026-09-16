from __future__ import annotations

import json
from pathlib import Path

import pytest

from leadtrace.ops.pilot.build_manifest import build_manifest


COLLECTION = {
    "journal": "Journal of Medicinal Chemistry",
    "publication_year": 2024,
    "volume": "67",
    "issue": "5",
}


def _write_pdf(path: Path, marker: str) -> None:
    path.write_bytes(f"%PDF-1.4\n% {marker}\n%%EOF\n".encode())


def _build(source_root: Path, output: Path) -> dict[str, object]:
    return build_manifest(
        source_root,
        output,
        source_directory="volume67 issue5",
        source_root_key="source_pdfs",
        collection=COLLECTION,
        created_on="2026-09-15",
    )


def test_manifest_selects_the_first_twenty_direct_pdfs_deterministically(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "protected sources"
    source_directory = source_root / "volume67 issue5"
    nested = source_directory / "nested"
    nested.mkdir(parents=True)
    names = [f"paper-{index:02d}.pdf" for index in range(21)] + ["文章-α.pdf"]
    for index, name in enumerate(reversed(names)):
        _write_pdf(source_directory / name, f"content-{index}")
    _write_pdf(nested / "ignored.pdf", "nested")
    _write_pdf(source_directory / "ignored.PDF", "uppercase suffix")
    (source_directory / "notes.txt").write_text("not a PDF", encoding="utf-8")

    first_output = tmp_path / "first.json"
    second_output = tmp_path / "second.json"
    payload = _build(source_root, first_output)
    _build(source_root, second_output)

    expected_names = sorted(names)[:20]
    entries = payload["entries"]
    assert isinstance(entries, list)
    assert [entry["original_filename"] for entry in entries] == expected_names
    assert [entry["manifest_order"] for entry in entries] == list(range(1, 21))
    assert [entry["source_key"] for entry in entries] == [
        f"volume67 issue5/{name}" for name in expected_names
    ]
    assert len({entry["sha256"] for entry in entries}) == 20
    assert all(entry["byte_size"] > 0 for entry in entries)
    assert payload["schema_version"] == 1
    assert payload["source_root_key"] == "source_pdfs"
    assert payload["source_directory"] == "volume67 issue5"
    assert payload["collection"] == COLLECTION
    assert payload["created_on"] == "2026-09-15"
    assert first_output.read_bytes() == second_output.read_bytes()
    assert str(source_root).encode() not in first_output.read_bytes()
    assert json.loads(first_output.read_text(encoding="utf-8")) == payload


def test_manifest_rejects_direct_pdf_symlinks(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_directory = source_root / "volume67 issue5"
    source_directory.mkdir(parents=True)
    outside = tmp_path / "outside.pdf"
    _write_pdf(outside, "outside")
    for index in range(20):
        _write_pdf(source_directory / f"paper-{index:02d}.pdf", str(index))
    (source_directory / "linked.pdf").symlink_to(outside)

    with pytest.raises(ValueError, match="symlink"):
        _build(source_root, tmp_path / "manifest.json")


def test_manifest_rejects_duplicate_pdf_hashes(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_directory = source_root / "volume67 issue5"
    source_directory.mkdir(parents=True)
    for index in range(20):
        _write_pdf(source_directory / f"paper-{index:02d}.pdf", str(index // 2))

    with pytest.raises(ValueError, match="duplicate SHA-256"):
        _build(source_root, tmp_path / "manifest.json")


@pytest.mark.parametrize("source_directory", ["../escape", "/absolute/path", "a/../b"])
def test_manifest_rejects_traversal_and_absolute_source_directories(
    tmp_path: Path,
    source_directory: str,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()

    with pytest.raises(ValueError, match="relative POSIX"):
        build_manifest(
            source_root,
            tmp_path / "manifest.json",
            source_directory=source_directory,
            source_root_key="source_pdfs",
            collection=COLLECTION,
            created_on="2026-09-15",
        )


def test_manifest_requires_an_existing_directory_with_twenty_pdfs(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    source_directory = source_root / "volume67 issue5"
    source_directory.mkdir(parents=True)
    for index in range(19):
        _write_pdf(source_directory / f"paper-{index:02d}.pdf", str(index))

    with pytest.raises(ValueError, match="exactly 20"):
        _build(source_root, tmp_path / "manifest.json")

    with pytest.raises(ValueError, match="does not exist"):
        build_manifest(
            source_root,
            tmp_path / "missing.json",
            source_directory="missing",
            source_root_key="source_pdfs",
            collection=COLLECTION,
            created_on="2026-09-15",
        )
