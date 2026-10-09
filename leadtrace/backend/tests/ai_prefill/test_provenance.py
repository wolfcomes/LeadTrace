import pytest
from pydantic import ValidationError


def test_provenance_requires_bound_observations_and_rejects_secrets():
    from app.ai_prefill.provenance import ProvenanceInput
    base=dict(run_key='synthetic-run', stage='prefill', source_sha256='a'*64,
              candidate_file_sha256='b'*64, model='gpt-test', reasoning_effort='high',
              adapter='codex', verification='requested_only', outcome='needs_revision')
    assert ProvenanceInput(**base).verification=='requested_only'
    with pytest.raises(ValidationError):ProvenanceInput(**{**base,'verification':'request_observed'})
    with pytest.raises(ValidationError):ProvenanceInput(**base,api_key='never-store')
    with pytest.raises(ValidationError):ProvenanceInput(**base,evidence_sha256='bad')
    with pytest.raises(ValidationError):ProvenanceInput(**{**base,'model':'https://secret@example.test'})
    assert ProvenanceInput(**{**base,'model':None,'reasoning_effort':None,'verification':'unknown'}).model is None


def test_append_is_idempotent_bound_and_preserves_science(auth_session_factory):
    from .test_apply import create_ai_context
    from app.ai_prefill.provenance import ProvenanceInput, append_provenance, list_provenance
    from app.workspaces.models import PaperWorkspace
    from app.workspaces.snapshot import build_paper_snapshot
    context=create_ai_context(auth_session_factory)
    record=ProvenanceInput(run_key='run-1',stage='prefill',source_sha256='a'*64,candidate_file_sha256='b'*64,
                           model='deepseek-flash',reasoning_effort='max',verification='requested_only',applied_workspace_version=1)
    with context.session_factory.begin() as session:
        workspace=session.get(PaperWorkspace,context.workspace_id)
        before=build_paper_snapshot(session,workspace.id)
        assert append_provenance(session,workspace=workspace,source_sha256='a'*64,actor_id=context.admin_id,record=record)
        assert not append_provenance(session,workspace=workspace,source_sha256='a'*64,actor_id=context.admin_id,record=record)
        assert len(list_provenance(session,workspace.id))==1
        after=build_paper_snapshot(session,workspace.id)
        assert len(after.pop('ai_provenance'))==1
        before.pop('ai_provenance',None)
        assert before==after and workspace.version==1
        with pytest.raises(ValueError,match='source'):
            append_provenance(session,workspace=workspace,source_sha256='c'*64,actor_id=context.admin_id,record=record)
        with pytest.raises(ValueError,match='different'):
            append_provenance(session,workspace=workspace,source_sha256='a'*64,actor_id=context.admin_id,record=record.model_copy(update={'model':'other'}))
