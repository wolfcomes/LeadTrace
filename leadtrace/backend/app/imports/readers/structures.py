from __future__ import annotations

from pathlib import Path

from app.imports.readers.lineages import AUTO_FILL
from app.imports.readers.manifest import StagedSourceRecord, read_csv_records


def read_confirmed_structure_records(
    source_root: Path,
) -> list[StagedSourceRecord]:
    return read_csv_records(
        source_root,
        f"{AUTO_FILL}/confirmed_compound_structures.csv",
        record_type="structure",
        id_field="confirmed_structure_id",
    )


def read_structure_source_records(
    source_root: Path,
) -> list[StagedSourceRecord]:
    return read_csv_records(
        source_root,
        f"{AUTO_FILL}/structure_source_manifest.csv",
        record_type="structure_source",
        id_field="source_id",
    )
