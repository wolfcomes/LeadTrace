from datetime import UTC, datetime

import pytest

from app.ai_prefill.artifact_store import ArtifactConflictError, ArtifactStore
from app.ai_prefill.assistance_contracts import CandidateEnvelope, CandidateRecipe, ProducerProvenance, SourceIdentity, computed_hashes
from app.ai_prefill.contracts import AiPrefillPayload


def make_candidate() -> CandidateEnvelope:
    return CandidateEnvelope(
        envelope_version=1, candidate_id="candidate:v1", experiment_id="experiment:test",
        source=SourceIdentity(paper_key="paper-1", source_sha256="a" * 64, byte_size=1, page_count=1),
        producer=ProducerProvenance(kind="local", engine="test", engine_version="1", generated_at=datetime(2026, 1, 1, tzinfo=UTC)),
        recipe=CandidateRecipe(guide_version="guide-v1"), payload=AiPrefillPayload(schema_version=1),
    )


def test_candidate_write_is_idempotent_but_immutable(tmp_path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    candidate = make_candidate()
    stored = store.put_candidate(candidate)
    assert stored.hashes == computed_hashes(candidate)
    assert store.put_candidate(stored).hashes == stored.hashes
    changed = stored.model_copy(update={"hashes": None, "producer": stored.producer.model_copy(update={"engine_version": "2"})})
    with pytest.raises(ArtifactConflictError):
        store.put_candidate(changed)


def test_read_rejects_symlink(tmp_path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    store.put_candidate(make_candidate())
    path = tmp_path / "artifacts" / "experiments" / "experiment:test" / "candidates" / "candidate:v1" / "candidate.json"
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(Exception):
        store.read_json(path)


def test_write_rejects_symlinked_artifact_directories(tmp_path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    outside = tmp_path / "outside"
    outside.mkdir()
    experiments = tmp_path / "artifacts" / "experiments"
    experiments.symlink_to(outside, target_is_directory=True)

    with pytest.raises(Exception):
        store.put_candidate(make_candidate())

    assert list(outside.rglob("*")) == []
