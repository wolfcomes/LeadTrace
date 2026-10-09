"""Synthetic subprocess trees; no model calls or database access."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import pytest
from leadtrace.ops.ai_prefill.tasks import _process_identity


def launch(tmp_path,*,exit_parent=False):
    child=tmp_path/'child.py'
    child.write_text('''import os,signal,time,pathlib,sys
os.setsid()
signal.signal(signal.SIGTERM,signal.SIG_IGN)
pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))
while True:time.sleep(.1)
''')
    leader=tmp_path/'leader.py'
    leader.write_text('''import subprocess,sys,pathlib,time
p=subprocess.Popen([sys.executable,sys.argv[1],sys.argv[2]])
while not pathlib.Path(sys.argv[2]).exists():time.sleep(.01)
'''+('sys.exit(7)\n' if exit_parent else 'while True:time.sleep(.1)\n'))
    pidfile=tmp_path/'escaped.pid'
    code='from leadtrace.ops.ai_prefill.sandbox_supervisor import supervise;import sys;sys.exit(supervise(sys.argv[1:]))'
    # Pytest's configured pythonpath is not inherited by a new interpreter.
    # Start this direct supervisor fixture at the repository import root.
    process=subprocess.Popen([sys.executable,'-c',code,sys.executable,str(leader),str(child),str(pidfile)],start_new_session=True,cwd=Path(__file__).resolve().parents[4])
    for _ in range(200):
        if pidfile.exists():break
        if process.poll() is not None:raise AssertionError('Supervisor exited early')
        time.sleep(.01)
    childpid=int(pidfile.read_text())
    return process,childpid


def cleanup(process,child):
    if process.poll() is None:process.kill();process.wait()
    if _process_identity(child):
        try:os.kill(child,signal.SIGKILL)
        except ProcessLookupError:pass


def test_supervisor_reaps_tools_which_create_another_session_on_cancel(tmp_path):
    process,child=launch(tmp_path)
    try:
        assert _process_identity(child)['session']==child
        process.terminate();process.wait(timeout=5)
        assert process.returncode==143
        assert _process_identity(child) is None
    finally:cleanup(process,child)


def test_supervisor_reaps_adopted_child_before_reporting_parent_exit(tmp_path):
    process,child=launch(tmp_path,exit_parent=True)
    try:
        process.wait(timeout=5)
        assert process.returncode==7
        assert _process_identity(child) is None
    finally:cleanup(process,child)


def test_outer_runner_cleanup_waits_for_supervised_escaped_tools(tmp_path):
    from leadtrace.ops.ai_prefill.tasks import _terminate_owned_group
    process,child=launch(tmp_path)
    try:
        _terminate_owned_group(process,_process_identity(process.pid))
        assert _process_identity(child) is None
    finally:cleanup(process,child)


def test_killed_supervisor_cannot_falsely_confirm_escaped_cleanup(tmp_path):
    from leadtrace.ops.ai_prefill.sandbox import sandbox_command,cleanup_sandbox,require_sandbox_cleanup
    from leadtrace.ops.ai_prefill.tasks import _terminate_owned_group
    job=tmp_path/'job';job.mkdir()
    code='''import os,subprocess,sys,time,pathlib
child=subprocess.Popen([sys.executable,'-c','import os,time,pathlib;os.setsid();pathlib.Path("escaped.pid").write_text(str(os.getpid()));time.sleep(30)'])
while True:time.sleep(.1)
'''
    command,env=sandbox_command([sys.executable,'-c',code],dict(os.environ),job_directory=job,python_executable=sys.executable,adapter='codex')
    process=subprocess.Popen(command,cwd=job,env=env,start_new_session=True)
    identity=_process_identity(process.pid);escaped=None
    try:
        for _ in range(300):
            if (job/'escaped.pid').exists():break
            time.sleep(.01)
        escaped=int((job/'escaped.pid').read_text())
        process.kill();process.wait()
        _terminate_owned_group(process,identity)
        # Outer session cleanup alone is not sufficient: the owned child escaped it.
        assert _process_identity(escaped) is not None
        with pytest.raises(ValueError,match='capacity must be retained'):
            require_sandbox_cleanup(env,expected_job_directory=job,supervisor_identity=identity)
        # Coordinator recovery must also retain capacity rather than trusting a dead leader.
        (job/'state.json').write_text(json.dumps({'status':'cleanup_pending','process_id':process.pid,'process_identity':identity,'sandbox_home':env['LEADTRACE_SANDBOX_HOME']}))
        from app.ai_tasks.coordinator import reconcile_processes
        with pytest.raises(ValueError,match='capacity must be retained'):reconcile_processes(job,cancel=True)
    finally:
        if escaped:
            try:os.kill(escaped,signal.SIGKILL)
            except ProcessLookupError:pass
        if process.poll() is None:_terminate_owned_group(process,identity)
        cleanup_sandbox(env,expected_job_directory=job)


def test_receipt_survives_home_cleanup_and_binds_supervisor(tmp_path):
    from leadtrace.ops.ai_prefill.sandbox import sandbox_command,cleanup_sandbox,require_sandbox_cleanup
    command,env=sandbox_command(['/bin/true'],dict(os.environ),job_directory=tmp_path,python_executable=sys.executable,adapter='codex')
    process=subprocess.Popen(command,cwd=tmp_path,env=env,start_new_session=True)
    identity=_process_identity(process.pid)
    process.wait(timeout=10)
    assert process.returncode==0
    cleanup_sandbox(env,expected_job_directory=tmp_path)
    require_sandbox_cleanup(env,expected_job_directory=tmp_path,supervisor_identity=identity)
    with pytest.raises(ValueError):require_sandbox_cleanup(env,expected_job_directory=tmp_path,supervisor_identity={**identity,'start_ticks':identity['start_ticks']+1})
