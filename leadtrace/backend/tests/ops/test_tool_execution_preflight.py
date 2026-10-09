import json,os,sys
from pathlib import Path
import pytest
from leadtrace.ops.ai_prefill.tool_execution_preflight import codex_execution_preflight,ToolExecutionUnavailable


def adapter(tmp_path, *, failure=False):
    script=tmp_path/'adapter.py'
    script.write_text('''import sys,json
from pathlib import Path
for line in sys.stdin:
 r=json.loads(line)
 if 'id' not in r:continue
 if r['method']=='initialize':result={}
 elif r['method']=='command/exec':
  assert r['params']['sandboxPolicy']['type']=='externalSandbox'
  assert r['params']['sandboxPolicy']['networkAccess']=='enabled'
  '''+('result={"exitCode":1,"stderr":"synthetic sandbox failure"}' if failure else 'Path("probe.txt").write_text("leadtrace-tool-ok");result={"exitCode":0}')+'''
 else:raise AssertionError('Must not create a model turn')
 print(json.dumps({'id':r['id'],'result':result}),flush=True)
''')
    return script


def test_preflight_uses_actual_tool_protocol_without_model_turn(tmp_path,monkeypatch):
    from leadtrace.ops.ai_prefill import sandbox
    script=adapter(tmp_path)
    monkeypatch.setattr(sandbox,'require_sandbox_cleanup',lambda *a,**kw:None)
    monkeypatch.setattr(sandbox,'sandbox_command',lambda *a,**kw:([sys.executable,str(script)],dict(os.environ)))
    assert codex_execution_preflight('synthetic',sys.executable,dict(os.environ))['model_calls']==0


def test_preflight_failure_is_safe_and_explicit(tmp_path,monkeypatch):
    from leadtrace.ops.ai_prefill import sandbox
    script=adapter(tmp_path,failure=True)
    monkeypatch.setattr(sandbox,'require_sandbox_cleanup',lambda *a,**kw:None)
    monkeypatch.setattr(sandbox,'sandbox_command',lambda *a,**kw:([sys.executable,str(script)],dict(os.environ)))
    with pytest.raises(ToolExecutionUnavailable) as error:codex_execution_preflight('synthetic',sys.executable,dict(os.environ))
    assert error.value.code=='TOOL_EXECUTION_UNAVAILABLE'
    assert 'synthetic sandbox failure' not in str(error.value)


def test_failed_preflight_prevents_producer_launch(tmp_path,monkeypatch):
    from .test_ai_prefill_tasks import inputs
    from leadtrace.ops.ai_prefill import tasks,tool_execution_preflight
    inp,_,_,_=inputs(tmp_path)
    job=tmp_path/'job'
    tasks.prepare_task(entry='prefill',input_path=inp,output=job,adapter='codex',model='gpt-test',reasoning_effort='high')
    def unavailable(*a,**kw):raise ToolExecutionUnavailable()
    monkeypatch.setattr(tool_execution_preflight,'codex_execution_preflight',unavailable)
    with pytest.raises(ToolExecutionUnavailable):tasks.run_task(job,executable=sys.executable,sandboxed=True)
    assert not (job/'stdout.log').exists()
    assert json.loads((job/'state.json').read_text())['failure_code']=='TOOL_EXECUTION_UNAVAILABLE'
    assert json.loads((job/'execution-preflight.json').read_text())['model_calls']==0


def test_operator_blocked_preset_cannot_be_selected(monkeypatch):
    from app.ai_tasks.service import presets,select_preset,TaskError
    from app.config import Settings
    monkeypatch.setattr('app.ai_tasks.service.shutil.which',lambda _: '/installed/codex')
    settings=Settings(_env_file=None,ai_task_presets=[{'id':'codex','adapter':'codex','model':'gpt-test','efforts':['high'],'default_effort':'high','unavailable_reason':'Tool execution unavailable'}])
    assert presets(settings)[0]['available'] is False
    assert presets(settings)[0]['unavailable_reason']=='Tool execution unavailable'
    with pytest.raises(TaskError):select_preset(settings,'codex','high')


def test_preflight_unconfirmed_cleanup_preserves_probe_identity(tmp_path,monkeypatch):
    from leadtrace.ops.ai_prefill import sandbox
    from leadtrace.ops.ai_prefill.tool_execution_preflight import ToolExecutionCleanupPending
    script=adapter(tmp_path)
    monkeypatch.setattr(sandbox,'sandbox_command',lambda *a,**kw:([sys.executable,str(script)],{**os.environ,'LEADTRACE_SANDBOX_HOME':'/tmp/leadtrace-model-home-synthetic'}))
    def unconfirmed(*a,**kw):raise ValueError('Missing receipt')
    monkeypatch.setattr(sandbox,'require_sandbox_cleanup',unconfirmed)
    with pytest.raises(ToolExecutionCleanupPending) as error:
        codex_execution_preflight('synthetic',sys.executable,dict(os.environ))
    state=error.value.process_state
    assert state['process_identity']['pid']==state['process_id']
    assert state['sandbox_home']=='/tmp/leadtrace-model-home-synthetic'
    assert state['sandbox_job_directory'].endswith('/job')


def test_runner_persists_unconfirmed_probe_cleanup_for_recovery(tmp_path,monkeypatch):
    from .test_ai_prefill_tasks import inputs
    from leadtrace.ops.ai_prefill import tasks,tool_execution_preflight
    inp,_,_,_=inputs(tmp_path)
    job=tmp_path/'job'
    tasks.prepare_task(entry='prefill',input_path=inp,output=job,adapter='codex',model='gpt-test',reasoning_effort='high')
    process_state={'process_id':123456,'process_identity':{'pid':123456,'start_ticks':42},
        'sandbox_home':'/tmp/leadtrace-model-home-synthetic','sandbox_job_directory':'/tmp/synthetic-probe/job'}
    def pending(*a,**kw):raise tool_execution_preflight.ToolExecutionCleanupPending(process_state)
    monkeypatch.setattr(tool_execution_preflight,'codex_execution_preflight',pending)
    with pytest.raises(tool_execution_preflight.ToolExecutionCleanupPending):
        tasks.run_task(job,executable=sys.executable,sandboxed=True)
    state=json.loads((job/'state.json').read_text())
    assert state['status']=='cleanup_pending' and state['process_cleanup_confirmed'] is False
    for key,value in process_state.items():assert state[key]==value
    assert not (job/'stdout.log').exists()
