from __future__ import annotations

from uuid import uuid4

from app.revisions.diff import build_revision_diff


def _diff(
    before: dict[str, object] | None,
    after: dict[str, object] | None,
    *,
    before_tombstone: bool = False,
    after_tombstone: bool = False,
) -> dict[str, object]:
    return build_revision_diff(
        object_id=uuid4(),
        object_kind="paper",
        base_revision_id=uuid4() if before is not None else None,
        proposed_revision_id=uuid4(),
        before_snapshot=before,
        after_snapshot=after,
        before_tombstone=before_tombstone,
        after_tombstone=after_tombstone,
    )


def test_scalar_and_long_text_diff_is_deterministic_and_retains_identity() -> None:
    object_id = uuid4()
    base_revision_id = uuid4()
    proposed_revision_id = uuid4()
    long_before = "old evidence " * 600
    long_after = "corrected evidence " * 600
    kwargs = {
        "object_id": object_id,
        "object_kind": "evidence",
        "base_revision_id": base_revision_id,
        "proposed_revision_id": proposed_revision_id,
        "before_snapshot": {
            "title": "Old title",
            "evidence_text": long_before,
            "year": 2024,
        },
        "after_snapshot": {
            "title": "New title",
            "evidence_text": long_after,
            "year": 2025,
        },
    }

    first = build_revision_diff(**kwargs)
    second = build_revision_diff(**kwargs)

    assert first == second
    assert first["object_id"] == str(object_id)
    assert first["base_revision_id"] == str(base_revision_id)
    assert first["proposed_revision_id"] == str(proposed_revision_id)
    assert first["change_type"] == "update"
    assert [change["path"] for change in first["changes"]] == [
        "/evidence_text",
        "/title",
        "/year",
    ]
    assert first["changes"][0] == {
        "path": "/evidence_text",
        "category": "text",
        "before_present": True,
        "after_present": True,
        "before": long_before,
        "after": long_after,
    }


def test_create_update_and_tombstone_are_distinct() -> None:
    created = _diff(None, {"title": "Created"})
    updated = _diff({"title": "Old"}, {"title": "New"})
    tombstoned = _diff(
        {"title": "Retired"},
        {"title": "Retired"},
        after_tombstone=True,
    )

    assert created["change_type"] == "create"
    assert created["changes"] == [
        {
            "path": "/title",
            "category": "scalar",
            "before_present": False,
            "after_present": True,
            "before": None,
            "after": "Created",
        }
    ]
    assert updated["change_type"] == "update"
    assert tombstoned["change_type"] == "tombstone"
    assert tombstoned["changes"] == [
        {
            "path": "/$tombstone",
            "category": "lifecycle",
            "before_present": True,
            "after_present": True,
            "before": False,
            "after": True,
        }
    ]


def test_scientific_fields_have_stable_categories_and_nested_paths() -> None:
    result = _diff(
        {
            "bindings": [{"compound_id": "cmp-1", "label": "1a"}],
            "region": {"x0": 0.1, "y0": 0.2, "x1": 0.4, "y1": 0.5},
            "canonical_smiles": "CCO",
            "lineage": {"parent_compound_id": "cmp-1", "derived_compound_id": "cmp-2"},
        },
        {
            "bindings": [{"compound_id": "cmp-1", "label": "1b"}],
            "region": {"x0": 0.12, "y0": 0.2, "x1": 0.4, "y1": 0.5},
            "canonical_smiles": "CCN",
            "lineage": {"parent_compound_id": "cmp-1", "derived_compound_id": "cmp-3"},
        },
    )

    assert result["changes"] == [
        {
            "path": "/bindings",
            "category": "binding",
            "before_present": True,
            "after_present": True,
            "before": [{"compound_id": "cmp-1", "label": "1a"}],
            "after": [{"compound_id": "cmp-1", "label": "1b"}],
        },
        {
            "path": "/canonical_smiles",
            "category": "smiles",
            "before_present": True,
            "after_present": True,
            "before": "CCO",
            "after": "CCN",
        },
        {
            "path": "/lineage/derived_compound_id",
            "category": "lineage_endpoint",
            "before_present": True,
            "after_present": True,
            "before": "cmp-2",
            "after": "cmp-3",
        },
        {
            "path": "/region/x0",
            "category": "region_coordinate",
            "before_present": True,
            "after_present": True,
            "before": 0.1,
            "after": 0.12,
        },
    ]


def test_unchanged_revision_has_no_changes() -> None:
    result = _diff({"title": "Same"}, {"title": "Same"})

    assert result["change_type"] == "no_change"
    assert result["changes"] == []


def test_absent_null_and_boolean_integer_values_remain_distinct() -> None:
    result = _diff(
        {"reviewed": True},
        {"reviewed": 1, "note": None},
    )

    assert result["changes"] == [
        {
            "path": "/note",
            "category": "scalar",
            "before_present": False,
            "after_present": True,
            "before": None,
            "after": None,
        },
        {
            "path": "/reviewed",
            "category": "scalar",
            "before_present": True,
            "after_present": True,
            "before": True,
            "after": 1,
        },
    ]


def test_real_import_field_names_map_to_scientific_categories() -> None:
    result = _diff(
        {
            "canonical_isomeric_smiles": "CCO",
            "parent_entity_id": "entity-1",
            "derived_entity_id": "entity-2",
        },
        {
            "canonical_isomeric_smiles": "CCN",
            "parent_entity_id": "entity-3",
            "derived_entity_id": "entity-4",
        },
    )

    assert {
        change["path"]: change["category"] for change in result["changes"]
    } == {
        "/canonical_isomeric_smiles": "smiles",
        "/derived_entity_id": "lineage_endpoint",
        "/parent_entity_id": "lineage_endpoint",
    }


def test_visual_region_snapshot_envelope_maps_coordinates_by_object_kind() -> None:
    result = build_revision_diff(
        object_id=uuid4(),
        object_kind="visual_region",
        base_revision_id=uuid4(),
        proposed_revision_id=uuid4(),
        before_snapshot={
            "normalized_values": {"x0": 0.1, "rotation": 0.0},
        },
        after_snapshot={
            "normalized_values": {"x0": 0.2, "rotation": 90.0},
        },
    )

    assert {
        change["path"]: change["category"] for change in result["changes"]
    } == {
        "/normalized_values/rotation": "region_coordinate",
        "/normalized_values/x0": "region_coordinate",
    }


def test_dedicated_region_columns_are_diffed_when_snapshots_match() -> None:
    result = build_revision_diff(
        object_id=uuid4(),
        object_kind="visual_region",
        base_revision_id=uuid4(),
        proposed_revision_id=uuid4(),
        before_snapshot={"normalized_values": {"label": "Figure 1"}},
        after_snapshot={"normalized_values": {"label": "Figure 1"}},
        before_region_fields={
            "x0": 0.1,
            "y0": 0.2,
            "x1": 0.4,
            "y1": 0.5,
            "rotation": 0,
        },
        after_region_fields={
            "x0": 0.2,
            "y0": 0.2,
            "x1": 0.4,
            "y1": 0.5,
            "rotation": 90,
        },
    )

    assert result["change_type"] == "update"
    assert result["changes"] == [
        {
            "path": "/region/rotation",
            "category": "region_coordinate",
            "before_present": True,
            "after_present": True,
            "before": 0,
            "after": 90,
        },
        {
            "path": "/region/x0",
            "category": "region_coordinate",
            "before_present": True,
            "after_present": True,
            "before": 0.1,
            "after": 0.2,
        },
    ]


def test_dedicated_region_columns_preserve_missing_and_explicit_null() -> None:
    missing_to_null = build_revision_diff(
        object_id=uuid4(),
        object_kind="visual_region",
        base_revision_id=uuid4(),
        proposed_revision_id=uuid4(),
        before_snapshot={},
        after_snapshot={},
        before_region_fields=None,
        after_region_fields={"x0": None},
    )

    assert missing_to_null["changes"] == [
        {
            "path": "/region/x0",
            "category": "region_coordinate",
            "before_present": False,
            "after_present": True,
            "before": None,
            "after": None,
        }
    ]

    value_to_null = build_revision_diff(
        object_id=uuid4(),
        object_kind="visual_region",
        base_revision_id=uuid4(),
        proposed_revision_id=uuid4(),
        before_snapshot={},
        after_snapshot={},
        before_region_fields={"x0": 0.1},
        after_region_fields={"x0": None},
    )

    assert value_to_null["changes"] == [
        {
            "path": "/region/x0",
            "category": "region_coordinate",
            "before_present": True,
            "after_present": True,
            "before": 0.1,
            "after": None,
        }
    ]
