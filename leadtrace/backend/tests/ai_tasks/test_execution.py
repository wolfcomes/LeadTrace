import hashlib,json,sys
from pathlib import Path
from uuid import uuid4
import pytest
from sqlalchemy import select
from app.config import Settings
from app.ai_tasks.models import AiTask
from app.ai_tasks.contracts import StartTask
from app.ai_tasks.service import enqueue,claim_next,TaskError,cancel_job
from app.ai_tasks.coordinator import AiTaskCoordinator
from app.workspaces.models import PaperWorkspace,ReviewTask
from tests.ai_prefill.test_apply import create_ai_context


def context_and_settings(factory,tmp_path,monkeypatch):
    from app.papers.models import Paper
    from app.catalog.models import PaperSource
    from app.assets.models import Asset
    c=create_ai_context(factory)
    root=tmp_path/'sources';path=root/'volume67 issue5/ai-paper.pdf';path.parent.mkdir(parents=True)
    import pymupdf
    pdf=pymupdf.open();pdf.new_page();path.write_bytes(pdf.tobytes());pdf.close()
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    with factory.begin() as s:
        source=s.get(PaperSource,s.get(Paper,c.paper_id).source_id);asset=s.get(Asset,source.asset_id)
        source.sha256=asset.sha256=digest;source.byte_size=asset.byte_size=path.stat().st_size;source.page_count=asset.page_count=1
    monkeypatch.setattr('app.ai_tasks.service.shutil.which',lambda _: '/bin/synthetic-runner')
    settings=Settings(_env_file=None,ai_task_worker_enabled=True,ai_task_root=tmp_path/'jobs',asset_root=tmp_path/'assets',source_roots={'source_pdfs':root},ai_task_python=Path(sys.executable),ai_task_presets=[{'id':'test','label':'Synthetic','adapter':'codex','model':'gpt-test','efforts':['high'],'default_effort':'high'}])
    return c,settings


def fake_runner(directory,**kwargs):
    from leadtrace.ops.ai_prefill.tasks import _postflight
    from leadtrace.ops.ai_prefill.runtime import RuntimeConfig
    task=json.loads((directory/'task.json').read_text())
    if task['entry']=='prefill':
        c={'envelope_version':1,'candidate_id':task['candidate_id'],'experiment_id':task['experiment_id'],'source':task['source'],
           'producer':{'kind':'local','engine':'synthetic','engine_version':'test','generated_at':'2026-10-08T00:00:00Z'},'recipe':{'guide_version':task['guide_version']},
           'payload':{'schema_version':1,'compounds':[{'ref':'c1','compound_label':'1','structure':{'smiles':'C'}}]}}
        raw=json.dumps(c).encode();(directory/'outputs/candidate.json').write_bytes(raw)
        inv={'inventory_version':1,'source':task['source'],'scope':'synthetic','reviewed_by':'synthetic','entries':[{'label':'1','role':'test','required':True,'source_locator':'p1'}]}
        (directory/'outputs/compound-inventory.json').write_text(json.dumps(inv))
        checks=['compound_scope','measurement_coverage','activity_semantics','structure_identity','source_crops','sar_reasoning','synthesis_paths']
        review={'self_review_version':1,'candidate_file_sha256':hashlib.sha256(raw).hexdigest(),'reviewer_type':'producer_self_check','checks':[{'check_id':key,'status':'checked','details':'synthetic','source_locations':['p1']} for key in checks]}
        (directory/'outputs/self-review.json').write_text(json.dumps(review))
    else:
        report={'candidate_file_sha256':task['baseline']['candidate_file_sha256'],'source_sha256':task['source']['source_sha256'],'complete_scope':False,'unreviewed_scope':['synthetic partial'],'scientific_approval':False,'item_reports':[]}
        (directory/'outputs/audit-summary.json').write_text(json.dumps(report))
    status,details=_postflight(directory,task)
    provenance={'requested':task['runtime'],'observed':[],'verification':'requested_only','stage':task['entry'],'task_id':task['task_id'],'source_sha256':task['source']['source_sha256'],'candidate_file_sha256':details.get('candidate_file_sha256') or task['baseline']['candidate_file_sha256'],'guide_version':task['guide_version'],'guide_bundle_sha256':hashlib.sha256((directory/'bundle-manifest.json').read_bytes()).hexdigest(),'completed_at':'2026-10-08T00:00:00Z','outcome':status}
    (directory/'runtime-provenance.json').write_text(json.dumps(provenance))
    return {'state':{'status':status,**details}}


def test_generation_applies_and_fresh_review_uses_saved_draft(auth_session_factory,tmp_path,monkeypatch):
    c,settings=context_and_settings(auth_session_factory,tmp_path,monkeypatch)
    request=StartTask(action='prefill',preset_id='test',reasoning_effort='high',expected_workspace_id=c.workspace_id,expected_task_version=1,expected_workspace_version=1,idempotency_key=uuid4(),auto_review={'preset_id':'test','reasoning_effort':'high'})
    worker=AiTaskCoordinator(auth_session_factory,settings,runner=fake_runner)
    with auth_session_factory.begin() as s:
        job=enqueue(s,settings,paper_id=c.paper_id,actor_id=c.admin_id,request=request);identifier=job.id
        assert enqueue(s,settings,paper_id=c.paper_id,actor_id=c.admin_id,request=request).id==identifier
        assert claim_next(s,owner=worker.owner)==identifier
    worker.execute(identifier)
    with auth_session_factory.begin() as s:
        job=s.get(AiTask,identifier)
        assert job.state=='completed', (job.error_code,job.error_message)
        assert job.delivery_state=='applied'
        assert s.get(PaperWorkspace,c.workspace_id).version==2
        child=s.scalar(select(AiTask).where(AiTask.parent_job_id==identifier))
        assert child.action=='review'
        child_id=claim_next(s,owner=worker.owner)
    worker.execute(child_id)
    with auth_session_factory() as s:
        assert s.get(AiTask,child_id).state=='partial'
        assert s.get(PaperWorkspace,c.workspace_id).version==2
    original=json.loads((settings.ai_task_root/str(identifier)/'job/outputs/candidate.json').read_text())
    reviewed=json.loads((settings.ai_task_root/str(child_id)/'job/inputs/current-candidate.json').read_text())
    assert reviewed['candidate_id']!=original['candidate_id']
    assert reviewed['payload']['compounds'][0]['structure']['smiles']=='C'
    worker.stop()


def test_stale_workspace_is_rejected_before_model_call(auth_session_factory,tmp_path,monkeypatch):
    c,settings=context_and_settings(auth_session_factory,tmp_path,monkeypatch)
    invoked=[]
    worker=AiTaskCoordinator(auth_session_factory,settings,runner=lambda *a,**kw:invoked.append(True))
    with auth_session_factory.begin() as s:
        job=enqueue(s,settings,paper_id=c.paper_id,actor_id=c.admin_id,request=StartTask(action='prefill',preset_id='test',reasoning_effort='high',expected_workspace_id=c.workspace_id,expected_task_version=1,expected_workspace_version=1,idempotency_key=uuid4()))
        identifier=job.id;claim_next(s,owner=worker.owner)
        s.get(PaperWorkspace,c.workspace_id).version=2
    worker.execute(identifier)
    with auth_session_factory() as s:assert s.get(AiTask,identifier).error_code=='WORKSPACE_CHANGED'
    assert invoked==[]
    worker.stop()


def test_enqueue_same_paper_and_invalid_configuration_are_rejected(auth_session_factory,tmp_path,monkeypatch):
    c,settings=context_and_settings(auth_session_factory,tmp_path,monkeypatch)
    req=StartTask(action='prefill',preset_id='test',reasoning_effort='high',expected_workspace_id=c.workspace_id,expected_task_version=1,expected_workspace_version=1,idempotency_key=uuid4())
    with auth_session_factory.begin() as s:
        enqueue(s,settings,paper_id=c.paper_id,actor_id=c.admin_id,request=req)
        with pytest.raises(TaskError,match='already'):enqueue(s,settings,paper_id=c.paper_id,actor_id=c.admin_id,request=req.model_copy(update={'idempotency_key':uuid4()}))
        with pytest.raises(TaskError,match='different'):enqueue(s,settings,paper_id=c.paper_id,actor_id=c.admin_id,request=req.model_copy(update={'reasoning_effort':'invalid'}))


def test_cancellation_and_human_edit_during_generation_never_overwrite(auth_session_factory,tmp_path,monkeypatch):
    c,settings=context_and_settings(auth_session_factory,tmp_path,monkeypatch)
    def runner(directory,**kwargs):
        result=fake_runner(directory,**kwargs)
        with auth_session_factory.begin() as s:
            cancel_job(s,s.get(AiTask,identifier))
            s.get(PaperWorkspace,c.workspace_id).version=2
        return result
    worker=AiTaskCoordinator(auth_session_factory,settings,runner=runner)
    with auth_session_factory.begin() as s:
        identifier=enqueue(s,settings,paper_id=c.paper_id,actor_id=c.admin_id,request=StartTask(action='prefill',preset_id='test',reasoning_effort='high',expected_workspace_id=c.workspace_id,expected_task_version=1,expected_workspace_version=1,idempotency_key=uuid4())).id
        claim_next(s,owner=worker.owner)
    worker.execute(identifier)
    with auth_session_factory() as s:
        assert s.get(AiTask,identifier).state=='cancelled'
        assert s.get(PaperWorkspace,c.workspace_id).version==2
        from app.compounds.models import Compound
        assert not s.scalar(select(Compound).where(Compound.workspace_id==c.workspace_id))
    assert not (settings.ai_task_root/str(identifier)/'delivery.json').exists()
    worker.stop()


def test_receipt_write_failure_does_not_undo_committed_apply(auth_session_factory,tmp_path,monkeypatch):
    from app.ai_tasks import execution
    c,settings=context_and_settings(auth_session_factory,tmp_path,monkeypatch)
    real_save=execution.save_json
    def save(path,value):
        if path.name=='delivery.json':
            with auth_session_factory() as s:
                assert s.get(AiTask,identifier).delivery_state=='applied'
                assert s.get(PaperWorkspace,c.workspace_id).version==2
            raise OSError('synthetic disk full')
        return real_save(path,value)
    monkeypatch.setattr(execution,'save_json',save)
    worker=AiTaskCoordinator(auth_session_factory,settings,runner=fake_runner)
    with auth_session_factory.begin() as s:
        identifier=enqueue(s,settings,paper_id=c.paper_id,actor_id=c.admin_id,request=StartTask(action='prefill',preset_id='test',reasoning_effort='high',expected_workspace_id=c.workspace_id,expected_task_version=1,expected_workspace_version=1,idempotency_key=uuid4())).id
        claim_next(s,owner=worker.owner)
    worker.execute(identifier)
    with auth_session_factory() as s:
        job=s.get(AiTask,identifier)
        assert job.state=='completed'
        assert job.result_summary['delivery_sidecar_unavailable']
    execution.deliver_result(auth_session_factory,settings,identifier,{'status':'failed'})
    with auth_session_factory() as s:assert s.get(AiTask,identifier).state=='completed'
    worker.stop()


def test_old_generation_cannot_enqueue_after_archive_reset(auth_session_factory,tmp_path,monkeypatch):
    from app.workspaces.lifecycle import archive_reset,LifecycleConflict
    c,settings=context_and_settings(auth_session_factory,tmp_path,monkeypatch)
    req=StartTask(action='prefill',preset_id='test',reasoning_effort='high',expected_workspace_id=c.workspace_id,expected_task_version=1,expected_workspace_version=1,idempotency_key=uuid4())
    with auth_session_factory.begin() as s:
        job=enqueue(s,settings,paper_id=c.paper_id,actor_id=c.admin_id,request=req)
        cancel_job(s,job)
        kwargs=dict(paper_id=c.paper_id,admin_id=c.admin_id,expected_workspace_id=c.workspace_id,expected_workspace_version=1,expected_task_version=1,confirm_paper_key='LT-JMC-2024-67-05-AI1',archive_root=tmp_path/'archives',asset_root=settings.asset_root,task_root=settings.ai_task_root)
        new,_=archive_reset(s,**kwargs)
        assert new.version==1 and new.id!=c.workspace_id
        with pytest.raises(TaskError,match='changed'):
            enqueue(s,settings,paper_id=c.paper_id,actor_id=c.admin_id,request=req.model_copy(update={'idempotency_key':uuid4()}),parent_job=job)
        with pytest.raises(LifecycleConflict,match='changed'):archive_reset(s,**kwargs)


def test_preview_identity_drift_blocks_delivery(auth_session_factory,tmp_path,monkeypatch):
    c,settings=context_and_settings(auth_session_factory,tmp_path,monkeypatch)
    settings.environment='preview';verified=[]
    def verify(*args):
        verified.append(True)
        if len(verified)>1:raise ValueError('synthetic preview identity drift')
    monkeypatch.setattr('app.ai_prefill.preview_identity.verify_preview_connection',verify)
    worker=AiTaskCoordinator(auth_session_factory,settings,runner=fake_runner)
    with auth_session_factory.begin() as s:
        identifier=enqueue(s,settings,paper_id=c.paper_id,actor_id=c.admin_id,request=StartTask(action='prefill',preset_id='test',reasoning_effort='high',expected_workspace_id=c.workspace_id,expected_task_version=1,expected_workspace_version=1,idempotency_key=uuid4())).id
        claim_next(s,owner=worker.owner)
    worker.execute(identifier)
    with auth_session_factory() as s:
        assert s.get(AiTask,identifier).state=='failed'
        assert s.get(PaperWorkspace,c.workspace_id).version==1
    assert len(verified)==2
    worker.stop()


def draft_runner(directory, *, missing_review=False, wrong_inventory=False, **kwargs):
    """Valid synthetic draft with an unresolved identity and honest self-review."""
    from leadtrace.ops.ai_prefill.tasks import _postflight
    fake_runner(directory,**kwargs)
    inv_path=directory/'outputs/compound-inventory.json'
    inv=json.loads(inv_path.read_text())
    inv['entries'].append({'label':'unknown-metabolite','role':'unresolved identity','required':True,'source_locator':'p1'})
    if wrong_inventory:inv['source']['source_sha256']='b'*64
    inv_path.write_text(json.dumps(inv))
    review_path=directory/'outputs/self-review.json'
    if missing_review:review_path.unlink()
    else:
        review=json.loads(review_path.read_text());review['checks'][0].update(status='unresolved',details='Synthetic structure unresolved; do not invent a graph.')
        review_path.write_text(json.dumps(review))
    status,details=_postflight(directory,json.loads((directory/'task.json').read_text()))
    p=directory/'runtime-provenance.json';v=json.loads(p.read_text());v.update(outcome=status,candidate_file_sha256=details.get('candidate_file_sha256'));p.write_text(json.dumps(v))
    return {'state':{'status':status,**details}}


@pytest.mark.parametrize('missing_review',[False,True])
def test_unresolved_draft_is_imported_with_visible_bound_report(auth_session_factory,tmp_path,monkeypatch,missing_review):
    from app.ai_tasks.execution import report_for,deliver_result
    from app.ai_tasks.service import job_response
    c,settings=context_and_settings(auth_session_factory,tmp_path,monkeypatch)
    worker=AiTaskCoordinator(auth_session_factory,settings,runner=lambda directory,**kw:draft_runner(directory,missing_review=missing_review,**kw))
    with auth_session_factory.begin() as s:
        identifier=enqueue(s,settings,paper_id=c.paper_id,actor_id=c.admin_id,request=StartTask(action='prefill',preset_id='test',reasoning_effort='high',expected_workspace_id=c.workspace_id,expected_task_version=1,expected_workspace_version=1,idempotency_key=uuid4())).id
        claim_next(s,owner=worker.owner)
    worker.execute(identifier)
    with auth_session_factory() as s:
        job=s.get(AiTask,identifier)
        assert job.delivery_state=='applied',(job.state,job.error_code,job.error_message)
        assert job.state=='needs_revision' and job.error_code is None
        assert job.result_summary['scientific_approval'] is False
        assert job.result_summary['missing_compounds']==1
        assert job.result_summary['report_available'] is True
        assert job_response(s,job)['can_retry'] is False
        assert s.get(PaperWorkspace,c.workspace_id).version==2
        report=report_for(settings,job)
        assert report['report_kind']=='prefill'
        assert report['coverage']=={'expected':2,'reviewed':1,'missing':[{'domain':'compound','ref':'unknown-metabolite'}]}
        assert report['candidate_file_sha256']==job.result_summary['candidate_file_sha256']
        assert any(x['domain']=='COMPOUND_COVERAGE_INCOMPLETE' for x in report['findings'])
        if missing_review:assert any(x['domain']=='SELF_REVIEW_MISSING' for x in report['findings'])
    # A second completion cannot apply the candidate twice.
    deliver_result(auth_session_factory,settings,identifier,{'status':'needs_revision'})
    with auth_session_factory() as s:assert s.get(PaperWorkspace,c.workspace_id).version==2
    worker.stop()


@pytest.mark.parametrize('change',['candidate_source','invalid_reference','human_edit'])
def test_draft_delivery_still_refuses_unsafe_or_changed_target(auth_session_factory,tmp_path,monkeypatch,change):
    c,settings=context_and_settings(auth_session_factory,tmp_path,monkeypatch)
    def runner(directory,**kw):
        result=draft_runner(directory,**kw)
        if change=='human_edit':
            with auth_session_factory.begin() as s:s.get(PaperWorkspace,c.workspace_id).version=2
        else:
            path=directory/'outputs/candidate.json';v=json.loads(path.read_text())
            if change=='candidate_source':v['source']['source_sha256']='a'*64
            else:v['payload']['activities']=[{'compound_ref':'nonexistent','assay_name':'assay','metric':'IC50','operator':'=','value':1,'unit':'nM'}]
            path.write_text(json.dumps(v))
        return result
    worker=AiTaskCoordinator(auth_session_factory,settings,runner=runner)
    with auth_session_factory.begin() as s:
        identifier=enqueue(s,settings,paper_id=c.paper_id,actor_id=c.admin_id,request=StartTask(action='prefill',preset_id='test',reasoning_effort='high',expected_workspace_id=c.workspace_id,expected_task_version=1,expected_workspace_version=1,idempotency_key=uuid4())).id
        claim_next(s,owner=worker.owner)
    worker.execute(identifier)
    with auth_session_factory() as s:
        assert s.get(AiTask,identifier).delivery_state!='applied'
        assert s.get(PaperWorkspace,c.workspace_id).version==(2 if change=='human_edit' else 1)
    worker.stop()


def test_saved_unresolved_result_can_be_delivered_without_rerunning_model(auth_session_factory,tmp_path,monkeypatch):
    from app.ai_tasks.execution import prepare_job,deliver_result,report_for
    c,settings=context_and_settings(auth_session_factory,tmp_path,monkeypatch)
    with auth_session_factory.begin() as s:
        identifier=enqueue(s,settings,paper_id=c.paper_id,actor_id=c.admin_id,request=StartTask(action='prefill',preset_id='test',reasoning_effort='high',expected_workspace_id=c.workspace_id,expected_task_version=1,expected_workspace_version=1,idempotency_key=uuid4())).id
        claim_next(s,owner='test')
    directory=prepare_job(auth_session_factory,settings,identifier)
    result=draft_runner(directory)
    path=directory/'state.json';state=json.loads(path.read_text());state.update(result['state'],process_cleanup_confirmed=True);path.write_text(json.dumps(state))
    with auth_session_factory.begin() as s:
        job=s.get(AiTask,identifier);job.state='needs_revision';job.delivery_state='not_applied';job.error_code='OUTPUT_INCOMPLETE'
    deliver_result(auth_session_factory,settings,identifier,{},deliver_saved=True)
    with auth_session_factory() as s:
        job=s.get(AiTask,identifier)
        assert job.delivery_state=='applied' and job.result_summary['previous_delivery']['state']=='needs_revision'
        assert job.result_summary['previous_delivery']['error_code']=='OUTPUT_INCOMPLETE'
        report=report_for(settings,job)
        # Published task report is a database snapshot, unaffected by later sidecar edits.
        (directory/'outputs/self-review.json').write_text('{}')
        assert report_for(settings,job)==report
    worker_state=json.loads(path.read_text())
    assert worker_state==state  # Do not pretend that the scientific run passed.


def test_wrong_source_inventory_is_reported_without_discarding_valid_candidate(auth_session_factory,tmp_path,monkeypatch):
    c,settings=context_and_settings(auth_session_factory,tmp_path,monkeypatch)
    worker=AiTaskCoordinator(auth_session_factory,settings,runner=lambda directory,**kw:draft_runner(directory,wrong_inventory=True,**kw))
    with auth_session_factory.begin() as s:
        identifier=enqueue(s,settings,paper_id=c.paper_id,actor_id=c.admin_id,request=StartTask(action='prefill',preset_id='test',reasoning_effort='high',expected_workspace_id=c.workspace_id,expected_task_version=1,expected_workspace_version=1,idempotency_key=uuid4())).id
        claim_next(s,owner=worker.owner)
    worker.execute(identifier)
    with auth_session_factory() as s:
        job=s.get(AiTask,identifier)
        assert job.delivery_state=='applied',(job.state,job.error_code)
        report=job.result_summary['producer_report']
        assert report['coverage_known'] is False
        assert any(x['domain']=='INVENTORY_UNAVAILABLE' for x in report['findings'])
    worker.stop()


def test_failed_delivery_retains_report_and_can_retry_only_import(auth_session_factory,tmp_path,monkeypatch):
    from app.ai_tasks.execution import deliver_result
    from app.ai_prefill.service import AiPrefillService
    from app.ai_tasks.service import job_response
    c,settings=context_and_settings(auth_session_factory,tmp_path,monkeypatch)
    real_write=AiPrefillService._write_payload
    def fail(*args,**kwargs):raise ValueError('Synthetic failure with private payload must not reach UI')
    monkeypatch.setattr(AiPrefillService,'_write_payload',fail)
    worker=AiTaskCoordinator(auth_session_factory,settings,runner=fake_runner)
    with auth_session_factory.begin() as s:
        identifier=enqueue(s,settings,paper_id=c.paper_id,actor_id=c.admin_id,request=StartTask(action='prefill',preset_id='test',reasoning_effort='high',expected_workspace_id=c.workspace_id,expected_task_version=1,expected_workspace_version=1,idempotency_key=uuid4())).id
        claim_next(s,owner=worker.owner)
    worker.execute(identifier)
    with auth_session_factory() as s:
        job=s.get(AiTask,identifier)
        assert job.error_code=='DELIVERY_WRITE_FAILED'
        assert job.result_summary['report_available'] is True
        assert job.result_summary['delivery_failure']=={'exception_type':'ValueError'}
        assert 'private' not in json.dumps(job.result_summary)
        assert job_response(s,job)['can_deliver'] is True
        assert s.get(PaperWorkspace,c.workspace_id).version==1
    folder=settings.ai_task_root/str(identifier)/'job'
    state=json.loads((folder/'state.json').read_text());run=json.loads((folder/'runtime-provenance.json').read_text())
    state.update(status=run['outcome'],candidate_file_sha256=run['candidate_file_sha256'],process_cleanup_confirmed=True)
    (folder/'state.json').write_text(json.dumps(state))
    monkeypatch.setattr(AiPrefillService,'_write_payload',real_write)
    deliver_result(auth_session_factory,settings,identifier,{},deliver_saved=True)
    with auth_session_factory() as s:
        job=s.get(AiTask,identifier);assert job.delivery_state=='applied'
        assert job_response(s,job)['can_deliver'] is False
        assert s.get(PaperWorkspace,c.workspace_id).version==2
    worker.stop()
