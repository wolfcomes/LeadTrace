from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID


_MISSING = object()


def _pointer_segment(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _flatten(snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    flattened: dict[str, Any] = {}

    def visit(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            if not value:
                flattened[path] = {}
                return
            for key in sorted(value, key=str):
                visit(value[key], f"{path}/{_pointer_segment(str(key))}")
            return
        flattened[path] = value

    if snapshot is not None:
        for key in sorted(snapshot, key=str):
            visit(snapshot[key], f"/{_pointer_segment(str(key))}")
    return flattened


def _overlay_region_fields(
    flattened: dict[str, Any],
    region_fields: Mapping[str, object] | None,
) -> None:
    """Overlay dedicated region columns using stable JSON-pointer paths."""

    if region_fields is None:
        return
    for key in sorted(region_fields, key=str):
        flattened[f"/region/{_pointer_segment(str(key))}"] = region_fields[key]


def _values_equal(before: Any, after: Any) -> bool:
    if type(before) is not type(after):
        return False
    if isinstance(before, Mapping):
        return (
            before.keys() == after.keys()
            and all(_values_equal(before[key], after[key]) for key in before)
        )
    if isinstance(before, list):
        return len(before) == len(after) and all(
            _values_equal(before_item, after_item)
            for before_item, after_item in zip(before, after, strict=True)
        )
    return bool(before == after)


def _category(object_kind: str, path: str, before: Any, after: Any) -> str:
    segments = path.casefold().split("/")
    leaf = segments[-1]
    if any(segment in {"bindings", "binding", "compound_bindings"} for segment in segments):
        return "binding"
    if leaf.endswith("_smiles") or leaf == "smiles":
        return "smiles"
    if leaf in {
        "parent_compound_id",
        "derived_compound_id",
        "parent_entity_id",
        "derived_entity_id",
        "source_id",
        "target_id",
    }:
        return "lineage_endpoint"
    region_fields = {"x0", "y0", "x1", "y1", "rotation", "rotation_degrees"}
    if leaf in region_fields and (
        "region" in segments or str(object_kind).casefold() == "visual_region"
    ):
        return "region_coordinate"
    if leaf.endswith("text") or leaf in {"abstract", "description", "notes", "reason"}:
        return "text"
    if isinstance(before, (list, dict)) or isinstance(after, (list, dict)):
        return "collection"
    return "scalar"


def build_revision_diff(
    *,
    object_id: UUID | str,
    object_kind: str,
    base_revision_id: UUID | str | None,
    proposed_revision_id: UUID | str | None,
    before_snapshot: Mapping[str, Any] | None,
    after_snapshot: Mapping[str, Any] | None,
    before_region_fields: Mapping[str, object] | None = None,
    after_region_fields: Mapping[str, object] | None = None,
    before_tombstone: bool = False,
    after_tombstone: bool = False,
) -> dict[str, object]:
    """Return a deterministic, identity-preserving structured revision diff.

    ``*_region_fields`` carries values stored in dedicated ``ObjectRevision``
    columns. ``None`` means that the region envelope is absent; keys whose
    values are ``None`` remain present so callers can distinguish SQL ``NULL``
    from a missing field via the ``*_present`` flags.
    """

    before_values = _flatten(before_snapshot)
    after_values = _flatten(after_snapshot)
    if str(object_kind).casefold() == "visual_region":
        _overlay_region_fields(before_values, before_region_fields)
        _overlay_region_fields(after_values, after_region_fields)
    changes: list[dict[str, object]] = []
    for path in sorted(before_values.keys() | after_values.keys()):
        before = before_values.get(path, _MISSING)
        after = after_values.get(path, _MISSING)
        before_present = before is not _MISSING
        after_present = after is not _MISSING
        if before_present and after_present and _values_equal(before, after):
            continue
        before_value = before if before_present else None
        after_value = after if after_present else None
        changes.append(
            {
                "path": path,
                "category": _category(
                    object_kind,
                    path,
                    before_value,
                    after_value,
                ),
                "before_present": before_present,
                "after_present": after_present,
                "before": before_value,
                "after": after_value,
            }
        )
    if before_tombstone != after_tombstone:
        changes.append(
            {
                "path": "/$tombstone",
                "category": "lifecycle",
                "before_present": True,
                "after_present": True,
                "before": before_tombstone,
                "after": after_tombstone,
            }
        )
        changes.sort(key=lambda change: str(change["path"]))

    if after_tombstone and not before_tombstone:
        change_type = "tombstone"
    elif before_snapshot is None and after_snapshot is not None:
        change_type = "create"
    elif before_snapshot is not None and after_snapshot is None:
        change_type = "tombstone"
    elif changes:
        change_type = "update"
    else:
        change_type = "no_change"

    return {
        "object_id": str(object_id),
        "object_kind": object_kind,
        "base_revision_id": str(base_revision_id) if base_revision_id else None,
        "proposed_revision_id": (
            str(proposed_revision_id) if proposed_revision_id else None
        ),
        "change_type": change_type,
        "changes": changes,
    }
