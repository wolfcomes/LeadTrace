"""Synthetic local processes only: no model calls or live database access."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import pytest
from leadtrace.ops.ai_prefill.tasks import _process_identity


def spawn_session(tmp_path, *, split_group=False):
    marker=tmp_path/'child.pid'
    code='''import os,signal,time,pathlib
child=os.fork()
if child==0:
    SPLIT
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    pathlib.Path(MARKER).write_text(str(os.getpid()))
    time.sleep(30)
else:
    time.sleep(30)
'''.replace('SPLIT','os.setpgid(0,0)' if split_group else 'pass').replace('MARKER',repr(str(marker)))
    process=subprocess.Popen([sys.executable,'-c',code],start_new_session=True)
    identity=_process_identity(process.pid)
    deadline=time.monotonic()+3
    while not marker.exists() and time.monotonic()<deadline:time.sleep(.01)
    assert marker.exists()
    return process,identity,int(marker.read_text())


def alive(pid):
    try:return Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[0]!='Z'
    except FileNotFoundError:return False


def cleanup(process,child):
    for pid in (child,process.pid):
        try:os.kill(pid,signal.SIGKILL)
        except ProcessLookupError:pass
    process.wait(timeout=3)


def test_verified_session_stop_reaps_children_in_separate_process_groups(tmp_path):
    from leadtrace.ops.ai_prefill.tasks import stop_task_processes
    process,identity,child=spawn_session(tmp_path,split_group=True)
    try:
        stop_task_processes({'process_id':process.pid,'process_identity':identity},grace_seconds=.1)
        assert not alive(child) and not alive(process.pid)
    finally:cleanup(process,child)


def test_bad_identity_never_signals_live_process(tmp_path):
    from leadtrace.ops.ai_prefill.tasks import stop_task_processes
    process,identity,child=spawn_session(tmp_path)
    try:
        with pytest.raises(ValueError,match='identity'):
            stop_task_processes({'process_id':process.pid,'process_identity':{**identity,'start_ticks':identity['start_ticks']-1}},grace_seconds=.1)
        assert alive(child) and alive(process.pid)
    finally:cleanup(process,child)


def test_stale_terminal_checkpoint_does_not_hide_live_descendants(tmp_path):
    from app.ai_tasks.coordinator import reconcile_processes
    process,identity,child=spawn_session(tmp_path)
    try:
        (tmp_path/'state.json').write_text(json.dumps({'status':'failed','process_id':process.pid,'process_identity':identity}))
        with pytest.raises(ValueError,match='active'):
            reconcile_processes(tmp_path,cancel=False)
        reconcile_processes(tmp_path,cancel=True)
        assert not alive(child) and not alive(process.pid)
    finally:cleanup(process,child)


def test_coordinator_retains_orphan_slot_until_verified_cancel(tmp_path,monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from uuid import uuid4
    import socket
    from app.ai_tasks.coordinator import AiTaskCoordinator
    job_dir=tmp_path/'job';job_dir.mkdir()
    process,identity,child=spawn_session(job_dir,split_group=True)
    row=SimpleNamespace(id=uuid4(),state='running',owner=f'{socket.gethostname()}:999999999:1:old',
        action='prefill',stage='running',result_summary={},delivery_state='pending')
    class Sessions:
        @contextmanager
        def begin(self):yield self
        def scalars(self,*args):return [row]
    worker=AiTaskCoordinator(Sessions(),SimpleNamespace(),runner=lambda *args,**kw:None)
    monkeypatch.setattr('app.ai_tasks.coordinator.job_directory',lambda *args:tmp_path)
    (job_dir/'state.json').write_text(json.dumps({'status':'partial','process_id':process.pid,'process_identity':identity}))
    try:
        worker.reconcile()
        assert row.state=='running' and row.stage=='orphaned_process'
        assert alive(child)
        row.state='cancel_requested'
        worker.reconcile()
        assert row.state=='cancelled' and row.delivery_state=='not_applied'
        assert not alive(child) and not alive(process.pid)
    finally:
        cleanup(process,child);worker.stop()


def test_missing_launch_identity_is_not_a_free_capacity_slot(tmp_path):
    from app.ai_tasks.coordinator import reconcile_processes
    (tmp_path/'state.json').write_text(json.dumps({'status':'running','process_id':None}))
    with pytest.raises(ValueError,match='identity'):
        reconcile_processes(tmp_path,cancel=True)
