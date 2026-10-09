import hashlib
import json
from uuid import uuid4
import pytest
from sqlalchemy import select
from app.ai_tasks.contracts import StartTask, RepairRequest
from app.ai_tasks.models import AiTask
from app.ai_tasks.service import enqueue, claim_next, TaskError
from app.ai_tasks.coordinator import AiTaskCoordinator
from app.ai_tasks.repair import enqueue_repair, accept_repair
from app.ai_tasks.execution import report_for
from app.workspaces.models import PaperWorkspace
from app.compounds.models import Compound
from app.structures.models import Structure
from .test_execution import context_and_settings, fake_runner


def runner(directory, **kwargs):
    from leadtrace.ops.ai_prefill.tasks import _postflight
    task=json.loads((directory/'task.json').read_text())
    if task['entry']=='prefill':return fake_runner(directory,**kwargs)
    base=json.loads((directory/'inputs/current-candidate.json').read_text())
    if task['entry']=='review':
        targets=json.loads((directory/'inputs/review-targets.json').read_text())
        rows=[{'domain':d,'ref':r,'verdict':'incorrect' if d=='structures' else 'uncertain','expected':'CC','observed':'C','source_locations':['p1 synthetic'], 'checked_fields':['connectivity'],'field_results':{'connectivity':'incorrect'},'reason':'Synthetic structure repair requested'} for d,refs in targets.items() for r in refs]
        (directory/'outputs/items.json').write_text(json.dumps(rows))
        report={'candidate_file_sha256':task['baseline']['candidate_file_sha256'],'source_sha256':task['source']['source_sha256'],'complete_scope':True,'unreviewed_scope':[],'scientific_approval':False,'item_reports':['items.json']}
        (directory/'outputs/audit-summary.json').write_text(json.dumps(report))
    if task['entry'] != 'review' or task.get('review_with_repair'):
        base.update(candidate_id=task['candidate_id'],experiment_id=task['experiment_id'],parent_candidate_id=task['baseline']['candidate_id'],recipe={'guide_version':task['guide_version']})
        base.pop('hashes',None)
        base['payload']['compounds'][0]['structure']={'smiles':'CC'}
        raw=json.dumps(base).encode();(directory/'outputs/candidate.json').write_bytes(raw)
        (directory/'outputs/compound-inventory.json').write_bytes((directory/'inputs/compound-inventory.json').read_bytes())
        checks=['compound_scope','measurement_coverage','activity_semantics','structure_identity','source_crops','sar_reasoning','synthesis_paths']
        review={'self_review_version':1,'candidate_file_sha256':hashlib.sha256(raw).hexdigest(),'reviewer_type':'producer_self_check','checks':[{'check_id':key,'status':'checked','details':'synthetic','source_locations':['p1']} for key in checks]}
        (directory/'outputs/self-review.json').write_text(json.dumps(review))
    status,details=_postflight(directory,task)
    provenance={'requested':task['runtime'],'observed':[],'verification':'requested_only','stage':task['entry'],'task_id':task['task_id'],'source_sha256':task['source']['source_sha256'],'candidate_file_sha256':task['baseline']['candidate_file_sha256'] if task['entry']=='review' else details.get('candidate_file_sha256'), 'proposal_candidate_file_sha256':details.get('candidate_file_sha256') if task['entry']=='review' else None,'guide_version':task['guide_version'],'guide_bundle_sha256':hashlib.sha256((directory/'bundle-manifest.json').read_bytes()).hexdigest(),'completed_at':'2026-10-09T00:00:00Z','outcome':status}
    (directory/'runtime-provenance.json').write_text(json.dumps(provenance))
    state={'status':status,**details,'process_cleanup_confirmed':True}
    path=directory/'state.json';saved=json.loads(path.read_text());saved.update(state);path.write_text(json.dumps(saved))
    return {'state':state}


def prepared_review(factory,tmp_path,monkeypatch,*,review_runner=runner,expected_state="proposal_ready"):
    calls=[]
    def counted(directory,**kwargs):
        calls.append(json.loads((directory/"task.json").read_text())["entry"])
        return review_runner(directory,**kwargs)
    c,settings=context_and_settings(factory,tmp_path,monkeypatch)
    worker=AiTaskCoordinator(factory,settings,runner=counted)
    worker.test_calls=calls
    with factory.begin() as s:
        job=enqueue(s,settings,paper_id=c.paper_id,actor_id=c.admin_id,request=StartTask(action='prefill',preset_id='test',reasoning_effort='high',expected_workspace_id=c.workspace_id,expected_task_version=1,expected_workspace_version=1,idempotency_key=uuid4(),auto_review={'preset_id':'test','reasoning_effort':'high'}));jid=job.id;claim_next(s,owner=worker.owner)
    worker.execute(jid)
    with factory.begin() as s:rid=claim_next(s,owner=worker.owner)
    assert rid
    worker.execute(rid)
    with factory() as s:
        j=s.get(AiTask,rid);assert j.state==expected_state,(j.error_code,j.error_message,j.result_summary.get('repair_proposal_errors'))
    assert calls==['prefill','review']
    return c,settings,worker,rid


def test_repair_proposal_is_explicit_then_accepted_once(auth_session_factory,tmp_path,monkeypatch):
    c,settings,worker,rid=prepared_review(auth_session_factory,tmp_path,monkeypatch)
    jid=rid
    with auth_session_factory() as s:
        job=s.get(AiTask,jid);assert job.state=='proposal_ready',(job.error_code,job.error_message)
        report=report_for(settings,job);digest=report['proposal']['sha256'];assert report['proposal']['total_changes']>0
        assert s.get(PaperWorkspace,c.workspace_id).version==2
        compound=s.scalar(select(Compound));cid=compound.id
        assert s.scalar(select(Structure)).smiles=='C'
    accept_repair(auth_session_factory,settings,jid,actor_id=c.admin_id,proposal_sha256=digest)
    accept_repair(auth_session_factory,settings,jid,actor_id=c.admin_id,proposal_sha256=digest)
    with auth_session_factory() as s:
        assert s.get(PaperWorkspace,c.workspace_id).version==3
        assert s.scalar(select(Compound)).id==cid
        assert s.scalar(select(Structure)).smiles=='CC'
        assert s.get(AiTask,jid).delivery_state=='applied'
        assert s.get(AiTask,jid).result_summary['scientific_approval'] is False
        assert len(list(s.scalars(select(AiTask))))==2
    assert worker.test_calls==['prefill','review']
    from app.ai_prefill.provenance import list_provenance
    with auth_session_factory() as s:
        records=list_provenance(s,c.workspace_id)
        assert [r['stage'] for r in records]==['prefill','independent_review','repair']
        assert records[1]['candidate_file_sha256']!=records[2]['candidate_file_sha256']
        assert records[1]['applied_workspace_version'] is None
        assert records[2]['applied_workspace_version']==3
    worker.stop()


@pytest.mark.parametrize('change',['version','candidate','proposal_hash'])
def test_accept_refuses_stale_or_tampered_proposal(auth_session_factory,tmp_path,monkeypatch,change):
    c,settings,worker,rid=prepared_review(auth_session_factory,tmp_path,monkeypatch)
    jid=rid
    with auth_session_factory.begin() as s:
        job=s.get(AiTask,jid);assert job.state=='proposal_ready',(job.error_code,job.error_message)
        digest=job.result_summary['proposal']['sha256']
        if change=='version':s.get(PaperWorkspace,c.workspace_id).version+=1
    if change=='candidate':
        p=settings.ai_task_root/str(jid)/'job/outputs/candidate.json';p.write_bytes(p.read_bytes()+b' ')
    if change=='proposal_hash':digest='0'*64
    with pytest.raises((TaskError,ValueError)):
        accept_repair(auth_session_factory,settings,jid,actor_id=c.admin_id,proposal_sha256=digest)
    with auth_session_factory() as s:assert s.scalar(select(Structure)).smiles=='C'
    worker.stop()


@pytest.mark.parametrize('variant',['missing','invalid','no_changes','timed_out','failed'])
def test_audit_survives_unavailable_or_no_change_proposal(auth_session_factory,tmp_path,monkeypatch,variant):
    def changed_runner(directory,**kwargs):
        result=runner(directory,**kwargs)
        task=json.loads((directory/'task.json').read_text())
        if task['entry']!='review':return result
        candidate=directory/'outputs/candidate.json'
        if variant=='invalid':candidate.write_text('{}')
        else:candidate.unlink()
        if variant=='no_changes':
            (directory/'outputs/repair-outcome.json').write_text(json.dumps({'status':'no_changes','reason':'No source-supported correction; uncertainties retained.'}))
        from leadtrace.ops.ai_prefill.tasks import _postflight
        status,details=_postflight(directory,task)
        if variant in {'timed_out','failed'}:status=variant
        state={'status':status,**details,'process_cleanup_confirmed':True}
        saved=json.loads((directory/'state.json').read_text());saved.update(state)
        (directory/'state.json').write_text(json.dumps(saved))
        return {'state':state}
    c,settings,worker,rid=prepared_review(auth_session_factory,tmp_path,monkeypatch,review_runner=changed_runner,
        expected_state='needs_revision' if variant=='no_changes' else variant if variant in {'timed_out','failed'} else 'partial')
    with auth_session_factory() as s:
        job=s.get(AiTask,rid);report=report_for(settings,job)
        assert report['findings_total']>0
        assert report['proposal'] is None
        assert report['repair_proposal_status']==('no_changes' if variant=='no_changes' else 'unavailable')
        assert s.get(PaperWorkspace,c.workspace_id).version==2
        assert s.scalar(select(Structure)).smiles=='C'
        assert len(list(s.scalars(select(AiTask))))==2
    worker.stop()


def test_separate_repair_launch_is_disabled(auth_session_factory,tmp_path,monkeypatch):
    c,settings,worker,rid=prepared_review(auth_session_factory,tmp_path,monkeypatch)
    with auth_session_factory.begin() as s:
        with pytest.raises(TaskError) as error:
            enqueue_repair(s,settings,review_id=rid,actor_id=c.admin_id,request=RepairRequest(preset_id='test',reasoning_effort='high',idempotency_key=uuid4()))
        assert error.value.code=='REPAIR_MERGED_IN_REVIEW'
    assert worker.test_calls==['prefill','review']
    worker.stop()
