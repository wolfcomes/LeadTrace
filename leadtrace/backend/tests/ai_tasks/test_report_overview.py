"""Statistics must never turn missing checks into scientific confidence."""
from hashlib import sha256
import json

import pytest

from app.ai_prefill.assistance_contracts import CandidateEnvelope
from app.ai_prefill.assistance_coverage import CompoundInventory
from app.ai_tasks.report_overview import build_overview, read_review_rows, actionable_review_rows


def candidate():
    return CandidateEnvelope.model_validate({
        'envelope_version': 1, 'candidate_id': 'test-candidate', 'experiment_id': 'test',
        'source': {'paper_key': 'test', 'source_sha256': 'a'*64, 'byte_size': 1, 'page_count': 2},
        'producer': {'kind': 'local', 'engine': 'synthetic', 'engine_version': 'test', 'generated_at': '2026-10-09T00:00:00Z'},
        'recipe': {'guide_version': 'test'}, 'payload': {
            'schema_version': 1,
            'compounds': [{'ref': 'c1', 'compound_label': '1', 'structure': {'smiles': 'C'}},
                          {'ref': 'c2', 'compound_label': '2', 'structure': {'smiles': 'CC'}, 'review_hint': 'Check identity'}],
            'structure_locators': [{'ref': ref, 'compound_ref': compound, 'page_number': 1,
                'bbox': {'x0': 0.1, 'y0': 0.1, 'x1': 0.9, 'y1': 0.9}} for ref, compound in [('s1','c1'),('s2','c1'),('s3','c2')]],
            'activities': [{'compound_ref': 'c1', 'assay_name': 'binding', 'metric': 'IC50', 'operator': '=', 'value': 1, 'unit': 'nM', 'evidence_ref': 'v1'}],
            'lineages': [{'ref': 'g1', 'lineage_label': 'test', 'lineage_type': 'sar',
                'members': [{'compound_ref': 'c1','role': 'root'}, {'compound_ref': 'c2','role': 'terminal'}],
                'edges': [{'ref': 'e1','parent_compound_ref': 'c1','child_compound_ref': 'c2','relation_type': 'optimization'}]}],
            'evidence': [{'ref': 'v1','kind': 'table','page_number': 1,'bbox': {'x0': .1,'y0': .1,'x1': .9,'y1': .9}}],
            'edge_evidence_links': [{'edge_ref': 'e1','evidence_ref': 'v1','role': 'supports'}]}})


def inventory(c):
    return CompoundInventory.model_validate({'source': c.source.model_dump(mode='json'), 'scope':'test', 'reviewed_by':'synthetic',
        'entries': [{'label': str(i), 'role':'test','source_locator':'p1'} for i in range(1,4)]})


def row(domain, ref, fields, verdict='correct'):
    return {'domain':domain,'ref':ref,'verdict':verdict,'reason':'Synthetic fixture', 'source_locations':['p1'],
        'expected': 'source expectation', 'observed':'candidate observation','checked_fields':fields,
        'field_results':{f:verdict for f in fields}}


def structure(ref, verdict='correct'):
    return row('structures',ref,['connectivity','regiochemistry','stereochemistry','chemical_form'],verdict)


def by_domain(result, domain):
    return next(x for x in result['entities'] if x['domain']==domain)


def test_producer_totals_and_known_inventory_do_not_imply_accuracy():
    c=candidate()
    result=build_overview(c, inventory=inventory(c), producer_report={'checks':[{'status':'checked'}], 'coverage_known':True})
    assert result['basis']=='producer'
    assert result['compound_coverage']=={'known':True,'covered':2,'expected':3,'percent':66.7}
    compounds=by_domain(result,'compounds')
    assert compounds=={'domain':'compounds','total':2,'supported':None,'incorrect':None,'uncertain':None,'unreviewed':2,'flagged':1}
    assert result['audit_coverage']['known'] is False
    assert by_domain(result,'screenshots')['total']==3
    assert result['screenshot_counts']=={'structure_occurrences':2,'evidence_crops':1,'unique_crop_regions':1}
    assert result['unique_crop_regions']==1


def test_unknown_inventory_stays_unknown_even_with_candidate_and_unbound_report():
    c=candidate()
    result=build_overview(c, producer_report={'coverage_known': True,'coverage':{'expected':2,'reviewed':2}})
    assert result['compound_coverage']=={'known':False,'covered':None,'expected':None,'percent':None}
    inv=inventory(c).model_copy(update={'source':c.source.model_copy(update={'source_sha256':'b'*64})})
    assert build_overview(c,inventory=inv)['compound_coverage']['known'] is False


def test_review_requires_full_field_checks_and_keeps_missing_unreviewed():
    c=candidate()
    partial=row('structures','c1',['connectivity'])
    result=build_overview(c,review_rows=[partial],inventory=inventory(c))
    assert by_domain(result,'compounds')=={'domain':'compounds','total':2,'supported':0,'incorrect':0,'uncertain':1,'unreviewed':1,'flagged':2}
    result=build_overview(c,review_rows=[structure('c1')],inventory=inventory(c))
    assert by_domain(result,'compounds')['supported']==1
    assert result['audit_coverage']['checked']==1
    assert result['audit_coverage']['percent']<100


def test_field_error_overrides_correct_verdict_and_propagates_to_checked_dependencies():
    c=candidate()
    bad=structure('c1');bad['field_results']['connectivity']='incorrect'
    activity=row('activities','0',['compound','assay','metric','value','unit','operator','conditions','source'])
    edge=row('edges','e1',['type','endpoints','direction','basis'])
    result=build_overview(c,review_rows=[bad,structure('c2'),activity,edge],inventory=inventory(c))
    assert by_domain(result,'compounds')['incorrect']==1
    assert by_domain(result,'activities')['incorrect']==1
    assert by_domain(result,'edges')['incorrect']==1
    assert by_domain(result,'lineages')['unreviewed']==1


def test_unstructured_field_result_is_uncertain_and_warnings_are_not_errors():
    c=candidate();r=structure('c1');r['field_results']['connectivity']='Looks fine to me'
    result=build_overview(c,review_rows=[r],inventory=inventory(c),producer_report={
        'findings':[{'domain':'LINEAGE_DISCONNECTED','ref':'payload.lineages[0]','verdict':'review','reason':'Check grouping'}]})
    assert by_domain(result,'compounds')['supported']==0
    assert by_domain(result,'compounds')['uncertain']==1
    assert by_domain(result,'lineages')['incorrect']==0
    assert result['issue_groups']==[{'code':'LINEAGE_DISCONNECTED','count':1},
                                    {'code':'REVIEW_UNCERTAIN_STRUCTURES','count':1}]


@pytest.mark.parametrize('rows', [[structure('c1'),structure('c1')], [structure('foreign')], [{'domain':'structures','ref':'c1','verdict':'correct'}]])
def test_invalid_review_rows_are_rejected(rows):
    with pytest.raises(ValueError):build_overview(candidate(),review_rows=rows,inventory=inventory(candidate()))


def test_bounded_exception_highlights_and_group_counts():
    findings=[{'domain':'SAME_CODE','ref':str(i),'reason':'x'*5000} for i in range(20)]
    result=build_overview(candidate(),producer_report={'findings':findings})
    assert result['issue_groups']==[{'code':'SAME_CODE','count':20}]
    assert len(result['highlights'])<=3
    assert all(len(x['summary'])<=500 for x in result['highlights'])


def test_duplicate_crop_refs_do_not_inflate_counts_or_hide_a_conflicting_review():
    c=candidate()
    rows=[row('locators','s1',['identity','bbox','source']),
          row('locators','s2',['identity','bbox','source'],'incorrect')]
    result=build_overview(c,review_rows=rows,inventory=inventory(c))
    screenshots=by_domain(result,'screenshots')
    assert screenshots['total']==3
    assert screenshots['incorrect']==1
    assert screenshots['supported']==0
    assert screenshots['unreviewed']==2


def test_all_row_coverage_is_not_all_field_confidence():
    from leadtrace.ops.ai_prefill.review_coverage import review_targets
    c=candidate();inv=inventory(c)
    rows=[row(domain,ref,['connectivity']) for domain,refs in review_targets(c,inv).items() for ref in refs]
    result=build_overview(c,review_rows=rows,inventory=inv)
    assert result['audit_coverage']['percent']==100
    assert all(item['supported']==0 for item in result['entities'])
    assert all(item['unreviewed']==0 for item in result['entities'])
    assert all(item['uncertain']==item['total'] for item in result['entities'])


def test_explicit_complete_checks_can_support_entities_without_clearing_saved_hints():
    c=candidate()
    rows=[structure('c1'),structure('c2'),
          row('activities','0',['compound','assay','metric','value','unit','operator','conditions','source']),
          row('edges','e1',['type','endpoints','direction','basis']),
          row('groups','g1',['type','scope','components','roles']),
          row('evidence','v1',['source','content','bbox']),
          row('edge_evidence_links','0',['identity','role']),
          *[row('locators',ref,['identity','bbox','source']) for ref in ['s1','s2','s3']]]
    result=build_overview(c,review_rows=rows,inventory=inventory(c))
    assert all(item['supported']==item['total'] for item in result['entities'])
    assert by_domain(result,'compounds')['flagged']==1
    assert c.payload.compounds[1].review_hint=='Check identity'
    assert result['audit_coverage']['percent']<100


def test_structured_field_errors_outside_checked_fields_are_not_hidden():
    r=structure('c1');r['field_results']['salt_form']={'verdict':'incorrect','reason':'wrong salt'}
    result=build_overview(candidate(),review_rows=[r])
    assert by_domain(result,'compounds')['incorrect']==1


def test_zero_count_domains_do_not_fabricate_a_confidence_percentage():
    c=candidate();c.payload=c.payload.model_copy(update={'activities':[], 'lineages':[], 'edge_evidence_links':[]})
    result=build_overview(c,review_rows=[])
    assert by_domain(result,'activities')['total']==0
    assert by_domain(result,'activities')['supported']==0
    assert result['audit_coverage']['percent']==0
    assert result['compound_coverage']['percent'] is None


def test_actionable_rows_expose_field_errors_and_preserve_original_evidence():
    original=structure('c1');original['field_results']['connectivity']={'verdict':'incorrect','reason':'wrong connection'}
    result=actionable_review_rows(candidate(),[original])
    assert len(result)==1
    fixed=result[0]
    assert fixed['verdict']=='incorrect'
    assert fixed['original_verdict']=='correct'
    assert fixed['original_reason']==original['reason']
    assert fixed['reason']!=original['reason']
    for key in ['expected','observed','checked_fields','field_results','source_locations']:
        assert fixed[key]==original[key]
    assert original['verdict']=='correct'


def test_actionable_rows_include_partial_core_fields_but_keep_unmapped_domains():
    partial=row('structures','c1',['connectivity'])
    correct=structure('c2')
    generic=[row(domain,'source',['identity']) for domain in ['source_identity','bibliography','highlights','inventory','participation']]
    result=actionable_review_rows(candidate(),[partial,correct,*generic])
    assert [(item['domain'],item['verdict']) for item in result]==[('structures','uncertain')]
    assert 'incomplete' in result[0]['reason'].lower()


def test_actionable_rows_keep_declared_findings_and_explicit_generic_field_uncertainty():
    existing=structure('c1','incorrect')
    generic=row('source_identity','source',['identity']);generic['field_results']['identity']='uncertain'
    assert actionable_review_rows(candidate(),[existing])[0]==existing
    assert actionable_review_rows(candidate(),[generic])[0]['verdict']=='uncertain'


def test_actionable_rows_require_steps_only_for_synthesis_and_bbox_for_cropped_evidence():
    c=candidate()
    edge=row('edges','e1',['type','endpoints','direction','basis'])
    evidence=row('evidence','v1',['source','content'])
    assert actionable_review_rows(c,[edge])==[]
    c.payload.lineages[0].lineage_type='synthesis'
    assert actionable_review_rows(c,[edge])[0]['verdict']=='uncertain'
    assert actionable_review_rows(c,[evidence])[0]['verdict']=='uncertain'


def write_review(directory, c, rows):
    raw=c.model_dump_json().encode();(directory/'inputs').mkdir();(directory/'outputs').mkdir()
    (directory/'inputs/compound-inventory.json').write_text(inventory(c).model_dump_json())
    (directory/'outputs/rows.json').write_text(json.dumps(rows))
    (directory/'outputs/audit-summary.json').write_text(json.dumps({'candidate_file_sha256':sha256(raw).hexdigest(),
        'source_sha256':c.source.source_sha256, 'scientific_approval':False,'item_reports':['rows.json']}))
    return raw


def test_review_reader_binds_candidate_and_source_and_rejects_stale_or_unsafe_rows(tmp_path):
    c=candidate();rows=[structure('c1')];raw=write_review(tmp_path,c,rows)
    assert read_review_rows(tmp_path,raw)==rows
    with pytest.raises(ValueError):read_review_rows(tmp_path,raw+b' ')
    path=tmp_path/'outputs/audit-summary.json';summary=json.loads(path.read_text())
    summary['source_sha256']='b'*64;path.write_text(json.dumps(summary))
    with pytest.raises(ValueError):read_review_rows(tmp_path,raw)


def test_review_reader_rejects_duplicate_files_and_symlinks(tmp_path):
    c=candidate();raw=write_review(tmp_path,c,[structure('c1')])
    path=tmp_path/'outputs/audit-summary.json';summary=json.loads(path.read_text())
    summary['item_reports']=['rows.json','rows.json'];path.write_text(json.dumps(summary))
    with pytest.raises(ValueError,match='Duplicate'):read_review_rows(tmp_path,raw)
    summary['item_reports']=['link.json'];path.write_text(json.dumps(summary))
    (tmp_path/'outputs/link.json').symlink_to(tmp_path/'outputs/rows.json')
    with pytest.raises(ValueError):read_review_rows(tmp_path,raw)
    summary['source_sha256']=c.source.source_sha256;summary['item_reports']=['../inputs/compound-inventory.json'];path.write_text(json.dumps(summary))
    with pytest.raises(ValueError):read_review_rows(tmp_path,raw)


@pytest.mark.parametrize('name',['rows.json','outputs/rows.json'])
def test_review_reader_accepts_output_relative_and_task_relative_paths(tmp_path,name):
    c=candidate();rows=[structure('c1')];raw=write_review(tmp_path,c,rows)
    path=tmp_path/'outputs/audit-summary.json';summary=json.loads(path.read_text())
    summary['item_reports']=[name];path.write_text(json.dumps(summary))
    assert read_review_rows(tmp_path,raw)==rows


@pytest.mark.parametrize('name',['outputs/../inputs/compound-inventory.json','/outputs/rows.json','outputs/link.json'])
def test_prefixed_review_paths_cannot_escape_or_follow_symlinks(tmp_path,name):
    c=candidate();raw=write_review(tmp_path,c,[structure('c1')])
    (tmp_path/'outputs/link.json').symlink_to(tmp_path/'outputs/rows.json')
    path=tmp_path/'outputs/audit-summary.json';summary=json.loads(path.read_text())
    summary['item_reports']=[name];path.write_text(json.dumps(summary))
    with pytest.raises(ValueError):read_review_rows(tmp_path,raw)
