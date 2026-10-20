"""Existing incomplete drafts are preserved, never synthesized or silently resolved."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from app.ai_prefill.contracts import AiPrefillPayload
from app.ai_prefill.assistance_validation import validate_candidate
from app.ai_prefill.service import AiPrefillService
from app.ai_prefill.workspace_export import _payload_from_snapshot
from app.ai_tasks.revision import export_revision_baseline
from app.ai_tasks.repair_apply import apply_delta, RepairApplyConflict
from app.structures.models import Structure, StructureStatus
from app.lineages.models import LineageEdge
from app.workspaces.snapshot import build_paper_snapshot
from tests.ai_prefill.test_apply import ai_context
from tests.ai_prefill.test_assistance_validation import make
from tests.ai_prefill.test_workspace_export import alias_export_fixture
from tests.ai_prefill.test_contract import complete_payload
from tests.ai_tasks.test_repair_apply import baseline, args


@pytest.mark.parametrize('mode',['missing','empty','unresolved','not_reported'])
def test_export_preserves_incomplete_structure_only_in_revision(mode):
    parent,snapshot,mapping=alias_export_fixture()
    if mode=='missing':snapshot['structures']=[]
    elif mode=='empty':snapshot['structures'][0].update(smiles=None,molfile=None,status='draft')
    else:snapshot['structures'][0]['status']=mode
    original=deepcopy(snapshot)
    with pytest.raises(ValueError):_payload_from_snapshot(parent,snapshot,mapping,snapshot['paper'])
    payload,refs,metadata,notes=export_revision_baseline(parent,snapshot,mapping)
    assert len(payload.compounds)==1
    assert payload.compounds[0].structure.preserve_unresolved is True
    assert payload.compounds[0].structure.smiles==('C' if mode in {'unresolved','not_reported'} else None)
    assert snapshot==original
    report=validate_candidate(make(payload))
    assert report.can_apply
    assert any(i.code=='PRESERVED_UNRESOLVED_STRUCTURE' for i in report.issues)
    assert AiPrefillService._parse_structures(payload) is None


def test_legacy_serialization_omits_preservation_markers():
    payload=AiPrefillPayload.model_validate(complete_payload())
    assert 'preserve_unresolved' not in str(payload.model_dump(mode='json'))


@pytest.mark.parametrize('mode',['missing','empty','unresolved','not_reported'])
def test_lineage_revision_preserves_incomplete_records_and_noop(ai_context,tmp_path,mode):
    with ai_context.session_factory.begin() as s:
        before,_,_=baseline(ai_context,s)
        structure=s.scalar(select(Structure));edge=s.scalar(select(LineageEdge))
        if mode=='missing':s.delete(structure)
        elif mode=='empty':structure.smiles=structure.molfile=None;structure.status=StructureStatus.UNRESOLVED
        else:structure.status=StructureStatus(mode)
        edge.review_status='unresolved';edge.review_hint='Human question';s.flush()
        snapshot=build_paper_snapshot(s,ai_context.workspace_id)
        parent=SimpleNamespace(payload=before,source=SimpleNamespace(source_sha256='a'*64))
        before,refs,_,_=export_revision_baseline(parent,snapshot)
        assert before.lineages[0].edges[0].preserve_unresolved is True
        assert any(i.code=='PRESERVED_UNRESOLVED_EDGE' for i in validate_candidate(make(before)).issues)
        parameters=args(ai_context,s,tmp_path,before,snapshot,refs)
        result=apply_delta(s,after=before,automatic_revision=True,**parameters)
        assert result['total_changes']==0
        assert build_paper_snapshot(s,ai_context.workspace_id)==snapshot
        data=before.model_dump(mode='json');data['lineages'][0]['description']='Clearer grouping'
        result=apply_delta(s,after=AiPrefillPayload.model_validate(data),automatic_revision=True,**parameters)
        after=build_paper_snapshot(s,ai_context.workspace_id)
        assert result['total_changes']==1
        assert after['structures']==snapshot['structures']
        assert after['compounds']==snapshot['compounds']
        assert after['lineage_edges']==snapshot['lineage_edges']
        assert after['workspace_version']==snapshot['workspace_version']+1


@pytest.mark.parametrize('change',['replace_structure','clear_edge_marker','delete_edge','new_marker','retarget_edge'])
def test_protected_records_cannot_be_forged_or_cleared(ai_context,tmp_path,change):
    with ai_context.session_factory.begin() as s:
        before,_,_=baseline(ai_context,s)
        structure=s.scalar(select(Structure));structure.smiles=structure.molfile=None;structure.status=StructureStatus.UNRESOLVED
        s.scalar(select(LineageEdge)).review_status='unresolved';s.flush()
        snapshot=build_paper_snapshot(s,ai_context.workspace_id)
        parent=SimpleNamespace(payload=before,source=SimpleNamespace(source_sha256='a'*64))
        before,refs,_,_=export_revision_baseline(parent,snapshot)
        data=before.model_dump(mode='json')
        protected=next(c for c in data['compounds'] if c['structure'].get('preserve_unresolved'))
        edge=data['lineages'][0]['edges'][0]
        if change=='replace_structure':protected['structure']={'smiles':'CCO'}
        elif change=='clear_edge_marker':edge.pop('preserve_unresolved')
        elif change=='delete_edge':data['lineages'][0]['edges']=[];data['edge_evidence_links']=[]
        elif change=='new_marker':
            next(c for c in data['compounds'] if c is not protected)['structure']['preserve_unresolved']=True
        elif change=='retarget_edge':edge['parent_compound_ref'],edge['child_compound_ref']=edge['child_compound_ref'],edge['parent_compound_ref']
        with pytest.raises(RepairApplyConflict,match='preserv|unresolved'):
            apply_delta(s,after=AiPrefillPayload.model_validate(data),automatic_revision=True,**args(ai_context,s,tmp_path,before,snapshot,refs))
        assert build_paper_snapshot(s,ai_context.workspace_id)==snapshot


def test_initial_prefill_rejects_preserved_edges(ai_context):
    with ai_context.session_factory.begin() as s:
        raw=complete_payload();raw['lineages'][0]['edges'][0]['preserve_unresolved']=True
        run=AiPrefillService().queue(s,workspace_id=ai_context.workspace_id,requested_by_id=ai_context.admin_id,engine='test',engine_version='1').run
        result=AiPrefillService().apply(s,run_id=run.id,payload=AiPrefillPayload.model_validate(raw))
        assert not result.applied


@pytest.mark.parametrize('edit',['annotation','regroup','forged_baseline'])
def test_unresolved_edge_identity_and_view_state(ai_context,tmp_path,edit):
    from datetime import datetime,UTC
    from app.workspaces.models import WorkspaceViewReceipt
    from app.workspaces.review_progress import get_progress
    with ai_context.session_factory.begin() as s:
        before,_,_=baseline(ai_context,s)
        edge=s.scalar(select(LineageEdge));edge.review_status='unresolved';s.flush()
        for item in get_progress(s,ai_context.workspace_id,ai_context.reviewer_id)['items']:
            s.add(WorkspaceViewReceipt(workspace_id=ai_context.workspace_id,reviewer_id=ai_context.reviewer_id,kind=item['kind'],entity_id=item['entity_id'],signature=item['signature'],viewed_at=datetime.now(UTC)))
        s.flush()
        snapshot=build_paper_snapshot(s,ai_context.workspace_id)
        parent=SimpleNamespace(payload=before,source=SimpleNamespace(source_sha256='a'*64))
        before,refs,_,_=export_revision_baseline(parent,snapshot)
        data=before.model_dump(mode='json')
        if edit=='annotation':data['lineages'][0]['edges'][0]['modification_summary']='Clarified, still uncertain'
        elif edit=='regroup':
            group=deepcopy(data['lineages'][0]);group['ref']='new-group';group['lineage_label']='Next stage'
            data['lineages'][0]['edges']=[];data['lineages'].append(group)
        else:
            data['compounds'][0]['structure']['preserve_unresolved']=True
            before=AiPrefillPayload.model_validate(data)
        if edit=='forged_baseline':
            with pytest.raises(RepairApplyConflict,match='preserv'):
                apply_delta(s,after=before,automatic_revision=True,**args(ai_context,s,tmp_path,before,snapshot,refs))
            assert build_paper_snapshot(s,ai_context.workspace_id)==snapshot
            return
        result=apply_delta(s,after=AiPrefillPayload.model_validate(data),automatic_revision=True,**args(ai_context,s,tmp_path,before,snapshot,refs))
        assert result['total_changes']>0
        assert s.get(LineageEdge,edge.id).review_status=='unresolved'
        progress=get_progress(s,ai_context.workspace_id,ai_context.reviewer_id)['items']
        assert all(i['viewed'] for i in progress if i['kind']=='compound')
        assert all(not i['viewed'] for i in progress if i['kind']=='lineage')


def test_coordinator_can_deliver_lineage_revision_with_missing_structure(auth_session_factory,tmp_path,monkeypatch):
    import json
    from hashlib import sha256
    from app.ai_tasks.models import AiTask
    from app.ai_tasks.service import enqueue,claim_next
    from app.workspaces.models import PaperWorkspace
    from tests.ai_tasks.test_revision import prepare,request
    from tests.ai_tasks.test_repair_flow import runner
    from leadtrace.ops.ai_prefill.tasks import _postflight
    c,settings,worker,_=prepare(auth_session_factory,tmp_path,monkeypatch)
    with auth_session_factory.begin() as s:
        row=s.scalar(select(Structure));row.smiles=row.molfile=None;row.status=StructureStatus.UNRESOLVED
        jid=enqueue(s,settings,paper_id=c.paper_id,actor_id=c.admin_id,request=request(c,3,action='revise',instructions='Clarify lineage, preserve incomplete structures')).id
        claim_next(s,owner=worker.owner)
    def revision(directory,**kwargs):
        runner(directory,**kwargs)
        task=json.loads((directory/'task.json').read_text())
        path=directory/'outputs/candidate.json';out=json.loads(path.read_text())
        original=json.loads((directory/'inputs/current-candidate.json').read_text())
        assert original['payload']['compounds'][0]['structure']['preserve_unresolved'] is True
        out['payload']=original['payload']
        out['payload']['lineages']=[{'ref':'new-group','lineage_label':'Series','members':[{'compound_ref':out['payload']['compounds'][0]['ref'],'role':'unspecified'}],'edges':[]}]
        raw=json.dumps(out).encode();path.write_bytes(raw)
        review_path=directory/'outputs/self-review.json';review=json.loads(review_path.read_text());review['candidate_file_sha256']=sha256(raw).hexdigest();review_path.write_text(json.dumps(review))
        status,details=_postflight(directory,task)
        provenance_path=directory/'runtime-provenance.json';provenance=json.loads(provenance_path.read_text());provenance.update(outcome=status,candidate_file_sha256=sha256(raw).hexdigest());provenance_path.write_text(json.dumps(provenance))
        state={'status':status,**details,'process_cleanup_confirmed':True}
        state_path=directory/'state.json';saved=json.loads(state_path.read_text());saved.update(state);state_path.write_text(json.dumps(saved))
        return {'state':state}
    worker.runner=revision;worker.execute(jid)
    with auth_session_factory() as s:
        job=s.get(AiTask,jid)
        assert job.delivery_state=='applied',(job.state,job.error_code,job.error_message)
        row=s.scalar(select(Structure));assert row.smiles is None and row.status==StructureStatus.UNRESOLVED
        assert s.get(PaperWorkspace,c.workspace_id).version==4
    worker.stop()


def test_bound_review_repair_preserves_legacy_gap_and_rejects_marker_mutation(ai_context,tmp_path):
    with ai_context.session_factory.begin() as s:
        original,_,_=baseline(ai_context,s)
        structure=s.scalar(select(Structure));structure.smiles=structure.molfile=None;structure.status=StructureStatus.NOT_REPORTED
        edge=s.scalar(select(LineageEdge));edge.review_status='unresolved';s.flush()
        snapshot=build_paper_snapshot(s,ai_context.workspace_id)
        parent=SimpleNamespace(payload=original,source=SimpleNamespace(source_sha256='a'*64))
        before,refs,_=_payload_from_snapshot(parent,snapshot,{},snapshot['paper'],preserve_unresolved=True)
        data=before.model_dump(mode='json');data['lineages'][0]['description']='Review-supported grouping note'
        apply_delta(s,after=AiPrefillPayload.model_validate(data),**args(ai_context,s,tmp_path,before,snapshot,refs))
        assert build_paper_snapshot(s,ai_context.workspace_id)['structures']==snapshot['structures']
        assert edge.review_status=='unresolved'
        current=build_paper_snapshot(s,ai_context.workspace_id)
        before,refs,_=_payload_from_snapshot(parent,current,{},current['paper'],preserve_unresolved=True)
        malicious=before.model_dump(mode='json');next(c for c in malicious['compounds'] if c['structure'].get('preserve_unresolved'))['structure']={'smiles':'CC'}
        with pytest.raises(RepairApplyConflict,match='preserv'):
            apply_delta(s,after=AiPrefillPayload.model_validate(malicious),**args(ai_context,s,tmp_path,before,current,refs))


@pytest.mark.parametrize('explicit',[False,True])
def test_unparseable_human_draft_is_preserved_by_bound_repair(ai_context,tmp_path,explicit):
    with ai_context.session_factory.begin() as s:
        original,_,_=baseline(ai_context,s)
        structure=s.scalar(select(Structure));structure.smiles='bad smiles';structure.molfile=None;structure.canonical_smiles=None;structure.status=StructureStatus.DRAFT
        if explicit:structure.availability='available'
        s.flush();snapshot=build_paper_snapshot(s,ai_context.workspace_id)
        parent=SimpleNamespace(payload=original,source=SimpleNamespace(source_sha256='a'*64))
        before,refs,_,_=export_revision_baseline(parent,snapshot)
        assert any(c.structure.preserve_unresolved and c.structure.smiles=='bad smiles' for c in before.compounds)
        data=before.model_dump(mode='json');data['lineages'][0]['description']='Checked grouping'
        apply_delta(s,after=AiPrefillPayload.model_validate(data),**args(ai_context,s,tmp_path,before,snapshot,refs))
        assert build_paper_snapshot(s,ai_context.workspace_id)['structures']==snapshot['structures']
