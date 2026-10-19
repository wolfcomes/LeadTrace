from copy import deepcopy
import pytest
from pydantic import ValidationError
from app.ai_prefill.contracts import AiPrefillPayload
from app.ai_tasks.repair_apply import design_diff
from tests.ai_prefill.test_contract import complete_payload


def table_payload():
    data = complete_payload()
    for i, activity in enumerate(data['activities']):
        activity['ref'] = f'a{i}'
    a = data['activities'][0]
    data['activity_tables'] = [dict(ref='table1', name='Table 1', source_label='Table 1', columns=[dict(
        id='column1', label='Potency', assay=a['assay_name'], metric=a['metric'], unit=a.get('unit'), activity_refs=['a0'])])]
    return data


def test_legacy_absent_fields_do_not_change_serialization():
    result = AiPrefillPayload.model_validate(complete_payload()).model_dump(mode='json')
    assert 'activity_tables' not in result
    assert all('ref' not in row for row in result['activities'])


@pytest.mark.parametrize('invalid', ['missing', 'measurement', 'duplicate', 'label'])
def test_table_rejects_invalid_references(invalid):
    data = table_payload(); table = data['activity_tables'][0]; col = table['columns'][0]
    if invalid == 'missing': col['activity_refs'] = ['unknown']
    if invalid == 'measurement': col['metric'] = 'different'
    if invalid == 'duplicate': col['activity_refs'] *= 2
    if invalid == 'label': table['source_label'] = ''
    with pytest.raises(ValidationError): AiPrefillPayload.model_validate(data)


def test_table_only_revision_preserves_activities_even_when_reordered():
    raw = table_payload(); before = AiPrefillPayload.model_validate(raw)
    raw['activity_tables'][0]['name'] = 'Potency table'
    raw['activities'].reverse()
    diff = design_diff(before, AiPrefillPayload.model_validate(raw))
    assert [(x['domain'], x['action']) for x in diff['changes']] == [('activity_tables', 'update')]


def test_stable_refs_disambiguate_identical_records_and_reject_identity_recycling():
    raw = table_payload(); second = deepcopy(raw['activities'][0]); second['ref']='a1'
    raw['activities'].append(second); before=AiPrefillPayload.model_validate(raw)
    raw['activities'].reverse();raw['activities'][0]['value']='123'
    diff=design_diff(before,AiPrefillPayload.model_validate(raw))
    assert len(diff['changes'])==1
    assert diff['changes'][0]['ref']=='activity:1'
    raw['activities'][0]['ref']='replacement'
    diff=design_diff(before,AiPrefillPayload.model_validate(raw))
    assert diff['counts']['activities']=={'added':1,'removed':1,'updated':0}


def test_table_page_and_refs_checked_by_candidate_validator():
    from tests.ai_prefill.test_assistance_validation import make
    from app.ai_prefill.assistance_validation import validate_candidate
    raw=table_payload();raw['activity_tables'][0]['ref']='bad/ref';raw['activity_tables'][0]['page_number']=999
    report=validate_candidate(make(AiPrefillPayload.model_validate(raw)))
    assert not report.can_apply
    codes={issue.code for issue in report.issues}
    assert {'UNSAFE_ENTITY_REF','PAGE_OUT_OF_RANGE'}<=codes


def test_revision_cannot_drop_stable_activity_refs():
    from app.ai_tasks.repair import require_explicit_collections
    raw=table_payload();before=AiPrefillPayload.model_validate(raw)
    del raw['activities'][0]['ref']
    with pytest.raises(ValueError,match='stable Activity refs'):
        require_explicit_collections(before,raw)


def test_receipt_table_and_explicit_activity_ref_paths_are_verified():
    from app.ai_prefill.assistance_verification import _entity_model
    from app.activities.models import Activity
    from app.activity_tables.models import ActivityTable
    assert _entity_model('/activities/0') is Activity
    assert _entity_model('/activity_refs/0') is Activity
    assert _entity_model('/activity_tables/table1') is ActivityTable


def row_evidence_payload():
    raw = table_payload()
    raw['evidence'][0]['kind'] = 'table'
    table = raw['activity_tables'][0]
    table['compound_refs'] = [c['ref'] for c in reversed(raw['compounds'])]
    table['evidence_refs'] = [raw['evidence'][0]['ref']]
    return raw


def test_table_rows_and_evidence_roundtrip_preserves_explicit_order_and_empty_rows():
    raw = row_evidence_payload()
    result = AiPrefillPayload.model_validate(raw).model_dump(mode='json')
    assert result['activity_tables'][0]['compound_refs'] == raw['activity_tables'][0]['compound_refs']
    assert result['activity_tables'][0]['evidence_refs'] == raw['activity_tables'][0]['evidence_refs']
    raw['activity_tables'][0]['compound_refs'] = []
    raw['activity_tables'][0]['columns'] = []
    assert AiPrefillPayload.model_validate(raw).model_dump(mode='json')['activity_tables'][0]['compound_refs'] == []


def test_legacy_table_serialization_omits_new_default_fields():
    before = AiPrefillPayload.model_validate(table_payload()).model_dump(mode='json')
    assert 'compound_refs' not in before['activity_tables'][0]
    assert 'evidence_refs' not in before['activity_tables'][0]
    raw = table_payload()
    raw['activity_tables'][0].update(compound_refs=None, evidence_refs=[])
    assert AiPrefillPayload.model_validate(raw).model_dump(mode='json') == before


@pytest.mark.parametrize('invalid', ['unknown_compound', 'duplicate_compound', 'outside_rows', 'unknown_evidence', 'duplicate_evidence', 'wrong_kind', 'missing_bbox'])
def test_table_rejects_invalid_rows_and_source_evidence(invalid):
    raw = row_evidence_payload()
    table = raw['activity_tables'][0]
    if invalid == 'unknown_compound': table['compound_refs'].append('missing')
    if invalid == 'duplicate_compound': table['compound_refs'] *= 2
    if invalid == 'outside_rows': table['compound_refs'] = []
    if invalid == 'unknown_evidence': table['evidence_refs'] = ['missing']
    if invalid == 'duplicate_evidence': table['evidence_refs'] *= 2
    if invalid == 'wrong_kind': raw['evidence'][0]['kind'] = 'scheme'
    if invalid == 'missing_bbox': raw['evidence'][0]['bbox'] = None
    with pytest.raises(ValidationError):
        AiPrefillPayload.model_validate(raw)


def test_row_and_evidence_only_revision_does_not_change_scientific_records():
    raw = table_payload()
    raw['evidence'][0]['kind'] = 'table'
    before = AiPrefillPayload.model_validate(raw)
    raw['activity_tables'][0].update(compound_refs=[raw['activities'][0]['compound_ref']], evidence_refs=[raw['evidence'][0]['ref']])
    diff = design_diff(before, AiPrefillPayload.model_validate(raw))
    assert [(c['domain'], c['action']) for c in diff['changes']] == [('activity_tables', 'update')]


@pytest.mark.parametrize('field', ['compound_refs', 'evidence_refs'])
def test_repair_must_explicitly_preserve_or_clear_existing_table_scope(field):
    from app.ai_tasks.repair import require_explicit_collections
    raw = row_evidence_payload()
    before = AiPrefillPayload.model_validate(raw)
    del raw['activity_tables'][0][field]
    with pytest.raises(ValueError, match='table'):
        require_explicit_collections(before, raw)
    raw['activity_tables'][0][field] = None if field == 'compound_refs' else []
    require_explicit_collections(before, raw)
