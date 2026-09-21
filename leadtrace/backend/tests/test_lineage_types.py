from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.ai_prefill.contracts import AiLineage
from app.lineages.schemas import LineageCreateRequest, LineageUpdateRequest
from app.publications.schemas import PublishedLineage


def test_lineage_classification_defaults_and_explicit_types():
    assert LineageCreateRequest(expected_workspace_version=1, lineage_label="Old").lineage_type == "unspecified"
    for value in ("sar", "synthesis"):
        assert LineageCreateRequest(expected_workspace_version=1, lineage_label="New", lineage_type=value).lineage_type == value
        assert LineageUpdateRequest(expected_workspace_version=1, lineage_type=value).updates() == {"lineage_type": value}
        assert AiLineage(ref="route", lineage_label="Route", lineage_type=value).lineage_type == value
    assert AiLineage(ref="legacy", lineage_label="Legacy").lineage_type == "unspecified"


@pytest.mark.parametrize("value", [None, "mixed", "unknown"])
def test_invalid_classification_is_rejected(value):
    with pytest.raises(ValidationError):
        LineageUpdateRequest(expected_workspace_version=1, lineage_type=value)


def test_published_legacy_snapshot_defaults_without_losing_explicit_type():
    legacy = dict(id=uuid4(), lineage_label="Legacy", description=None, sort_order=0)
    assert PublishedLineage.model_validate(legacy).lineage_type == "unspecified"
    assert PublishedLineage.model_validate({**legacy, "lineage_type": "synthesis"}).lineage_type == "synthesis"


def test_legacy_candidate_serialization_retains_original_fingerprint():
    original = {"ref": "legacy", "lineage_label": "Legacy", "description": None, "members": [], "edges": []}
    assert AiLineage.model_validate(original).model_dump(mode="json") == original
    typed = {**original, "lineage_type": "sar"}
    assert AiLineage.model_validate(typed).model_dump(mode="json") == typed
