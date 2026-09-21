from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.ai_prefill.assistance_contracts import CandidateEnvelope, CandidateRecipe, ProducerProvenance, SourceIdentity, canonical_payload_bytes, computed_hashes, with_computed_hashes
from app.ai_prefill.contracts import AiPrefillPayload


def payload() -> AiPrefillPayload:
    return AiPrefillPayload.model_validate({"schema_version": 1, "compounds": [{"ref": "c1", "compound_label": "1", "structure": {"smiles": "CCO"}}]})


def candidate(source_hash: str = "a" * 64) -> CandidateEnvelope:
    return CandidateEnvelope(
        envelope_version=1, candidate_id="candidate:v1", experiment_id="experiment:test",
        source=SourceIdentity(paper_key="paper-1", source_sha256=source_hash, byte_size=10, page_count=2),
        producer=ProducerProvenance(kind="local", engine="test", engine_version="1", generated_at=datetime(2026, 1, 1, tzinfo=UTC)),
        recipe=CandidateRecipe(guide_version="guide-v1"), payload=payload(),
    )


def test_hashes_are_deterministic_and_source_bound() -> None:
    first = computed_hashes(candidate())
    second = computed_hashes(candidate("b" * 64))
    assert first.payload_sha256 == second.payload_sha256
    assert first.candidate_sha256 != second.candidate_sha256
    assert canonical_payload_bytes(payload()) == canonical_payload_bytes(payload())


def test_hashes_are_computed_by_receiver() -> None:
    stored = with_computed_hashes(candidate())
    assert stored.hashes == computed_hashes(candidate())


def test_database_uuid_is_not_part_of_portable_identity() -> None:
    assert "paper_key" in candidate().source.model_dump()
    assert "paper_id" not in candidate().model_dump()


@pytest.mark.parametrize("value", ["../escape", "/absolute", "bad space"])
def test_candidate_ids_reject_path_values(value: str) -> None:
    with pytest.raises(ValidationError):
        CandidateEnvelope.model_validate({**candidate().model_dump(), "candidate_id": value})
