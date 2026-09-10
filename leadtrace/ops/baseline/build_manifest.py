from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Iterable, Sequence


SCHEMA_VERSION = 1
CHUNK_SIZE = 1024 * 1024
EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
}
EXCLUDED_SUFFIXES = {".lock", ".log", ".pyc", ".tmp"}


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _is_excluded(path: Path, source_root: Path) -> bool:
    relative = path.relative_to(source_root)
    if any(
        part in EXCLUDED_DIRECTORY_NAMES or part.startswith(".venv")
        for part in relative.parts[:-1]
    ):
        return True
    return path.suffix.casefold() in EXCLUDED_SUFFIXES


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _category(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".csv", ".json", ".tsv", ".xls", ".xlsx"}:
        return "structured_data"
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}:
        return "image"
    if suffix in {".py", ".js", ".ts", ".vue", ".html", ".css"}:
        return "source_code"
    if suffix in {".md", ".txt"}:
        return "documentation"
    if suffix in {".zip", ".tar", ".gz"}:
        return "archive"
    return "other"


def _normalize_roots(
    source_roots: Iterable[Path],
    *,
    workspace_root: Path,
) -> list[Path]:
    workspace = workspace_root.resolve(strict=True)
    roots: list[Path] = []
    for raw_root in source_roots:
        root = Path(raw_root).resolve(strict=True)
        if not root.is_dir():
            raise ValueError(f"source root is not a directory: {root}")
        if not _is_relative_to(root, workspace):
            raise ValueError(f"source root must be within workspace: {root}")
        if root not in roots:
            roots.append(root)
    if not roots:
        raise ValueError("at least one source root is required")
    return sorted(roots, key=lambda path: path.relative_to(workspace).as_posix())


def collect_manifest(
    source_roots: Iterable[Path],
    *,
    workspace_root: Path,
) -> dict[str, object]:
    workspace = Path(workspace_root).resolve(strict=True)
    roots = _normalize_roots(source_roots, workspace_root=workspace)
    rows: list[dict[str, object]] = []
    for root in roots:
        for path in root.rglob("*"):
            if path.is_symlink() or not path.is_file() or _is_excluded(path, root):
                continue
            stat = path.stat()
            rows.append(
                {
                    "path": path.relative_to(workspace).as_posix(),
                    "byte_size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                    "sha256": _sha256(path),
                    "category": _category(path),
                }
            )
    rows.sort(key=lambda row: str(row["path"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "workspace_root": str(workspace),
        "source_roots": [root.relative_to(workspace).as_posix() for root in roots],
        "file_count": len(rows),
        "total_bytes": sum(int(row["byte_size"]) for row in rows),
        "files": rows,
    }


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def build_manifest(
    source_roots: Iterable[Path],
    output: Path,
    *,
    workspace_root: Path,
) -> dict[str, object]:
    workspace = Path(workspace_root).resolve(strict=True)
    roots = _normalize_roots(source_roots, workspace_root=workspace)
    destination = Path(output).resolve(strict=False)
    if any(_is_relative_to(destination, root) for root in roots):
        raise ValueError("manifest output must be outside every source root")
    payload = collect_manifest(roots, workspace_root=workspace)
    _atomic_write_json(destination, payload)
    return payload


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a read-only source manifest.")
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, action="append")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    workspace = args.workspace_root.resolve(strict=True)
    roots = args.source_root or [workspace / "source_pdfs"]
    payload = build_manifest(roots, args.output, workspace_root=workspace)
    print(
        f"files={payload['file_count']} total_bytes={payload['total_bytes']} "
        f"output={Path(args.output).resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
