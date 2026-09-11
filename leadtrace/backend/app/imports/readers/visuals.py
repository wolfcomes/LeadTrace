from __future__ import annotations

from pathlib import Path

from app.imports.readers.lineages import AUTO_FILL
from app.imports.readers.manifest import StagedSourceRecord, read_csv_records


def read_visual_object_records(source_root: Path) -> list[StagedSourceRecord]:
    return read_csv_records(
        source_root,
        f"{AUTO_FILL}/first_page_molecule_objects.csv",
        record_type="visual_object",
        id_field="object_id",
    )
