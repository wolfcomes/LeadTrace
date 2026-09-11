from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
from pathlib import Path, PurePosixPath
import unicodedata


SOURCE_NULL_MARKERS = frozenset({"", "--"})


@dataclass(frozen=True, slots=True)
class StagedSourceRecord:
    """One source fact with both forensic and application-ready values."""

    record_type: str
    original_id: str
    source_file: str
    source_row_locator: str
    source_hash: str
    raw_values: dict[str, str | None]
    normalized_values: dict[str, str | None]


def normalize_source_value(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFC", value.strip())
    if normalized in SOURCE_NULL_MARKERS:
        return None
    return normalized


def _source_path(source_root: Path, relative_path: str) -> tuple[Path, str]:
    root = source_root.resolve()
    pure_path = PurePosixPath(relative_path)
    if (
        pure_path.is_absolute()
        or "\\" in relative_path
        or any(part in {"", ".", ".."} for part in pure_path.parts)
    ):
        raise ValueError("Baseline source path must be a safe relative POSIX path")
    lexical_path = root.joinpath(*pure_path.parts)
    first_component = root / pure_path.parts[0]
    allowed_root = first_component.resolve() if first_component.is_symlink() else root
    path = lexical_path.resolve()
    try:
        path.relative_to(allowed_root)
    except ValueError as error:
        raise ValueError("Baseline source path escapes the source root") from error
    if not path.is_file():
        raise FileNotFoundError(f"Required baseline fact file is missing: {relative_path}")
    return path, pure_path.as_posix()


def hash_source_file(source_root: Path, relative_path: str) -> str:
    path, _ = _source_path(source_root, relative_path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv_records(
    source_root: Path,
    relative_path: str,
    *,
    record_type: str,
    id_field: str,
) -> list[StagedSourceRecord]:
    """Read logical CSV records without losing raw text or source provenance."""

    path, source_file = _source_path(source_root, relative_path)
    source_hash = hash_source_file(source_root, relative_path)
    records: list[StagedSourceRecord] = []
    seen_ids: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or id_field not in reader.fieldnames:
            raise ValueError(f"Required ID field {id_field!r} is missing from {source_file}")
        for logical_row_number, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(f"Malformed CSV record in {source_file} at row:{logical_row_number}")
            raw_values = {str(key): value for key, value in row.items()}
            normalized_values = {
                key: normalize_source_value(value)
                for key, value in raw_values.items()
            }
            original_id = normalized_values.get(id_field)
            if not isinstance(original_id, str) or not original_id:
                raise ValueError(
                    f"Missing source ID in {source_file} at row:{logical_row_number}"
                )
            if original_id in seen_ids:
                raise ValueError(f"Duplicate source ID {original_id!r} in {source_file}")
            seen_ids.add(original_id)
            records.append(
                StagedSourceRecord(
                    record_type=record_type,
                    original_id=original_id,
                    source_file=source_file,
                    source_row_locator=f"row:{logical_row_number}",
                    source_hash=source_hash,
                    raw_values=raw_values,
                    normalized_values=normalized_values,
                )
            )
    return records
