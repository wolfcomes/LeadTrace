"""Convert checked local run metadata to a safe operator attestation (no DB access)."""
from hashlib import sha256
import json
from pathlib import Path
from app.ai_prefill.assistance_contracts import CandidateEnvelope
from app.ai_prefill.provenance import ProvenanceInput


def export_run_provenance(directory: Path, candidate_path: Path, *, applied_workspace_version: int | None = None, proposal: bool = False) -> dict:
    from leadtrace.ops.ai_prefill.tasks import _verify_bundle
    state = _verify_bundle(directory)
    raw = (directory / 'runtime-provenance.json').read_bytes()
    run = json.loads(raw)
    candidate_bytes = candidate_path.read_bytes()
    candidate = CandidateEnvelope.model_validate_json(candidate_bytes)
    binding = run.get('proposal_candidate_file_sha256') if proposal else run['candidate_file_sha256']
    if proposal:
        task=json.loads((directory/'task.json').read_text())
        if (run['stage']!='review' or not task.get('review_with_repair')
            or binding!=state.get('candidate_file_sha256')
            or run['candidate_file_sha256']!=task['baseline']['candidate_file_sha256']
            or candidate.parent_candidate_id!=task['baseline']['candidate_id']):
            raise ValueError('Combined review proposal provenance does not match frozen baseline/output')
    if sha256(candidate_bytes).hexdigest() != binding or candidate.source.source_sha256 != run['source_sha256']:
        raise ValueError('Run provenance does not match candidate/source bytes')
    requested = run['requested']
    observations = run.get('observed', [])
    observed = observations[0] if len(observations) == 1 else {}
    status = run['outcome']
    stage = 'repair' if proposal else {'prefill': 'prefill', 'selfcheck': 'repair', 'review': 'independent_review'}[run['stage']]
    outcome = {'ready_for_independent_review': 'completed', 'review_complete': 'completed',
               'needs_revision': 'needs_revision', 'partial': 'partial'}.get(status, 'failed')
    if applied_workspace_version is not None and outcome == 'failed':
        raise ValueError('A failed or mismatched run cannot be attested as applied')
    # Multiple observed models remain a mismatch; never choose one silently.
    verification = run['verification']
    if len(observations) > 1:
        raise ValueError('Multiple observed configurations require an explicit operator investigation')
    record = ProvenanceInput(
        run_key='task:' + run['task_id'] + (':repair' if proposal else ''), stage=stage, adapter=requested['adapter'],
        model=requested.get('model'), reasoning_effort=requested.get('reasoning_effort'),
        observed_model=observed.get('model'),
        observed_reasoning_effort='none' if observed.get('thinking') == 'disabled' else observed.get('reasoning_effort'),
        verification=verification, evidence_sha256=sha256(raw).hexdigest(),
        source_sha256=run['source_sha256'], candidate_file_sha256=binding,
        guide_version=run['guide_version'], guide_bundle_sha256=run['guide_bundle_sha256'],
        completed_at=run['completed_at'], outcome=outcome,
        applied_workspace_version=applied_workspace_version)
    return record.model_dump(mode='json')
