import json
from hashlib import sha256
import pytest
from sqlalchemy import select
from app.ai_tasks.models import AiTask
from app.ai_tasks.repair import accept_repair
from app.ai_tasks.service import TaskError, job_response
from app.ai_tasks.review_recovery import recover_saved_review
from app.ai_prefill.provenance import list_provenance
from app.workspaces.models import PaperWorkspace
from app.structures.models import Structure
from .test_repair_flow import runner, prepared_review


def failed_postflight(directory, **kwargs):
    result=runner(directory,**kwargs)
    task=json.loads((directory/'task.json').read_text())
    if task['entry']=='review':
        state=json.loads((directory/'state.json').read_text())
        state.update(status='failed',exit_code=0,failure='Synthetic old output-reader failure')
        state.pop('candidate_file_sha256',None)
        (directory/'state.json').write_text(json.dumps(state))
        provenance=json.loads((directory/'runtime-provenance.json').read_text())
        provenance.update(outcome='failed',proposal_candidate_file_sha256=None)
        (directory/'runtime-provenance.json').write_text(json.dumps(provenance))
        return {'state':state}
    return result


def setup_recovery(factory,tmp_path,monkeypatch):
    return prepared_review(factory,tmp_path,monkeypatch,review_runner=failed_postflight,expected_state='failed')


def test_saved_review_recovery_offers_real_accept_without_model_or_rewriting_history(auth_session_factory,tmp_path,monkeypatch):
    c,settings,worker,jid=setup_recovery(auth_session_factory,tmp_path,monkeypatch)
    directory=settings.ai_task_root/str(jid)/'job'
    original={str(p.relative_to(directory)):sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*.json')}
    recover_saved_review(auth_session_factory,settings,jid,actor_id=c.admin_id)
    recover_saved_review(auth_session_factory,settings,jid,actor_id=c.admin_id)
    with auth_session_factory() as s:
        job=s.get(AiTask,jid)
        assert job.state=='proposal_ready'
        assert job.error_code is None and job.error_message is None
        assert job_response(s,job)['can_accept'] is True
        assert not job.result_summary.get('repair_proposal_reason')
        assert s.get(PaperWorkspace,c.workspace_id).version==2
        digest=job.result_summary['proposal']['sha256']
    for name,digest_file in original.items():assert sha256((directory/name).read_bytes()).hexdigest()==digest_file
    accept_repair(auth_session_factory,settings,jid,actor_id=c.admin_id,proposal_sha256=digest)
    accept_repair(auth_session_factory,settings,jid,actor_id=c.admin_id,proposal_sha256=digest)
    with auth_session_factory() as s:
        assert s.get(PaperWorkspace,c.workspace_id).version==3
        assert s.scalar(select(Structure)).smiles=='CC'
        records=list_provenance(s,c.workspace_id)
        assert [r['stage'] for r in records]==['prefill','independent_review','repair']
        assert records[-1]['applied_workspace_version']==3
        assert records[-1]['candidate_file_sha256']==sha256((directory/'outputs/candidate.json').read_bytes()).hexdigest()
    assert worker.test_calls==['prefill','review']
    worker.stop()


@pytest.mark.parametrize('fault',['nonzero_exit','stale_workspace','invalid_candidate'])
def test_recovery_rejects_unfinished_stale_or_invalid_results(auth_session_factory,tmp_path,monkeypatch,fault):
    c,settings,worker,jid=setup_recovery(auth_session_factory,tmp_path,monkeypatch)
    directory=settings.ai_task_root/str(jid)/'job'
    if fault=='nonzero_exit':
        path=directory/'state.json';state=json.loads(path.read_text());state['exit_code']=1;path.write_text(json.dumps(state))
    if fault=='invalid_candidate':(directory/'outputs/candidate.json').write_text('{}')
    if fault=='stale_workspace':
        with auth_session_factory.begin() as s:s.get(PaperWorkspace,c.workspace_id).version+=1
    with pytest.raises(ValueError):recover_saved_review(auth_session_factory,settings,jid,actor_id=c.admin_id)
    with auth_session_factory() as s:
        assert s.get(AiTask,jid).state=='failed'
        assert s.scalar(select(Structure)).smiles=='C'
    worker.stop()


@pytest.mark.parametrize('fault',['receipt','audit','candidate','runtime'])
def test_recovered_accept_rechecks_attestation_and_artifacts(auth_session_factory,tmp_path,monkeypatch,fault):
    c,settings,worker,jid=setup_recovery(auth_session_factory,tmp_path,monkeypatch)
    recover_saved_review(auth_session_factory,settings,jid,actor_id=c.admin_id)
    with auth_session_factory() as s:
        job=s.get(AiTask,jid);digest=job.result_summary['proposal']['sha256'];receipt=job.config['review_revalidation']['file']
    root=settings.ai_task_root/str(jid)
    path=root/receipt if fault=='receipt' else root/'job'/dict(audit='outputs/items.json',candidate='outputs/candidate.json',runtime='runtime-provenance.json')[fault]
    path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ValueError):accept_repair(auth_session_factory,settings,jid,actor_id=c.admin_id,proposal_sha256=digest)
    with auth_session_factory() as s:
        assert s.get(PaperWorkspace,c.workspace_id).version==2
        assert s.scalar(select(Structure)).smiles=='C'
    worker.stop()
