"""Repair applies a delta, never replaces an edited workspace."""
from app.ai_prefill.contracts import AiPrefillPayload
from app.ai_tasks.repair_apply import design_diff


def payload():
    return AiPrefillPayload.model_validate({'schema_version':1, 'compounds':[
        {'ref':'a','compound_label':'1','structure':{'smiles':'CC'}},
        {'ref':'b','compound_label':'2','structure':{'smiles':'CCC'}}],
        'activities':[{'compound_ref':'a','assay_name':'binding','metric':'IC50','operator':'=','value':'10','unit':'nM'},
                      {'compound_ref':'a','assay_name':'binding','metric':'IC50','operator':'=','value':'20','unit':'nM'}]})


def test_diff_preserves_unchanged_duplicate_assay_identity_when_value_changes():
    before=payload(); data=before.model_dump(mode='json')
    data['activities'][0]['value']='12'
    after=AiPrefillPayload.model_validate(data)
    diff=design_diff(before,after)
    assert diff['total_changes']==1
    assert diff['changes'][0]['domain']=='activities'
    assert diff['changes'][0]['ref']=='activity:0'
    assert diff['changes'][0]['before']['value']=='10'
    assert diff['changes'][0]['after']['value']=='12'
    assert diff['counts']['activities']=={'added':0,'updated':1,'removed':0}
    assert design_diff(before,after)['sha256']==diff['sha256']


def test_diff_reports_structure_change_without_deleting_compound():
    before=payload(); data=before.model_dump(mode='json'); data['compounds'][0]['structure']['smiles']='CO'
    diff=design_diff(before,AiPrefillPayload.model_validate(data))
    assert diff['total_changes']==1
    assert diff['changes'][0]['domain']=='structures'
    assert diff['changes'][0]['action']=='update'
    assert design_diff(before,before)['total_changes']==0

from types import SimpleNamespace
from uuid import uuid4
import pytest
from sqlalchemy import select
from app.ai_prefill.service import AiPrefillService
from app.ai_prefill.workspace_export import _payload_from_snapshot
from app.ai_tasks.repair_apply import apply_delta, RepairApplyConflict
from app.catalog.models import PaperSource
from app.compounds.models import Compound
from app.lineages.models import LineageEdge
from app.structures.models import Structure, StructureStatus
from app.workspaces.models import PaperWorkspace, ChangeEvent, ChangeActorKind
from app.workspaces.snapshot import build_paper_snapshot
from tests.ai_prefill.test_apply import ai_context
from tests.ai_prefill.test_contract import complete_payload


def baseline(context,session,raw=None):
    run=AiPrefillService().queue(session,workspace_id=context.workspace_id,requested_by_id=context.admin_id,engine='synthetic',engine_version='1').run
    original=AiPrefillPayload.model_validate(raw if raw is not None else complete_payload())
    result=AiPrefillService().apply(session,run_id=run.id,payload=original)
    assert result.applied
    snapshot=build_paper_snapshot(session,context.workspace_id)
    parent=SimpleNamespace(payload=original,source=SimpleNamespace(source_sha256='a'*64))
    before,refs,_=_payload_from_snapshot(parent,snapshot,result.entity_map,snapshot['paper'])
    return before,snapshot,refs


def args(context,session,tmp_path,before,snapshot,refs):
    workspace=session.get(PaperWorkspace,context.workspace_id)
    source=session.scalar(select(PaperSource))
    return dict(settings=SimpleNamespace(asset_root=tmp_path,source_roots={}),workspace=workspace,source=source,
                actor_id=context.admin_id,before=before,baseline_snapshot=snapshot,entity_refs=refs,job_id=uuid4())


def test_apply_updates_structure_and_dependent_confirmation_but_keeps_ids_and_other_review(ai_context,tmp_path):
    with ai_context.session_factory.begin() as session:
        before,snapshot,refs=baseline(ai_context,session)
        structures=list(session.scalars(select(Structure))); edge=session.scalar(select(LineageEdge))
        for row in structures:row.status=StructureStatus.REVIEWER_CONFIRMED
        edge.review_status='reviewer_confirmed';session.flush()
        snapshot=build_paper_snapshot(session,ai_context.workspace_id)
        old_ids={str(row.id) for row in structures};version=snapshot['workspace_version']
        data=before.model_dump(mode='json');data['compounds'][0]['structure']={'smiles':'CCCO'}
        result=apply_delta(session,after=AiPrefillPayload.model_validate(data),**args(ai_context,session,tmp_path,before,snapshot,refs))
        assert result['workspace_version']==version+1
        assert {str(row.id) for row in session.scalars(select(Structure))}==old_ids
        changed=session.scalar(select(Structure).where(Structure.canonical_smiles=='CCCO'))
        assert changed is not None and changed.depiction_asset_id is not None and changed.status==StructureStatus.DRAFT
        assert next(row for row in structures if row.id!=changed.id).status==StructureStatus.REVIEWER_CONFIRMED
        assert edge.review_status=='draft'
        events=list(session.scalars(select(ChangeEvent).where(ChangeEvent.action.like('%.repair_%'))))
        assert events and all(row.actor_kind==ChangeActorKind.AI for row in events)
        assert all((row.after_value or row.before_value)['_repair']['repair_job_id'] for row in events)


def test_apply_rejects_stale_snapshot_and_noop_does_not_bump_version(ai_context,tmp_path):
    with ai_context.session_factory.begin() as session:
        before,snapshot,refs=baseline(ai_context,session)
        parameters=args(ai_context,session,tmp_path,before,snapshot,refs)
        assert apply_delta(session,after=before,**parameters)['workspace_version']==snapshot['workspace_version']
        session.scalar(select(Compound)).description='human correction';session.flush()
        with pytest.raises(RepairApplyConflict,match='Workspace changed'):
            apply_delta(session,after=before,**parameters)


def test_apply_adds_and_removes_dependencies_without_rebuilding_unchanged_rows(ai_context,tmp_path,monkeypatch):
    from app.structure_images.service import StructureSourceImageService
    monkeypatch.setattr(StructureSourceImageService,'render_source_image_crop',lambda *a,**k:None)
    with ai_context.session_factory.begin() as session:
        before,snapshot,refs=baseline(ai_context,session)
        preserved=session.scalar(select(Compound).where(Compound.compound_label=='Lead 1')).id
        data=before.model_dump(mode='json')
        removed=next(x for x in data['compounds'] if x['compound_label']=='Compound 18')['ref']
        data['compounds']=[x for x in data['compounds'] if x['ref']!=removed]
        data['compounds'].append({'ref':'compound:new','compound_label':'New 3','structure':{'smiles':'CO'}})
        data['lineages'][0]['members']=[x for x in data['lineages'][0]['members'] if x['compound_ref']!=removed]+[{'compound_ref':'compound:new','role':'terminal'}]
        data['lineages'][0]['edges'][0]['child_compound_ref']='compound:new'
        data['activities'][0]['compound_ref']='compound:new'
        data['activities'][0]['value']='4'
        after=AiPrefillPayload.model_validate(data)
        result=apply_delta(session,after=after,**args(ai_context,session,tmp_path,before,snapshot,refs))
        assert session.get(Compound,preserved).compound_label=='Lead 1'
        assert len(list(session.scalars(select(Compound))))==2
        assert session.scalar(select(Compound).where(Compound.compound_label=='Compound 18')) is None
        assert result['counts']['compounds']=={'added':1,'updated':0,'removed':1}


def test_evidence_edit_preserves_human_notes_and_invalidates_linked_edge(ai_context,tmp_path):
    from app.evidence.models import Evidence
    from app.structure_images.models import StructureSourceImage
    with ai_context.session_factory.begin() as session:
        before,snapshot,refs=baseline(ai_context,session)
        evidence=session.scalar(select(Evidence));evidence.reviewer_note='Human note: keep this'
        locator=session.scalar(select(StructureSourceImage));locator.reviewer_note='Original crop checked'
        edge=session.scalar(select(LineageEdge));edge.review_status='reviewer_confirmed';session.flush()
        snapshot=build_paper_snapshot(session,ai_context.workspace_id)
        evidence_id=evidence.id;locator_id=locator.id;crop_status=locator.crop_status
        data=before.model_dump(mode='json');data['evidence'][0]['quoted_text']='Corrected exact sentence'
        apply_delta(session,after=AiPrefillPayload.model_validate(data),**args(ai_context,session,tmp_path,before,snapshot,refs))
        assert evidence.id==evidence_id and evidence.reviewer_note=='Human note: keep this'
        assert locator.id==locator_id and locator.reviewer_note=='Original crop checked' and locator.crop_status==crop_status
        assert edge.review_status=='draft'


def test_late_crop_failure_rolls_back_all_mutations(ai_context,tmp_path,monkeypatch):
    from app.structure_images.service import StructureSourceImageService
    def fail(*a,**k):raise RuntimeError('synthetic crop failure')
    monkeypatch.setattr(StructureSourceImageService,'render_source_image_crop',fail)
    with ai_context.session_factory.begin() as session:
        before,snapshot,refs=baseline(ai_context,session)
        data=before.model_dump(mode='json');data['compounds'][0]['description']='Proposal only'
        data['structure_locators'][0]['page_number']=5
        with pytest.raises(RuntimeError,match='synthetic crop'):
            apply_delta(session,after=AiPrefillPayload.model_validate(data),**args(ai_context,session,tmp_path,before,snapshot,refs))
        assert build_paper_snapshot(session,ai_context.workspace_id)==snapshot
        assert list(session.scalars(select(ChangeEvent).where(ChangeEvent.action.like('%.repair_%'))))==[]


def test_compound_label_swaps_are_explicitly_rejected_before_writes(ai_context,tmp_path):
    with ai_context.session_factory.begin() as session:
        before,snapshot,refs=baseline(ai_context,session)
        data=before.model_dump(mode='json');left,right=data['compounds']
        left['compound_label'],right['compound_label']=right['compound_label'],left['compound_label']
        with pytest.raises(RepairApplyConflict,match='swaps existing compounds'):
            apply_delta(session,after=AiPrefillPayload.model_validate(data),**args(ai_context,session,tmp_path,before,snapshot,refs))
        assert build_paper_snapshot(session,ai_context.workspace_id)==snapshot


def test_add_evidence_highlight_crop_and_edit_activity_keep_existing_ids(ai_context,tmp_path,monkeypatch):
    from app.activities.models import Activity
    from app.compounds.models import CompoundHighlight
    from app.evidence.models import Evidence, EdgeEvidenceLink
    from app.structure_images.service import StructureSourceImageService
    from app.structure_images.models import CropStatus
    rendered=[]
    def render(session,*,source_image,actor_id):
        rendered.append(source_image.id);source_image.crop_status=CropStatus.READY
    monkeypatch.setattr(StructureSourceImageService,'render_source_image_crop',staticmethod(render))
    with ai_context.session_factory.begin() as session:
        before,snapshot,refs=baseline(ai_context,session)
        activity_id=session.scalar(select(Activity.id));link_id=session.scalar(select(EdgeEvidenceLink.id))
        data=before.model_dump(mode='json')
        data['bibliography']['abstract']='A synthetic abstract'
        data['evidence'].append({'ref':'evidence:new','kind':'text','page_number':6,'quoted_text':'New synthetic evidence'})
        target=data['activities'][0]['compound_ref']
        data['activities'][0]['value']='7.25';data['activities'][0]['evidence_ref']='evidence:new'
        data['edge_evidence_links'][0]['role']='contextual'
        data['compound_highlights']=[{'ref':'highlight:new','compound_ref':target,'evidence_ref':'evidence:new',
                                     'role':'paper_selected','scope':'paper','rationale':'Explicit source selection'}]
        data['structure_locators'].append({'ref':'locator:new','compound_ref':target,'page_number':6,
            'bbox':{'x0':'0.1','y0':'0.1','x1':'0.3','y1':'0.4'},'source_context':'Synthetic scheme'})
        result=apply_delta(session,after=AiPrefillPayload.model_validate(data),**args(ai_context,session,tmp_path,before,snapshot,refs))
        assert session.scalar(select(Activity.id))==activity_id
        assert session.scalar(select(EdgeEvidenceLink.id))==link_id
        assert session.scalar(select(CompoundHighlight)).review_status=='draft'
        assert len(list(session.scalars(select(Evidence))))==2
        assert len(rendered)==1
        assert result['counts']['activities']['updated']==1


def test_diff_ignores_equivalent_decimal_rendering():
    before=payload();data=before.model_dump(mode='json');data['activities'][0]['value']='10.0000000000'
    assert design_diff(before,AiPrefillPayload.model_validate(data))['total_changes']==0


def test_diff_rejects_conflicting_duplicate_evidence_links():
    before=AiPrefillPayload.model_validate(complete_payload())
    data=before.model_dump(mode='json')
    data['edge_evidence_links'].append({**data['edge_evidence_links'][0],'role':'contradicts'})
    with pytest.raises(RepairApplyConflict,match='Duplicate Edge/Evidence'):
        design_diff(before,AiPrefillPayload.model_validate(data))


def test_locator_repair_invalidates_sections_for_changed_confirmations(ai_context,tmp_path,monkeypatch):
    from app.compounds.models import CompoundHighlight
    from app.structure_images.service import StructureSourceImageService
    from app.structure_images.models import CropStatus
    from app.workspaces.models import PaperSectionReview, PaperSectionState
    def render(session,*,source_image,actor_id):source_image.crop_status=CropStatus.READY
    monkeypatch.setattr(StructureSourceImageService,'render_source_image_crop',staticmethod(render))
    with ai_context.session_factory.begin() as session:
        raw=complete_payload()
        raw['compound_highlights']=[{'ref':'highlight:start','compound_ref':'compound:lead-1',
            'evidence_ref':'evidence:scheme-2','role':'study_start','scope':'paper','rationale':'Synthetic starting point'}]
        before,snapshot,refs=baseline(ai_context,session,raw)
        for row in session.scalars(select(Structure)):row.status=StructureStatus.REVIEWER_CONFIRMED
        session.scalar(select(LineageEdge)).review_status='reviewer_confirmed'
        session.scalar(select(CompoundHighlight)).review_status='reviewer_confirmed'
        sections=list(session.scalars(select(PaperSectionReview)))
        for row in sections:row.state=PaperSectionState.COMPLETED;row.note='Keep reviewer note'
        session.flush();snapshot=build_paper_snapshot(session,ai_context.workspace_id)
        data=before.model_dump(mode='json');data['structure_locators'][0]['page_number']=5
        result=apply_delta(session,after=AiPrefillPayload.model_validate(data),**args(ai_context,session,tmp_path,before,snapshot,refs))
        assert {change['domain'] for change in result['changes']}=={'locators'}
        for row in sections:
            assert row.state==('completed' if row.section_key=='bibliography' else 'pending')
            assert row.note=='Keep reviewer note'
        section_events=list(session.scalars(select(ChangeEvent).where(ChangeEvent.action=='paper_section_review.repair_invalidate')))
        assert len(section_events)==5
        assert all(row.before_value['state']=='completed' and row.after_value['state']=='pending' for row in section_events)


def test_locator_halfway_quantization_matches_database_and_occurrence_grouping():
    before=AiPrefillPayload.model_validate(complete_payload())
    data=before.model_dump(mode='json');data['structure_locators'][0]['bbox']['x0']='0.10000000005'
    diff=design_diff(before,AiPrefillPayload.model_validate(data))
    assert diff['total_changes']==1
    assert diff['changes'][0]['after']['bbox']['x0']=='0.1000000001'
