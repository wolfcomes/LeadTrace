from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tempfile
from collections.abc import Mapping


SCHEMA_VERSION = 1
PILOT_SIZE = 20
_ROOT_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _validate_relative_posix(value: str, *, label: str) -> str:
    if not value or "\\" in value:
        raise ValueError(f"{label} must be relative POSIX")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{label} must be relative POSIX")
    if value.endswith("/") or path.as_posix() != value:
        raise ValueError(f"{label} must be relative POSIX")
    return value


def _validate_root_key(value: str) -> str:
    if not _ROOT_KEY.fullmatch(value) or value in {".", ".."}:
        raise ValueError("source_root_key must be a logical key")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, payload: Mapping[str, object]) -> None:
    path = path.resolve(strict=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with open(descriptor, "w", encoding="utf-8", newline="\n", closefd=True) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
        Path(temporary_name).replace(path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def build_manifest(
    source_root: Path,
    output: Path,
    *,
    source_directory: str,
    source_root_key: str,
    collection: Mapping[str, object],
    created_on: str,
) -> dict[str, object]:
    """Build a stable manifest from exactly twenty direct lowercase PDF files."""
    source_root = Path(source_root).resolve(strict=True)
    if not source_root.is_dir():
        raise ValueError(f"source root is not a directory: {source_root}")
    source_directory = _validate_relative_posix(source_directory, label="source_directory")
    source_root_key = _validate_root_key(source_root_key)
    try:
        date.fromisoformat(created_on)
    except ValueError as error:
        raise ValueError("created_on must be an ISO date") from error
    directory = source_root / source_directory
    if not directory.is_dir():
        raise ValueError(f"source directory does not exist: {source_directory}")

    candidates = sorted(directory.iterdir(), key=lambda path: path.name)
    pdfs: list[Path] = []
    for path in candidates:
        if path.is_symlink():
            raise ValueError(f"symlink is not allowed: {path.name}")
        if path.is_file() and path.suffix == ".pdf":
            pdfs.append(path)
    if len(pdfs) < PILOT_SIZE:
        raise ValueError(f"expected exactly 20 direct PDFs; found {len(pdfs)}")
    selected = pdfs[:PILOT_SIZE]
    hashes = [_sha256(path) for path in selected]
    if len(set(hashes)) != len(hashes):
        raise ValueError("duplicate SHA-256 among pilot PDFs")

    entries = []
    for order, (path, digest) in enumerate(zip(selected, hashes, strict=True), start=1):
        source_key = (PurePosixPath(source_directory) / path.name).as_posix()
        entries.append(
            {
                "manifest_order": order,
                "original_filename": path.name,
                "source_key": source_key,
                "sha256": digest,
                "byte_size": path.stat().st_size,
            }
        )
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "source_root_key": source_root_key,
        "source_directory": source_directory,
        "collection": dict(collection),
        "created_on": created_on,
        "entries": entries,
    }
    _atomic_write(Path(output), payload)
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the deterministic 20-paper pilot manifest")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-directory", required=True)
    parser.add_argument("--source-root-key", required=True)
    parser.add_argument("--journal", required=True)
    parser.add_argument("--publication-year", type=int, required=True)
    parser.add_argument("--volume", required=True)
    parser.add_argument("--issue", required=True)
    parser.add_argument("--created-on", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    payload = build_manifest(
        args.source_root,
        args.output,
        source_directory=args.source_directory,
        source_root_key=args.source_root_key,
        collection={
            "journal": args.journal,
            "publication_year": args.publication_year,
            "volume": args.volume,
            "issue": args.issue,
        },
        created_on=args.created_on,
    )
    print(f"entries={len(payload['entries'])} output={Path(args.output).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
