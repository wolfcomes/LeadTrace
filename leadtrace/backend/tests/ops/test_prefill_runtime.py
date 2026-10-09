from pathlib import Path
import json
import pytest
from leadtrace.ops.ai_prefill import tasks


def test_runtime_configuration_is_explicit_and_provider_specific(tmp_path):
    from leadtrace.ops.ai_prefill.runtime import RuntimeConfig, build_command
    cfg = RuntimeConfig(adapter='codex', model='gpt-test', reasoning_effort='high')
    command = build_command(cfg, tmp_path, '/bin/codex', 'synthetic prompt')
    assert command[1] == 'exec'
    assert command[command.index('--model')+1] == 'gpt-test'
    assert 'model_reasoning_effort="high"' in command
    assert '--skip-git-repo-check' in command
    assert '--sandbox' in command and 'workspace-write' in command
    assert not any('bypass' in x for x in command)
    with pytest.raises(ValueError): RuntimeConfig(adapter='codex', model='gpt-test', reasoning_effort='max')
    with pytest.raises(ValueError): RuntimeConfig(adapter='dsh', model='deepseek-flash', reasoning_effort='xhigh')
    with pytest.raises(ValueError): RuntimeConfig(adapter='codex', model='--bad', reasoning_effort='high')


def test_deepseek_model_and_effort_are_applied_in_local_patch(tmp_path):
    from leadtrace.ops.ai_prefill.runtime import RuntimeConfig, build_command
    cfg=RuntimeConfig(adapter='dsh', model='deepseek-flash', reasoning_effort='max')
    command=build_command(cfg,tmp_path,'/bin/dsh','prompt')
    assert command[command.index('--profile')+1]=='headless'
    patch=Path(command[command.index('--patch')+1]).read_text()
    assert 'deepseek-flash' in patch and 'max' in patch
    assert command[-1]=='prompt'


def test_tool_preflight_uses_selected_python_for_parse_and_render(tmp_path):
    from leadtrace.ops.ai_prefill.runtime import tool_preflight
    import sys
    result=tool_preflight(sys.executable)
    assert result['rdkit_parse_and_render'] is True
    assert result['pdf_tools'] is True
    with pytest.raises(ValueError):tool_preflight('/does/not/exist')


def test_observation_is_safe_and_mismatch_is_reported(tmp_path):
    from leadtrace.ops.ai_prefill.runtime import RuntimeConfig, observed_runtime
    cfg=RuntimeConfig(model='expected',reasoning_effort='high')
    path=tmp_path/'runtime-requests.jsonl'
    path.write_text('{broken\n'+json.dumps({'model':'actual','reasoning_effort':'max','thinking':'enabled','messages':'never expose'})+'\n')
    result=observed_runtime(tmp_path,cfg)
    assert result['verification']=='mismatch'
    assert result['metadata_incomplete'] is True
    assert 'never expose' not in json.dumps(result)


@pytest.mark.parametrize('defect', ['missing_domain', 'unknown_ref', 'empty_evidence'])
def test_full_review_must_cover_real_candidate_targets(tmp_path, defect):
    from .test_ai_prefill_tasks import inputs
    inp, _, candidate, inventory = inputs(tmp_path)
    job=tmp_path/'review'
    tasks.prepare_task(entry='review', input_path=inp, output=job, candidate_path=candidate, inventory_path=inventory)
    task=json.loads((job/'task.json').read_text())
    row={'domain':'structures','ref':json.loads(candidate.read_text())['payload']['compounds'][0]['ref'],
         'expected':'synthetic','observed':'synthetic','source_locations':['synthetic p1'],
         'checked_fields':['connectivity'],'field_results':{'connectivity':'correct'},'reason':'Synthetic fixture only','verdict':'correct'}
    if defect=='unknown_ref': row['ref']='not-in-candidate'
    if defect=='empty_evidence': row['checked_fields']=[];row['field_results']={}
    (job/'outputs/items.json').write_text(json.dumps([row]))
    report={'candidate_file_sha256':task['baseline']['candidate_file_sha256'],'source_sha256':task['source']['source_sha256'],
            'complete_scope':True,'unreviewed_scope':[],'scientific_approval':False,'item_reports':['items.json']}
    (job/'outputs/audit-summary.json').write_text(json.dumps(report))
    if defect=='missing_domain':
        state,details=tasks._postflight(job,task)
        assert state=='partial' and details['missing_review_targets']
    else:
        with pytest.raises(ValueError):tasks._postflight(job,task)


def test_review_coverage_accepts_complete_rows_and_rejects_duplicates():
    from leadtrace.ops.ai_prefill.review_coverage import check_review_rows
    row={'domain':'edges','ref':'edge-a','expected':'synthetic','observed':'synthetic',
         'source_locations':['p1'], 'checked_fields':['direction'],'field_results':{'direction':'uncertain'},
         'reason':'Synthetic uncertain evidence','verdict':'uncertain'}
    result=check_review_rows({'edges':['edge-a']},[row])
    assert result['missing']==[] and result['scientific_approval'] is False
    with pytest.raises(ValueError,match='Duplicate'):
        check_review_rows({'edges':['edge-a']},[row,row])


def test_producer_report_preserves_declared_omissions_without_source_reads(tmp_path):
    from app.ai_prefill.assistance_contracts import CandidateEnvelope
    from app.ai_tasks.producer_report import producer_report
    candidate=CandidateEnvelope.model_validate_json((Path(__file__).resolve().parents[4]/'docs/ai-prefill/examples/candidate-v1.json').read_bytes())
    from app.ai_prefill.assistance_contracts import CandidateOmission
    candidate=candidate.model_copy(update={'omissions':[CandidateOmission(path='payload.compounds',reason='Synthetic positional identity unresolved')]})
    raw=candidate.model_dump_json().encode()
    report=producer_report(tmp_path,candidate,raw)
    assert any(x['domain']=='DECLARED_OMISSION' and x['reason']=='Synthetic positional identity unresolved' for x in report['findings'])
    assert report['coverage_known'] is False


def test_producer_report_keeps_semantic_checks_when_inventory_is_missing(tmp_path):
    from app.ai_prefill.assistance_contracts import CandidateEnvelope
    from app.ai_prefill.contracts import AiPrefillPayload
    from app.ai_tasks.producer_report import producer_report
    candidate=CandidateEnvelope.model_validate_json((Path(__file__).resolve().parents[4]/'docs/ai-prefill/examples/candidate-v1.json').read_bytes())
    payload=AiPrefillPayload.model_validate({'schema_version':1,'compounds':[{'ref':'c','compound_label':'1','structure':{'smiles':'C'}}], 'activities':[{'compound_ref':'c','assay_name':'test','metric':'dose','operator':'=','value':10,'unit':'mg/kg'}]})
    candidate=candidate.model_copy(update={'payload':payload,'hashes':None})
    report=producer_report(tmp_path,candidate,candidate.model_dump_json().encode())
    assert report['coverage_known'] is False
    assert any(x['domain']=='DOSE_AS_ENDPOINT' for x in report['findings'])
