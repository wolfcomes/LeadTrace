import pytest
from pydantic import ValidationError
from app.ai_prefill.contracts import AiPrefillPayload
from app.ai_prefill.service import AiPrefillService
from tests.ai_prefill.test_contract import complete_payload


def absent():
    return dict(availability='not_reported', availability_note='No structure in inspected source', identity_source='Table 2, row 32a', checked_sources='Main text pages 1–10 and complete SI')


def test_source_identifiable_absent_structure_keeps_activity_and_parses():
    raw=complete_payload();raw['compounds'][1]['structure']=absent()
    payload=AiPrefillPayload.model_validate(raw)
    assert payload.activities[0].compound_ref==payload.compounds[1].ref
    parsed=AiPrefillService._parse_structures(payload)
    assert parsed is not None
    assert parsed[payload.compounds[1].ref].canonical_smiles is None
    assert payload.model_dump(mode='json')['compounds'][1]['structure']['availability']=='not_reported'


@pytest.mark.parametrize('field',['availability_note','identity_source','checked_sources'])
def test_absent_structure_requires_explicit_provenance(field):
    raw=complete_payload();raw['compounds'][1]['structure']=absent();raw['compounds'][1]['structure'][field]=' '
    with pytest.raises(ValidationError):AiPrefillPayload.model_validate(raw)


def test_absent_structure_cannot_hide_representation():
    raw=complete_payload();raw['compounds'][1]['structure']=absent()|{'smiles':'CC'}
    with pytest.raises(ValidationError):AiPrefillPayload.model_validate(raw)


def test_old_candidate_bytes_unchanged():
    value=AiPrefillPayload.model_validate(complete_payload()).model_dump(mode='json')
    assert value['compounds'][0]['structure']=={'smiles':'CCO','molfile':None}

from sqlalchemy import select
from app.structures.models import Structure, StructureStatus, StructureInputMethod
from app.structures.service import StructureService
from app.compounds.models import Compound
from app.security.policies import Principal
from app.users.models import UserRole
from app.workspaces.validation import validate_submission
from app.workspaces.snapshot import build_paper_snapshot
from app.ai_tasks.repair_apply import apply_delta
from tests.ai_prefill.test_apply import ai_context
from tests.ai_tasks.test_repair_apply import baseline, args


def test_import_unknown_then_confirm_and_resolve_preserves_ids(ai_context,tmp_path):
    with ai_context.session_factory.begin() as s:
        raw=complete_payload();raw['compounds'][1]['structure']=absent()
        before,snapshot,refs=baseline(ai_context,s,raw)
        compound=s.scalar(select(Compound).where(Compound.compound_label=='Compound 18'))
        structure=s.scalar(select(Structure).where(Structure.compound_id==compound.id))
        assert structure.status==StructureStatus.DRAFT
        assert structure.canonical_smiles is None and structure.depiction_asset_id is None
        original_id=structure.id
        result=StructureService(tmp_path).upsert_structure(s,compound_id=compound.id,expected_version=snapshot['workspace_version'],actor=Principal(ai_context.reviewer_id,UserRole.REVIEWER),status=StructureStatus.REVIEWER_CONFIRMED,input_method=StructureInputMethod.MANUAL_SMILES,smiles=None,molfile=None,**absent())
        assert result.structure.id==original_id
        assert result.structure.status==StructureStatus.REVIEWER_CONFIRMED
        assert not any(b.entity_id==structure.id and b.code=='STRUCTURE_NOT_CONFIRMED' for b in validate_submission(s,ai_context.workspace_id).blockers)
        snapshot=build_paper_snapshot(s,ai_context.workspace_id)
        from app.workspaces.models import ChangeEvent
        from app.publications.reviewer_projection import reviewer_only_baseline
        from app.publications.comparison import _scientific_snapshot
        previous_events={e.id for e in s.scalars(select(ChangeEvent))}
        changed=before.model_dump(mode='json');changed['compounds'][1]['structure']={'smiles':'CCN','availability':'available'}
        apply_delta(s,after=AiPrefillPayload.model_validate(changed),automatic_revision=True,**args(ai_context,s,tmp_path,before,snapshot,refs))
        assert structure.id==original_id and structure.status==StructureStatus.DRAFT
        assert structure.availability=='available' and structure.canonical_smiles=='CCN'
        assert structure.identity_source is None
        events=[e for e in s.scalars(select(ChangeEvent).order_by(ChangeEvent.occurred_at,ChangeEvent.id)) if e.id not in previous_events]
        final=build_paper_snapshot(s,ai_context.workspace_id)
        projected,warnings=reviewer_only_baseline(final,events,verified_repair_ids={e.id for e in events},expected_start=snapshot)
        assert not warnings
        assert _scientific_snapshot(projected)==_scientific_snapshot(final)


def test_unknown_table_only_revision_preserves_entire_structure(ai_context,tmp_path):
    with ai_context.session_factory.begin() as s:
        raw=complete_payload();raw['compounds'][1]['structure']=absent();raw['activities'][0]['ref']='activity:a'
        before,snapshot,refs=baseline(ai_context,s,raw)
        changed=before.model_dump(mode='json');changed['activity_tables']=[dict(ref='table:1',name='Table 1',source_label='Table 1',columns=[dict(id='potency',label='IC50',assay='Cell potency',metric='IC50',unit='nM',activity_refs=['activity:a'])])]
        apply_delta(s,after=AiPrefillPayload.model_validate(changed),automatic_revision=True,**args(ai_context,s,tmp_path,before,snapshot,refs))
        after=build_paper_snapshot(s,ai_context.workspace_id)
        assert after['structures']==snapshot['structures']
        assert after['compounds']==snapshot['compounds']
        assert after['activities']==snapshot['activities']


def test_absent_identity_review_does_not_claim_structure_or_invalidate_activity():
    from app.ai_tasks.report_overview import build_overview
    from tests.ai_tasks.test_report_overview import candidate, inventory, row, by_domain
    from leadtrace.ops.ai_prefill.review_coverage import review_targets
    c=candidate();raw=c.model_dump(mode='json');raw['payload']['compounds'][0]['structure']=absent()
    c=type(c).model_validate(raw)
    targets=review_targets(c,inventory(c))
    assert targets['structures']==['c2'] and targets['compound_identity']==['c1']
    rows=[row('compound_identity','c1',['identity_source','checked_sources','availability','availability_note']),row('evidence','v1',['source','content','bbox']),row('activities','0',['compound','assay','metric','value','unit','operator','conditions','source'])]
    overview=build_overview(c,review_rows=rows,inventory=inventory(c))
    assert overview['compound_coverage']['covered']==2
    assert overview['structure_availability']['available']==1
    assert overview['structure_availability']['not_reported']==1
    assert by_domain(overview,'activities')['supported']==1


def test_availability_fields_survive_normalized_approval_and_legacy_undo():
    from app.publications.comparison import _normalized, _FIELDS
    from app.workspaces.edit_history import _convert
    historical={key:None for key in _FIELDS['structure'][1].split()}
    historical.update(id='s1',status='draft',input_method='ai_prefill')
    assert _normalized('structure',historical|absent())['availability']=='not_reported'
    assert 'availability' not in _normalized('structure',historical)
    assert _convert(Structure,{'smiles':'CC'})['availability'] is None


def test_forty_identities_with_six_missing_structures_keep_activity_and_table_refs(ai_context,tmp_path):
    from app.activities.models import Activity
    from app.activity_tables.models import ActivityTable
    from app.structures.availability import structure_counts
    compounds=[dict(ref=f'c:{i}',compound_label=str(i),structure={'smiles':'C'} if i<34 else absent()) for i in range(40)]
    activities=[dict(ref=f'a:{i}',compound_ref=f'c:{i}',assay_name='Binding',metric='IC50',operator='=',value=str(i+1),unit='nM') for i in range(40)]
    raw=dict(schema_version=1,compounds=compounds,activities=activities,activity_tables=[dict(ref='t:1',name='Table 1',source_label='Table 1',compound_refs=[c['ref'] for c in compounds],columns=[dict(id='potency',label='IC50',assay='Binding',metric='IC50',unit='nM',activity_refs=[a['ref'] for a in activities])])])
    with ai_context.session_factory.begin() as s:
        before,snapshot,refs=baseline(ai_context,s,raw)
        compound_rows=list(s.scalars(select(Compound)));structure_rows=list(s.scalars(select(Structure)))
        assert structure_counts(compound_rows,structure_rows)==dict(total=40,available=34,not_reported=6,not_checked=0,unresolved=0,confirmed=0)
        assert len(list(s.scalars(select(Activity))))==40
        table=s.scalar(select(ActivityTable));assert len(table.compound_ids)==40 and len(table.columns[0]['activity_ids'])==40
        assert len(before.compounds)==40 and len(before.activities)==40
        assert all(r.status==StructureStatus.DRAFT for r in structure_rows)
        blockers=validate_submission(s,ai_context.workspace_id).blockers
        assert len([b for b in blockers if b.code=='STRUCTURE_NOT_CONFIRMED'])==40


def test_malformed_confirmed_absence_blocks_submission(ai_context):
    with ai_context.session_factory.begin() as s:
        raw=complete_payload();raw['compounds'][1]['structure']=absent()
        baseline(ai_context,s,raw)
        row=s.scalar(select(Structure).where(Structure.availability=='not_reported'))
        row.status=StructureStatus.REVIEWER_CONFIRMED;row.identity_source=' ';s.flush()
        assert any(b.entity_id==row.id and b.code=='STRUCTURE_NOT_CONFIRMED' for b in validate_submission(s,ai_context.workspace_id).blockers)


@pytest.mark.parametrize('status',['not_reported','unresolved'])
def test_explicit_availability_cannot_use_legacy_review_disposition(ai_context,tmp_path,status):
    from app.structures.service import StructureValidationError
    with ai_context.session_factory.begin() as s:
        _,snapshot,_=baseline(ai_context,s)
        compound=s.scalar(select(Compound))
        with pytest.raises(StructureValidationError,match='Explicit availability'):
            StructureService(tmp_path).upsert_structure(s,compound_id=compound.id,expected_version=snapshot['workspace_version'],actor=Principal(ai_context.reviewer_id,UserRole.REVIEWER),status=StructureStatus(status),input_method=StructureInputMethod.MANUAL_SMILES,smiles='CC',molfile=None,availability='available')
