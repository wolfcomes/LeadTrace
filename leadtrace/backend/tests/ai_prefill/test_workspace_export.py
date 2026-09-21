from datetime import UTC, datetime

import pytest

from app.ai_prefill.assistance_contracts import (
    CandidateEnvelope,
    CandidateRecipe,
    ProducerProvenance,
    SourceIdentity,
    with_computed_hashes,
)
from app.ai_prefill.contracts import AiPrefillPayload
from app.ai_prefill.workspace_export import (
    WorkspaceExportConflictError,
    export_candidate_revision,
)


def original() -> CandidateEnvelope:
    return with_computed_hashes(
        CandidateEnvelope(
            envelope_version=1,
            candidate_id="candidate:v1",
            experiment_id="experiment:test",
            source=SourceIdentity(paper_key="paper-1", source_sha256="a" * 64, byte_size=10, page_count=2),
            producer=ProducerProvenance(kind="local", engine="test", engine_version="1", generated_at=datetime(2026, 1, 1, tzinfo=UTC)),
            recipe=CandidateRecipe(guide_version="guide-v1"),
            payload=AiPrefillPayload.model_validate({"schema_version": 1}),
        )
    )


def test_export_candidate_creates_human_assisted_child_without_mutating_parent() -> None:
    parent = original()

    child = export_candidate_revision(
        parent,
        payload=AiPrefillPayload.model_validate({"schema_version": 1, "bibliography": {"title": "edited"}}),
        candidate_id="candidate:v2",
        evaluation_id="evaluation:1",
        reviewer="reviewer@example.test",
    )

    assert child.parent_candidate_id == parent.candidate_id
    assert child.producer.kind == "human-assisted"
    assert child.payload.bibliography.title == "edited"
    assert child.hashes is not None
    assert parent.candidate_id == "candidate:v1"


def test_export_candidate_rejects_concurrent_workspace_version() -> None:
    with pytest.raises(WorkspaceExportConflictError, match="version"):
        export_candidate_revision(
            original(),
            payload=AiPrefillPayload.model_validate({"schema_version": 1}),
            candidate_id="candidate:v2",
            evaluation_id="evaluation:1",
            reviewer="reviewer@example.test",
            expected_workspace_version=2,
            current_workspace_version=3,
        )
