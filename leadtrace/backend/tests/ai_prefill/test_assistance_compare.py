from datetime import UTC, datetime

import pytest

from app.ai_prefill.assistance_compare import compare_candidates
from app.ai_prefill.assistance_contracts import (
    CandidateEnvelope,
    CandidateRecipe,
    ProducerProvenance,
    SourceIdentity,
)
from app.ai_prefill.contracts import AiPrefillPayload


def candidate(payload: AiPrefillPayload, *, candidate_id: str) -> CandidateEnvelope:
    return CandidateEnvelope(
        envelope_version=1,
        candidate_id=candidate_id,
        experiment_id="experiment:test",
        source=SourceIdentity(paper_key="paper-1", source_sha256="a" * 64, byte_size=10, page_count=2),
        producer=ProducerProvenance(kind="local", engine="test", engine_version="1", generated_at=datetime(2026, 1, 1, tzinfo=UTC)),
        recipe=CandidateRecipe(guide_version="guide-v1"),
        payload=payload,
    )


def test_compare_reports_duplicate_activity_keys_as_ambiguous() -> None:
    payload = AiPrefillPayload.model_validate(
        {
            "schema_version": 1,
            "compounds": [{"ref": "c1", "compound_label": "1", "structure": {"smiles": "CCO"}}],
            "activities": [
                {"compound_ref": "c1", "assay_name": "binding", "metric": "IC50", "operator": "=", "value": "1"},
                {"compound_ref": "c1", "assay_name": "binding", "metric": "IC50", "operator": "=", "value": "2"},
            ],
        }
    )

    result = compare_candidates(candidate(payload, candidate_id="candidate:v1"), candidate(payload, candidate_id="candidate:v2"))

    assert result["sections"]["activities"]["ambiguous"] == ["c1"]


def test_compare_requires_same_source_identity() -> None:
    first = candidate(AiPrefillPayload.model_validate({"schema_version": 1}), candidate_id="candidate:v1")
    second = first.model_copy(update={"source": first.source.model_copy(update={"source_sha256": "b" * 64})})

    with pytest.raises(ValueError, match="same source"):
        compare_candidates(first, second)
