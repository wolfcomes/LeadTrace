from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.ai_prefill.assistance_contracts import (
    CandidateEnvelope,
    CandidateRecipe,
    ProducerProvenance,
    SourceIdentity,
)
from app.ai_prefill.assistance_inputs import (
    PrefillInputPackage,
    input_package_sha256,
    load_candidate,
    prepare_input_package,
)
from app.ai_prefill.contracts import AiPrefillPayload


def source() -> SourceIdentity:
    return SourceIdentity(
        paper_key="paper-1",
        source_sha256="a" * 64,
        byte_size=100,
        page_count=4,
    )


def test_input_package_keeps_local_path_only_in_authorized_locator(tmp_path: Path) -> None:
    source_path = tmp_path / "paper.pdf"
    source_path.write_bytes(b"pdf")

    package = prepare_input_package(
        experiment_id="experiment:test",
        source=source(),
        guide_version="guide-v1",
        source_path=source_path,
        input_evaluation_ids=["evaluation:v1"],
    )

    assert package.source_locator.path == str(source_path.resolve())
    public = package.model_dump(mode="json")
    assert public["target"]["paper_key"] == "paper-1"
    assert public["input_evaluation_ids"] == ["evaluation:v1"]
    assert input_package_sha256(package) == input_package_sha256(package.model_copy(deep=True))


def test_load_candidate_uses_the_same_envelope_parser(tmp_path: Path) -> None:
    candidate = CandidateEnvelope(
        envelope_version=1,
        candidate_id="candidate:v1",
        experiment_id="experiment:test",
        source=source(),
        producer=ProducerProvenance(
            kind="local",
            engine="test",
            engine_version="1",
            generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        recipe=CandidateRecipe(guide_version="guide-v1"),
        payload=AiPrefillPayload(schema_version=1),
    )
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(candidate.model_dump(mode="json")), encoding="utf-8")

    loaded = load_candidate(path)

    assert loaded == candidate


def test_input_package_rejects_locator_for_a_different_source() -> None:
    package = prepare_input_package(
        experiment_id="experiment:test",
        source=source(),
        guide_version="guide-v1",
    )

    with pytest.raises(ValidationError):
        PrefillInputPackage.model_validate(
            {
                **package.model_dump(),
                "source_locator": {
                    **package.source_locator.model_dump(),
                    "source_sha256": "b" * 64,
                },
            }
        )
