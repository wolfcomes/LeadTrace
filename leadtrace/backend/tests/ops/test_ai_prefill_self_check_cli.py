import json
from pathlib import Path

from leadtrace.ops.ai_prefill.cli import main


def inputs(tmp_path):
    example = Path(__file__).resolve().parents[4] / 'docs/ai-prefill/examples/candidate-v1.json'
    c = json.loads(example.read_text()); c['hashes'] = None
    c['payload'] = {'schema_version': 1, 'compounds': [
        {'ref': 'c1', 'compound_label': '1', 'structure': {'smiles': 'CCO'}}],
        'activities': [], 'lineages': []}
    inv = {'inventory_version': 1, 'source': c['source'], 'scope': 'main text',
           'reviewed_by': 'source reviewer', 'entries': [{'label':'1','required':True,'role':'assayed','source_locator':'Table1'}]}
    p, i = tmp_path/'candidate.json', tmp_path/'inventory.json'
    p.write_text(json.dumps(c)); i.write_text(json.dumps(inv)); return p,i


def activity(metric='IC50', unit='uM', value=1, operator='='):
    return dict(compound_ref='c1', assay_name='assay', metric=metric, unit=unit, value=value, operator=operator)


def edit(p, **payload):
    c=json.loads(p.read_text()); c['payload'].update(payload);p.write_text(json.dumps(c))


def run(p,i,capsys,*extra):
    code=main(['candidate','self-check',str(p),'--inventory',str(i),*extra]);return code,json.loads(capsys.readouterr().out)


def codes(r):return {x['code'] for x in r['issues']}


def test_real_failure_patterns_report_without_mutating_candidate(tmp_path,capsys):
    p,i=inputs(tmp_path);edit(p,activities=[activity('oral dose','mg/kg'),activity('Selectivity index S.I. (EAhy926/RPMI8226)','uM')]);before=p.read_bytes()
    code,r=run(p,i,capsys)
    assert code==4
    assert {'DOSE_AS_ENDPOINT','DIMENSIONLESS_METRIC_UNIT','SELF_REVIEW_MISSING'}<=codes(r)
    assert p.read_bytes()==before
    assert r['scientific_approval'] is False


def test_dose_derived_endpoints_and_real_thresholds_not_flagged(tmp_path,capsys):
    p,i=inputs(tmp_path);edit(p,activities=[activity('ED50','mg/kg'),activity('Maximum tolerated dose','mg/kg'),activity('IC50','uM',20,'>'),activity('inhibition','%',-5),activity('S.I.',None)])
    _,r=run(p,i,capsys)
    assert 'DOSE_AS_ENDPOINT' not in codes(r)
    assert 'DIMENSIONLESS_METRIC_UNIT' not in codes(r)


def test_missing_compound_not_excused_by_omission(tmp_path,capsys):
    p,i=inputs(tmp_path);x=json.loads(i.read_text());x['entries'].append(dict(label='2',required=True,role='control',source_locator='Fig1'));i.write_text(json.dumps(x))
    _,r=run(p,i,capsys);assert 'COMPOUND_COVERAGE_INCOMPLETE' in codes(r)


def test_duplicate_and_untyped_lineage_reported(tmp_path,capsys):
    p,i=inputs(tmp_path);edit(p,activities=[activity(),activity()],lineages=[dict(ref='l1',lineage_label='series')])
    _,r=run(p,i,capsys);assert {'DUPLICATE_ACTIVITY','LINEAGE_TYPE_MISSING'}<=codes(r)


def review(p):
    import hashlib
    from app.ai_prefill.assistance_self_check import SOURCE_REVIEW_CHECKS
    return {'self_review_version':1,'candidate_file_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
            'reviewer_type':'producer_self_check','checks':[{'check_id':x,'status':'checked','details':'Checked the stated scope; no claim of full population accuracy.','source_locations':['PDF p1 Table1'], 'checked_edge_refs':[]} for x in SOURCE_REVIEW_CHECKS]}


def test_bound_review_can_be_ready_but_never_scientific_approval(tmp_path,capsys):
    p,i=inputs(tmp_path);j=tmp_path/'self-review.json';j.write_text(json.dumps(review(p)))
    output=tmp_path/'result.json';code,r=run(p,i,capsys,'--self-review',str(j),'--output',str(output))
    assert code==0 and r['status']=='ready_for_independent_review'
    assert r['scientific_approval'] is False and json.loads(output.read_text())==r
    assert r['whole_population_accuracy'] is None


def test_stale_source_review_and_phantom_edge_block_handoff(tmp_path,capsys):
    p,i=inputs(tmp_path);x=review(p);x['candidate_file_sha256']='0'*64;x['checks'][0]['checked_edge_refs']=['phantom'];j=tmp_path/'review.json';j.write_text(json.dumps(x))
    code,r=run(p,i,capsys,'--self-review',str(j));assert code==4
    assert {'SELF_REVIEW_STALE','SELF_REVIEW_UNKNOWN_EDGE'}<=codes(r)


def test_missing_and_unresolved_source_checks_do_not_pass(tmp_path,capsys):
    p,i=inputs(tmp_path);x=review(p);x['checks'].pop();x['checks'][0]['status']='unresolved';j=tmp_path/'review.json';j.write_text(json.dumps(x))
    code,r=run(p,i,capsys,'--self-review',str(j));assert code==4
    assert {'SELF_REVIEW_INCOMPLETE','SOURCE_REVIEW_UNRESOLVED'}<=codes(r)


def test_cannot_overwrite_input_with_output(tmp_path,capsys):
    p,i=inputs(tmp_path);before=p.read_bytes()
    assert run(p,i,capsys,'--output',str(p))[0]==2
    assert p.read_bytes()==before


def test_inventory_required(tmp_path,capsys):
    p,_=inputs(tmp_path)
    assert main(['candidate','self-check',str(p)])==2
    assert json.loads(capsys.readouterr().out)['code']=='INVENTORY_REQUIRED'


def test_inferred_sar_without_evidence_is_allowed(tmp_path,capsys):
    p,i=inputs(tmp_path);c=json.loads(p.read_text());c['payload']['compounds'].append({'ref':'c2','compound_label':'2','structure':{'smiles':'CCN'}})
    c['payload']['lineages']=[{'ref':'sar','lineage_label':'SAR','lineage_type':'sar','members':[{'compound_ref':'c1','role':'root'},{'compound_ref':'c2','role':'terminal'}],'edges':[{'ref':'edge1','parent_compound_ref':'c1','child_compound_ref':'c2','relation_type':'analog','modification_summary':'AI inference: replace O with N'}]}];p.write_text(json.dumps(c))
    j=tmp_path/'self-review.json';j.write_text(json.dumps(review(p)))
    code,r=run(p,i,capsys,'--self-review',str(j))
    assert code==0 and 'EDGE_WITHOUT_SUPPORTING_EVIDENCE' in codes(r)
    assert not any(x['code']=='EDGE_WITHOUT_SUPPORTING_EVIDENCE' and x['severity']=='blocking' for x in r['issues'])


def test_review_duplicate_check_and_false_waiver_rejected(tmp_path,capsys):
    p,i=inputs(tmp_path);x=review(p);x['checks'].append(x['checks'][0]);j=tmp_path/'review.json';j.write_text(json.dumps(x))
    assert run(p,i,capsys,'--self-review',str(j))[0]==2
    x['checks'].pop();x['checks'][0]['status']='not_applicable';j.write_text(json.dumps(x))
    code,r=run(p,i,capsys,'--self-review',str(j));assert code==4 and 'SELF_REVIEW_INVALID_WAIVER' in codes(r)


def test_changed_conditions_or_evidence_not_duplicate(tmp_path,capsys):
    p,i=inputs(tmp_path);a=activity();a['context']='24 h';b=activity();b['context']='72 h';edit(p,activities=[a,b])
    _,r=run(p,i,capsys);assert 'DUPLICATE_ACTIVITY' not in codes(r)
