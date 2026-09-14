from __future__ import annotations

import json
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


def _normalized_crop_reference(source_root: Path, value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("Molecule proposal crop_path must be text")
    candidate = Path(value)
    if candidate.is_absolute():
        resolved_candidate = candidate.resolve()
        try:
            return resolved_candidate.relative_to(source_root.resolve()).as_posix()
        except ValueError:
            # A read-only worktree may expose the scientific corpus through a
            # nested symlink while the CSV still records the canonical main
            # workspace path. Accept only a suffix that resolves to the exact
            # same file through this source root.
            for anchor in ("09_paper_review",):
                if anchor not in candidate.parts:
                    continue
                suffix = Path(*candidate.parts[candidate.parts.index(anchor) :])
                if (source_root / suffix).resolve() == resolved_candidate:
                    return suffix.as_posix()
            raise ValueError("Molecule proposal crop_path is outside the source root")
    if "\\" in value or any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValueError("Molecule proposal crop_path is unsafe")
    return candidate.as_posix()


def _token_confidences(value: object) -> list[dict[str, object]]:
    if not isinstance(value, str):
        raise ValueError("Molecule proposal token_confidences must be JSON")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError(
            "Molecule proposal token_confidences must be valid JSON"
        ) from error
    if not isinstance(parsed, list):
        raise ValueError("Molecule proposal token_confidences must be a list")
    normalized: list[dict[str, object]] = []
    for item in parsed:
        if not isinstance(item, dict):
            raise ValueError("Molecule proposal token confidence must be an object")
        token = item.get("token")
        confidence = item.get("confidence")
        if (
            not isinstance(token, str)
            or not token
            or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 1
        ):
            raise ValueError("Molecule proposal token confidence is invalid")
        normalized.append({"token": token, "confidence": float(confidence)})
    return normalized


def read_molecule_proposal_records(
    source_root: Path,
) -> list[StagedSourceRecord]:
    records = read_csv_records(
        source_root,
        f"{AUTO_FILL}/first_page_molecule_proposals.csv",
        record_type="molecule_proposal",
        id_field="object_id",
    )
    prepared: list[StagedSourceRecord] = []
    for record in records:
        values = dict(record.normalized_values)
        object_id = values.get("object_id")
        model_version = values.get("model_version")
        updated_at = values.get("updated_at")
        if not all(
            isinstance(value, str) and value
            for value in (object_id, model_version, updated_at)
        ):
            raise ValueError(
                "Molecule proposal requires object_id, model_version, and updated_at"
            )
        values["token_confidences"] = _token_confidences(
            values.get("token_confidences")
        )
        values["crop_path"] = _normalized_crop_reference(
            source_root, values.get("crop_path")
        )
        values["proposal_key"] = f"ocsr:{object_id}"
        values["model_run_key"] = f"{model_version}:{updated_at}"
        prepared.append(
            StagedSourceRecord(
                record_type=record.record_type,
                original_id=record.original_id,
                source_file=record.source_file,
                source_row_locator=record.source_row_locator,
                source_hash=record.source_hash,
                raw_values=record.raw_values,
                normalized_values=values,
            )
        )
    return prepared
