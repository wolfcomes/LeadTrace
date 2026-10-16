"""Directed revisions use current drafts and auto-apply validated deltas once."""
import json
from datetime import datetime, UTC
from uuid import uuid4
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from app.ai_tasks.contracts import StartTask
from app.ai_tasks.models import AiTask
from app.ai_tasks.service import enqueue, claim_next, job_response, cancel_job
from app.ai_tasks.coordinator import AiTaskCoordinator
from app.ai_tasks.execution import deliver_result, report_for
from app.compounds.models import Compound
from app.structures.models import Structure
from app.workspaces.models import PaperWorkspace, WorkspaceViewReceipt, ChangeEvent, ChangeActorKind
from app.workspaces.review_progress import get_progress
from .test_execution import context_and_settings, fake_runner
from .test_repair_flow import runner


def request(c, version=1, **kwargs):
    return StartTask(preset_id='test', reasoning_effort='high', expected_workspace_id=c.workspace_id,
                     expected_task_version=1, expected_workspace_version=version, idempotency_key=uuid4(), **kwargs)


def test_revision_requires_only_nonblank_bounded_instructions():
    for instructions in (None, '', '  ', 'x'*12001):
        with pytest.raises(ValidationError):
            StartTask(action='revise', preset_id='test', reasoning_effort='high', idempotency_key=uuid4(), instructions=instructions)
    valid=StartTask(action='revise',preset_id='test',reasoning_effort='high',idempotency_key=uuid4(),instructions='  Check lineage scope  ')
    assert valid.instructions=='Check lineage scope'
    with pytest.raises(ValidationError):
        StartTask(action='prefill',preset_id='test',reasoning_effort='high',idempotency_key=uuid4(),instructions='do something')


def prepare(factory,tmp_path,monkeypatch):
    c,settings=context_and_settings(factory,tmp_path,monkeypatch)
    worker=AiTaskCoordinator(factory,settings,runner=fake_runner)
    with factory.begin() as s:
        jid=enqueue(s,settings,paper_id=c.paper_id,actor_id=c.admin_id,request=request(c,action='prefill')).id
        claim_next(s,owner=worker.owner)
    worker.execute(jid)
    with factory.begin() as s:
        s.scalar(select(Compound)).description='Keep reviewer correction'
        s.get(PaperWorkspace,c.workspace_id).version+=1;s.flush()
        for item in get_progress(s,c.workspace_id,c.admin_id)['items']:
            s.add(WorkspaceViewReceipt(workspace_id=c.workspace_id,reviewer_id=c.admin_id,kind=item['kind'],entity_id=item['entity_id'],signature=item['signature'],viewed_at=datetime.now(UTC)))
    return c,settings,worker,jid


def test_revision_auto_applies_current_draft_preserves_identity_and_invalidates_view(auth_session_factory,tmp_path,monkeypatch):
    c,settings,worker,parent=prepare(auth_session_factory,tmp_path,monkeypatch)
    with auth_session_factory.begin() as s:
        assert job_response(s,s.get(AiTask,parent))['can_revise']
        req=request(c,3,action='revise',instructions='Correct the structure only; keep reviewer notes')
        jid=enqueue(s,settings,paper_id=c.paper_id,actor_id=c.admin_id,request=req).id
        assert enqueue(s,settings,paper_id=c.paper_id,actor_id=c.admin_id,request=req).id==jid
        cid=s.scalar(select(Compound)).id;claim_next(s,owner=worker.owner)
    def revision(directory,**kwargs):
        task=json.loads((directory/'task.json').read_text())
        assert task['entry']=='selfcheck' and task['continuation']['strategy']=='fresh_session'
        base=json.loads((directory/'inputs/current-candidate.json').read_text())
        assert base['payload']['compounds'][0]['description']=='Keep reviewer correction'
        assert json.loads((directory/'inputs/feedback.json').read_text())['instructions']==req.instructions
        return runner(directory,**kwargs)
    worker.runner=revision;worker.execute(jid)
    with auth_session_factory() as s:
        job=s.get(AiTask,jid)
        assert job.delivery_state=='applied',(job.state,job.error_code,job.error_message)
        assert not job_response(s,job)['can_accept']
        assert job.result_summary['scientific_approval'] is False
        assert job.result_summary['revision_changes']['total_changes']==1
        assert s.get(PaperWorkspace,c.workspace_id).version==4
        assert s.get(Compound,cid).description=='Keep reviewer correction'
        assert s.scalar(select(Structure)).smiles=='CC'
        assert not get_progress(s,c.workspace_id,c.admin_id)['items'][0]['viewed']
        events=list(s.scalars(select(ChangeEvent).where(ChangeEvent.action.like('%.repair_%'))))
        assert events and all(e.actor_kind==ChangeActorKind.AI for e in events)
        assert report_for(settings,job)['report_kind']=='revise'
    deliver_result(auth_session_factory,settings,jid,{'status':'failed'})
    with auth_session_factory() as s:assert s.get(PaperWorkspace,c.workspace_id).version==4
    worker.stop()


@pytest.mark.parametrize('mode',['conflict','cancelled','failed','timed_out','no_change','invalid'])
def test_revision_never_overwrites_drift_or_applies_unsuccessful_output(auth_session_factory,tmp_path,monkeypatch,mode):
    c,settings,worker,_=prepare(auth_session_factory,tmp_path,monkeypatch)
    with auth_session_factory.begin() as s:
        if mode=='no_change':
            structure=s.scalar(select(Structure));structure.smiles=structure.canonical_smiles='CC'
        jid=enqueue(s,settings,paper_id=c.paper_id,actor_id=c.admin_id,request=request(c,3,action='revise',instructions='Check structure')).id
        claim_next(s,owner=worker.owner)
    def revision(directory,**kwargs):
        result=runner(directory,**kwargs)
        if mode=='conflict':
            with auth_session_factory.begin() as s:
                s.scalar(select(Compound)).description='New human edit';s.get(PaperWorkspace,c.workspace_id).version+=1
        if mode=='cancelled':
            with auth_session_factory.begin() as s:cancel_job(s,s.get(AiTask,jid))
        if mode in {'failed','timed_out'}:result['state']['status']=mode
        if mode=='invalid':(directory/'outputs/candidate.json').write_text('{}')
        return result
    worker.runner=revision;worker.execute(jid)
    with auth_session_factory() as s:
        job=s.get(AiTask,jid)
        assert job.delivery_state!='applied',(mode,job.state)
        assert s.get(PaperWorkspace,c.workspace_id).version==(4 if mode=='conflict' else 3)
        assert s.scalar(select(Structure)).smiles==('CC' if mode=='no_change' else 'C')
        if mode=='no_change':
            assert job.state=='completed'
            assert job.result_summary['revision_changes']['total_changes']==0
        if mode=='conflict':assert job.error_code=='WORKSPACE_CHANGED'
    worker.stop()


def test_revision_delta_preserves_unaffected_view_and_marks_new_groups_unviewed(auth_session_factory,tmp_path,monkeypatch):
    from hashlib import sha256
    from leadtrace.ops.ai_prefill.tasks import _postflight
    c,settings,worker,_=prepare(auth_session_factory,tmp_path,monkeypatch)
    with auth_session_factory.begin() as s:
        jid=enqueue(s,settings,paper_id=c.paper_id,actor_id=c.admin_id,request=request(c,3,action='revise',instructions='Add the missing compound only')).id
        claim_next(s,owner=worker.owner)
    def revision(directory,**kwargs):
        runner(directory,**kwargs)
        task=json.loads((directory/'task.json').read_text())
        path=directory/'outputs/candidate.json';out=json.loads(path.read_text())
        original=json.loads((directory/'inputs/current-candidate.json').read_text())
        out['payload']=original['payload']
        out['payload']['compounds'].append({'ref':'new:2','compound_label':'2','structure':{'smiles':'CO'}})
        raw=json.dumps(out).encode();path.write_bytes(raw)
        review_path=directory/'outputs/self-review.json';review=json.loads(review_path.read_text());review['candidate_file_sha256']=sha256(raw).hexdigest();review_path.write_text(json.dumps(review))
        status,details=_postflight(directory,task)
        provenance_path=directory/'runtime-provenance.json';provenance=json.loads(provenance_path.read_text());provenance.update(outcome=status,candidate_file_sha256=sha256(raw).hexdigest());provenance_path.write_text(json.dumps(provenance))
        state={'status':status,**details,'process_cleanup_confirmed':True}
        state_path=directory/'state.json';saved=json.loads(state_path.read_text());saved.update(state);state_path.write_text(json.dumps(saved))
        return {'state':state}
    worker.runner=revision;worker.execute(jid)
    with auth_session_factory() as s:
        job=s.get(AiTask,jid);assert job.delivery_state=='applied',(job.state,job.error_code)
        assert {x['label']:x['viewed'] for x in get_progress(s,c.workspace_id,c.admin_id)['items']}=={'1':True,'2':False}
        events=list(s.scalars(select(ChangeEvent).where(ChangeEvent.action.like('%.repair_%'))))
        for event in events:
            metadata=(event.after_value or event.before_value)['_repair']
            assert metadata['delivery_mode']=='automatic_revision'
            assert metadata['requested_by_id']==str(c.admin_id)
            assert 'accepted_by_id' not in metadata
    worker.stop()


@pytest.mark.parametrize('section', ['compounds','lineages','bibliography','activities'])
def test_omitted_fields_cannot_silently_erase_reviewer_content(section):
    from app.ai_tasks.revision import require_explicit_revision_fields
    from app.ai_tasks.service import TaskError
    before={
        'compounds':[{'ref':'c1','description':'human correction','structure':{'smiles':'CC'}}],
        'lineages':[{'ref':'g1','description':'human scope','members':[],'edges':[]}],
        'bibliography':{'research_profile':{'mechanisms':[{'name':'human mechanism','source':'p1'}]}},
        'activities':[{'compound_ref':'c1','assay_name':'binding','metric':'IC50','operator':'=','value':'1','unit':'nM','context':'human condition'}],
    }
    raw=json.loads(json.dumps(before))
    if section in {'compounds','lineages'}:del raw[section][0]['description']
    elif section=='bibliography':del raw[section]['research_profile']
    else:del raw[section][0]['context']
    with pytest.raises(TaskError,match='omitted'):
        require_explicit_revision_fields(before,raw)
    if section in {'compounds','lineages'}:raw[section][0]['description']=None
    elif section=='bibliography':raw[section]['research_profile']=None
    else:raw[section][0]['context']=None
    require_explicit_revision_fields(before,raw)


def test_revision_export_preserves_reviewer_notes_outside_candidate():
    from app.ai_tasks.revision import export_revision_baseline
    from app.ai_prefill.workspace_export import _payload_from_snapshot
    from tests.ai_prefill.test_workspace_export import alias_export_fixture
    parent,snapshot,mapping=alias_export_fixture()
    snapshot['structure_source_images'][0]['reviewer_note']='Human crop note'
    snapshot['evidence']=[{'id':str(uuid4()),'source_sha256':'a'*64,'page_number':1,'kind':'text','x0':None,'y0':None,'x1':None,'y1':None,'quoted_text':'Synthetic quote','caption':None,'reviewer_note':'Human evidence note'}]
    with pytest.raises(ValueError):_payload_from_snapshot(parent,snapshot,mapping,snapshot['paper'])
    payload,refs,metadata,notes=export_revision_baseline(parent,snapshot,mapping)
    assert payload.structure_locators and payload.evidence
    assert {n['note'] for n in notes}=={'Human crop note','Human evidence note'}
    assert snapshot['structure_source_images'][0]['reviewer_note']=='Human crop note'
    assert all(n['ref'] in refs.values() for n in notes)


@pytest.mark.parametrize('new_group',[False,True])
def test_regrouped_edge_cannot_lose_populated_fields(new_group):
    from app.ai_tasks.revision import require_explicit_revision_fields
    from app.ai_tasks.service import TaskError
    edge={'ref':'e1','parent_compound_ref':'c1','child_compound_ref':'c2','modification_summary':'Human explanation','review_hint':'Human unresolved point'}
    before={'lineages':[{'ref':'g1','edges':[edge]},{'ref':'g2','edges':[]}]}
    raw={'lineages':[{'ref':'g1','edges':[]},{'ref':'g3' if new_group else 'g2','edges':[{k:v for k,v in edge.items() if k not in {'modification_summary','review_hint'}}]}]}
    with pytest.raises(TaskError,match='omitted'):require_explicit_revision_fields(before,raw)
    raw['lineages'][1]['edges'][0].update(modification_summary='Human explanation',review_hint=None)
    require_explicit_revision_fields(before,raw)


def test_reordered_normalized_activity_cannot_lose_human_context():
    from app.ai_tasks.revision import require_explicit_revision_fields
    from app.ai_tasks.service import TaskError
    a={'compound_ref':'c1','assay_name':'binding','metric':'IC50','operator':'=','unit':'nM','value':'1.00','context':None}
    b={**a,'value':'2.00','context':'Human assay detail'}
    before={'activities':[a,b]}
    raw={'activities':[{k:v for k,v in {**b,'value':'2'}.items() if k!='context'},{**a,'value':'1'}]}
    with pytest.raises(TaskError,match='omitted'):require_explicit_revision_fields(before,raw)
    raw['activities'][0]['context']='Human assay detail'
    require_explicit_revision_fields(before,raw)


def test_reordered_metadata_cannot_erase_populated_fields():
    from app.ai_tasks.revision import require_explicit_revision_fields
    from app.ai_tasks.service import TaskError
    before={'bibliography':{'research_profile':{'targets':[{'name':'A','gene_symbol':None},{'name':'B','gene_symbol':'BGENE'}]}}}
    raw={'bibliography':{'research_profile':{'targets':[{'name':'B'},{'name':'A','gene_symbol':None}]}}}
    with pytest.raises(TaskError,match='omitted'):require_explicit_revision_fields(before,raw)
    raw['bibliography']['research_profile']['targets'][0]['gene_symbol']='BGENE'
    require_explicit_revision_fields(before,raw)
