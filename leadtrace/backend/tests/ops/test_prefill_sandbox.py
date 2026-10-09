import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from leadtrace.ops.ai_prefill.sandbox import sandbox_command,cleanup_sandbox,landlock_abi


def invoke(job,code,env=None,adapter='codex'):
    command,clean=sandbox_command([sys.executable,'-c',code],env or dict(os.environ),job_directory=job,python_executable=sys.executable,adapter=adapter)
    try:return subprocess.run(command,cwd=job,env=clean,capture_output=True,text=True,timeout=30)
    finally:cleanup_sandbox(clean)


def test_landlock_blocks_credentials_sibling_jobs_and_parent_proc(tmp_path):
    job=tmp_path/'job';job.mkdir()
    secret=tmp_path/'credentials.json';secret.write_text('synthetic-secret')
    sibling=tmp_path/'sibling';sibling.mkdir();(sibling/'candidate.json').write_text('synthetic')
    paths=[str(secret),str(sibling/'candidate.json'),f'/proc/{os.getpid()}/environ']
    code=f'''import json,pathlib
paths={paths!r}
for path in paths:
 try:pathlib.Path(path).read_bytes()
 except PermissionError:pass
 else:raise AssertionError('Unexpected read permitted: '+path)
try:pathlib.Path({str(tmp_path/'outside')!r}).write_text('bad')
except PermissionError:pass
else:raise AssertionError('Unexpected outside write permitted')
pathlib.Path('allowed.txt').write_text('ok')
print('isolated')'''
    result=invoke(job,code)
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=='isolated'
    assert (job/'allowed.txt').read_text()=='ok'


def test_scientific_python_imports_and_renders_inside_sandbox(tmp_path):
    code='''import fitz
from rdkit import Chem
from rdkit.Chem import Draw
from leadtrace.ops.ai_prefill.review_coverage import check_review_rows
m=Chem.MolFromSmiles('CCO');assert m
assert 'svg' in Draw.MolsToGridImage([m],useSVG=True)
p=fitz.open();p.new_page();p.save('synthetic.pdf')
print('scientific-tools-ok')'''
    result=invoke(tmp_path,code)
    assert result.returncode==0,result.stderr
    assert 'scientific-tools-ok' in result.stdout


def test_provider_home_is_isolated_and_not_archived(tmp_path):
    original=tmp_path/'original';original.mkdir();codex=original/'.codex';codex.mkdir()
    (codex/'auth.json').write_text('{"api_key":"synthetic"}')
    (codex/'config.toml').write_text('model_provider="test"\n[mcp_servers.danger]\ncommand="secret-hook"\n[model_providers.test]\nname="Test"\nbase_url="https://example.invalid"\nenv_key="TEST_MODEL_KEY"\n')
    (codex/'history.jsonl').write_text('must not copy')
    job=tmp_path/'job';job.mkdir()
    env={**os.environ,'HOME':str(original),'CODEX_HOME':str(codex),'DATABASE_URL':'synthetic','LEADTRACE_DATABASE_URL':'synthetic','PGPASSWORD':'synthetic','TEST_MODEL_KEY':'provider-key','UNRELATED_SECRET':'secret'}
    command,clean=sandbox_command([sys.executable,'-c','pass'],env,job_directory=job,python_executable=sys.executable,adapter='codex')
    private=Path(clean['LEADTRACE_SANDBOX_HOME'])
    try:
        assert not private.is_relative_to(job)
        assert clean['TEST_MODEL_KEY']=='provider-key'
        assert not any(k in clean for k in ('DATABASE_URL','LEADTRACE_DATABASE_URL','PGPASSWORD','UNRELATED_SECRET'))
        isolated=Path(clean['CODEX_HOME'])
        assert not (isolated/'history.jsonl').exists()
        assert 'mcp_servers' not in (isolated/'config.toml').read_text()
        assert (isolated/'auth.json').read_text()=='{"api_key":"synthetic"}'
    finally:cleanup_sandbox(clean)
    assert not private.exists()


def test_cleanup_rejects_non_runtime_directory(tmp_path):
    (tmp_path/'keep').write_text('safe')
    cleanup_sandbox({'LEADTRACE_SANDBOX_HOME':str(tmp_path)})
    assert (tmp_path/'keep').exists()


def test_shell_adapter_can_launch_scientific_python(tmp_path):
    # The adapter is not Python: its runtime whitelist must independently include
    # the scientific interpreter's symlink-resolved shared libraries.
    command,env=sandbox_command(['/bin/sh','-c', '\"$LEADTRACE_SCIENTIFIC_PYTHON\" -c \'import fitz; from rdkit import Chem; assert Chem.MolFromSmiles("CCO")\''],dict(os.environ),job_directory=tmp_path,python_executable=sys.executable,adapter='dsh')
    try:
        result=subprocess.run(command,cwd=tmp_path,env=env,capture_output=True,text=True,timeout=30)
        assert result.returncode==0,result.stderr
    finally:cleanup_sandbox(env)


def test_recovery_cleanup_requires_matching_job(tmp_path):
    command,env=sandbox_command(['/bin/true'],dict(os.environ),job_directory=tmp_path,python_executable=sys.executable,adapter='codex')
    private=Path(env['LEADTRACE_SANDBOX_HOME'])
    cleanup_sandbox(env,expected_job_directory=tmp_path/'other')
    assert private.exists()
    cleanup_sandbox(env,expected_job_directory=tmp_path)
    assert not private.exists()


def test_native_backend_can_import_admin_runtime_without_pytest_path():
    from pathlib import Path
    backend=Path(__file__).resolve().parents[2]
    env={k:v for k,v in os.environ.items() if k!='PYTHONPATH'}
    result=subprocess.run([sys.executable,'-c','import app.ai_tasks; from leadtrace.ops.ai_prefill.tasks import run_task'],cwd=backend,env=env,capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
