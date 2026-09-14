from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
from typing import Iterable, Mapping, Sequence


class MigrationError(ValueError):
    pass


@dataclass(frozen=True)
class Migration:
    paper_rows: list[dict[str, str]]
    id_map: dict[str, str]
    pdf_paths: dict[str, str]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _legacy_path(row: Mapping[str, str]) -> str:
    return PurePosixPath(
        "source_pdfs", row["source_folder"], row["filename"]
    ).as_posix()


def build_migration(
    paper_rows: Sequence[Mapping[str, str]],
    source_manifest: Mapping[str, object],
    current_pdfs: Iterable[Path],
    *,
    workspace_root: Path,
) -> Migration:
    workspace = workspace_root.resolve()
    pdf_by_name: dict[str, Path] = {}
    for raw_path in current_pdfs:
        path = raw_path.resolve()
        if path.name in pdf_by_name:
            raise MigrationError(f"duplicate current PDF filename: {path.name}")
        try:
            path.relative_to(workspace)
        except ValueError as error:
            raise MigrationError("current PDF is outside the workspace") from error
        pdf_by_name[path.name] = path

    groups: dict[str, list[Mapping[str, str]]] = {}
    for row in paper_rows:
        groups.setdefault(row["filename"], []).append(row)
    if set(groups) != set(pdf_by_name):
        missing = sorted(set(groups) - set(pdf_by_name))
        unexpected = sorted(set(pdf_by_name) - set(groups))
        raise MigrationError(
            f"paper/PDF filename mismatch: missing={missing!r} unexpected={unexpected!r}"
        )

    entries = source_manifest.get("files")
    if not isinstance(entries, list):
        raise MigrationError("source manifest has no files list")
    hashes = {
        entry.get("path"): entry.get("sha256")
        for entry in entries
        if isinstance(entry, dict)
    }

    migrated: list[dict[str, str]] = []
    id_map: dict[str, str] = {}
    pdf_paths: dict[str, str] = {}
    for filename, rows in groups.items():
        current = pdf_by_name[filename]
        relative = current.relative_to(workspace).as_posix()
        current_hash = _sha256(current)
        if len(rows) == 1:
            canonical = rows[0]
        else:
            matches = [
                row for row in rows
                if hashes.get(_legacy_path(row)) == current_hash
            ]
            if len(matches) != 1:
                raise MigrationError(
                    f"duplicate {filename!r} must have exactly one legacy hash "
                    f"matching the current PDF; found {len(matches)}"
                )
            canonical = matches[0]
            canonical_id = canonical["paper_id"]
            id_map.update(
                (row["paper_id"], canonical_id)
                for row in rows
                if row["paper_id"] != canonical_id
            )
        output = dict(canonical)
        output["source_folder"] = current.parent.name
        output["source_pdf"] = relative
        output["file_size_bytes"] = str(current.stat().st_size)
        migrated.append(output)
        pdf_paths[filename] = relative

    migrated.sort(key=lambda row: row["paper_id"])
    return Migration(migrated, dict(sorted(id_map.items())), pdf_paths)


def _atomic_csv(path: Path, fieldnames: Sequence[str], rows: Sequence[Mapping[str, str]]) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary_path = Path(temporary)
        if temporary_path.exists():
            temporary_path.unlink()


def rewrite_csv(
    path: Path,
    *,
    id_map: Mapping[str, str],
    pdf_paths: Mapping[str, str],
    apply: bool,
) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise MigrationError(f"CSV has no header: {path}")
        fieldnames = reader.fieldnames
        rows = [dict(row) for row in reader]
    changed = 0
    for row in rows:
        dirty = False
        if "paper_id" in row and row["paper_id"] in id_map:
            row["paper_id"] = id_map[row["paper_id"]]
            dirty = True
        for field in ("source_pdf", "visual_source_pdf"):
            value = row.get(field)
            if value:
                filename = PurePosixPath(value.replace("\\", "/")).name
                replacement = pdf_paths.get(filename)
                if replacement is not None and value != replacement:
                    row[field] = replacement
                    dirty = True
        changed += int(dirty)
    if fieldnames:
        first = fieldnames[0]
        keys = [row[first] for row in rows]
        if len(keys) != len(set(keys)):
            raise MigrationError(f"rewrite would create duplicate records in {path}")
    if apply and changed:
        _atomic_csv(path, fieldnames, rows)
    return changed


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise MigrationError(f"CSV has no header: {path}")
        return reader.fieldnames, [dict(row) for row in reader]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    workspace = args.workspace_root.resolve()
    source_root = args.source_root.resolve()
    paper_path = source_root / "01_manifest/all_volume67_papers.csv"
    fields, paper_rows = _read_csv(paper_path)
    manifest = json.loads(args.source_manifest.read_text(encoding="utf-8"))
    current_pdfs = sorted((workspace / "source_pdfs").glob("volume* issue*/*.pdf"))
    migration = build_migration(
        paper_rows, manifest, current_pdfs, workspace_root=workspace
    )

    authoritative = [
        source_root / "09_paper_review/auto_fill" / name
        for name in (
            "compound_entities.csv",
            "compound_lineage_edges.csv",
            "compound_lineage_evidence.csv",
            "compound_activities.csv",
            "first_page_molecule_objects.csv",
            "confirmed_compound_structures.csv",
            "structure_source_manifest.csv",
        )
    ]
    changes = {
        path.relative_to(source_root).as_posix(): rewrite_csv(
            path,
            id_map=migration.id_map,
            pdf_paths=migration.pdf_paths,
            apply=args.apply,
        )
        for path in authoritative
    }
    if args.apply:
        _atomic_csv(paper_path, fields, migration.paper_rows)
    report = {
        "applied": args.apply,
        "paper_count_before": len(paper_rows),
        "paper_count_after": len(migration.paper_rows),
        "duplicate_mappings": migration.id_map,
        "rewritten_rows": changes,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
