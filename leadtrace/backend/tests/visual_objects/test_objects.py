from __future__ import annotations

import pytest

from app.visual_objects.objects import (
    MoleculeObjectType,
    MoleculeObjectService,
    ObjectVersionConflict,
    ObjectValidationError,
    build_object_snapshot,
    normalize_object_type,
)
from app.visual_objects.objects_router import _error
from app.visual_objects.objects_router import create_visual_objects_router


def test_object_type_is_controlled_and_snapshot_is_stable() -> None:
    assert normalize_object_type("r_group") is MoleculeObjectType.R_GROUP
    snapshot = build_object_snapshot(
        object_key="obj-1",
        object_type=MoleculeObjectType.R_GROUP,
        label="R1",
    )
    assert snapshot == {
        "object_key": "obj-1",
        "object_type": "r_group",
        "label": "R1",
    }


def test_unknown_object_type_is_rejected() -> None:
    with pytest.raises(ObjectValidationError):
        normalize_object_type("lineage_edge")


def test_stale_visual_object_edit_is_a_revision_conflict() -> None:
    with pytest.raises(ObjectVersionConflict) as error:
        MoleculeObjectService.check_expected_version(7, expected_version=6)

    assert error.value.expected_version == 6
    assert error.value.current_version == 7
    response = _error(error.value)
    assert response.status_code == 409
    assert response.detail["code"] == "REVISION_CONFLICT"


def test_visual_object_router_exposes_versioned_update() -> None:
    router = create_visual_objects_router("test-session-secret")
    matching = [
        route
        for route in router.routes
        if route.path.endswith("/{object_id}") and "PATCH" in route.methods
    ]
    assert len(matching) == 1
