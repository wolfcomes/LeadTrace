"""Durable local scheduler. Browser lifecycle does not own scientific subprocesses."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json,os,socket,threading,time
from uuid import uuid4
from sqlalchemy import select, or_
from app.ai_tasks.models import AiTask
from app.ai_tasks.service import ACTIVE,now,capacity,claim_next,TaskError
from app.ai_tasks.execution import prepare_job,deliver_result,job_directory


def reconcile_processes(directory, *, cancel=False):
    """Prove a dead worker has no executing descendants, regardless of checkpoint."""
    from leadtrace.ops.ai_prefill.tasks import (_active_session_processes,
        stop_task_processes, _writer_lock)
    from pathlib import Path
    directory=Path(directory)
    state_path=directory/'state.json'
    process_path=directory/'process.json'
    state=json.loads(state_path.read_text()) if state_path.exists() else {}
    if process_path.exists():
        process=json.loads(process_path.read_text())
        if state.get('process_identity') and process.get('process_identity') != state['process_identity']:
            raise ValueError('Process identity records disagree')
        if not state.get('process_identity'):
            state.update(process_id=process.get('pid'),process_identity=process.get('process_identity'))
        if not state.get('sandbox_home') and process.get('sandbox_home'):
            state['sandbox_home']=process['sandbox_home']
    if state.get('status') in {'running','cleanup_pending'} and not state.get('process_id'):
        raise ValueError('Task launch identity is unknown; capacity is retained')
    if cancel:
        stop_task_processes(state)
    elif _active_session_processes(state):
        raise ValueError('Task process session is still active')
    task_path=directory/'task.json'
    if task_path.exists():
        task=json.loads(task_path.read_text())
        lock_root=Path(state['lock_root']) if state.get('lock_root') else None
        with _writer_lock(task['source']['paper_key'],lock_root):
            # A descendant may hold an inherited lock after changing its session.
            if _active_session_processes(state):
                raise ValueError('Task process session is still active')
    if state.get('sandbox_home'):
        from leadtrace.ops.ai_prefill.sandbox import cleanup_sandbox,require_sandbox_cleanup
        require_sandbox_cleanup({'LEADTRACE_SANDBOX_HOME':state['sandbox_home']},expected_job_directory=state.get('sandbox_job_directory',directory),supervisor_identity=state.get('process_identity'))
        cleanup_sandbox({'LEADTRACE_SANDBOX_HOME':state['sandbox_home']},expected_job_directory=state.get('sandbox_job_directory',directory))
    return state


def _owner_active(owner):
    """Unknown host or malformed ownership must retain capacity, never be reclaimed."""
    from leadtrace.ops.ai_prefill.tasks import _process_identity
    if not owner:
        raise ValueError('Missing worker ownership')
    parts=owner.split(':')
    if len(parts) not in {4,5} or parts[0]!=socket.gethostname():
        raise ValueError('Unknown worker ownership')
    identity=_process_identity(int(parts[1]))
    if not identity:
        return False
    try:
        from pathlib import Path
        if Path(f'/proc/{int(parts[1])}/stat').read_text().rsplit(')',1)[1].split()[0] in {'Z','X'}:
            return False
    except FileNotFoundError:
        return False
    if len(parts)==5 and parts[3]!=identity['boot_id']:
        return False
    return identity['start_ticks']==int(parts[2])


class AiTaskCoordinator:
    def __init__(self,session_factory,settings,*,runner=None):
        from leadtrace.ops.ai_prefill.tasks import run_task,_process_identity
        self.sessions=session_factory;self.settings=settings;self.runner=runner or run_task
        identity=_process_identity(os.getpid()) or {}
        self.owner=f'{socket.gethostname()}:{os.getpid()}:{identity.get("start_ticks",0)}:{identity.get("boot_id", "unknown")}:{uuid4().hex}'
        self.stopping=threading.Event();self.thread=None;self.pool=ThreadPoolExecutor(max_workers=16,thread_name_prefix='scientific-job');self.futures={}
    def start(self):
        self.thread=threading.Thread(target=self.loop,name='ai-task-coordinator',daemon=True);self.thread.start()
    def stop(self):
        self.stopping.set()
        if self.thread:self.thread.join(timeout=10)
        self.pool.shutdown(wait=True,cancel_futures=False)
    def loop(self):
        while not self.stopping.is_set():
            try:self.tick()
            except Exception:
                # No raw exception/DSN/model output leaks into web responses.
                pass
            self.stopping.wait(2)
    def tick(self):
        self.futures={k:f for k,f in self.futures.items() if not f.done()}
        self.reconcile()
        with self.sessions.begin() as s:capacity(s).worker_seen_at=now()
        if len(self.futures)<16:
            with self.sessions.begin() as s:identifier=claim_next(s,owner=self.owner)
            if identifier:self.futures[identifier]=self.pool.submit(self.execute,identifier)
    def reconcile(self):
        with self.sessions.begin() as s:
            jobs=list(s.scalars(select(AiTask).where(AiTask.state.in_(ACTIVE),
                or_(AiTask.heartbeat_at.is_(None),AiTask.heartbeat_at<now()-timedelta(seconds=20)))
                .with_for_update(skip_locked=True)))
            for job in jobs:
                try:
                    if job.owner==self.owner:
                        future=self.futures.get(job.id)
                        if future is not None and not future.done():continue
                    elif _owner_active(job.owner):continue
                    directory=job_directory(self.settings,job.id)/'job'
                    reconcile_processes(directory,cancel=job.state=='cancel_requested')
                    cancelled=job.state=='cancel_requested'
                    job.state=('superseded' if job.result_summary.get('invalidated') else 'cancelled') if cancelled else 'interrupted'
                    job.stage=job.state;job.finished_at=now();job.heartbeat_at=now()
                    job.error_code=None if cancelled else 'WORKER_INTERRUPTED'
                    job.error_message=None if cancelled else 'The previous worker stopped. Artifacts were preserved; this task was not automatically rerun.'
                    job.delivery_state='conflict' if job.result_summary.get('invalidated') else ('not_applied' if job.action=='prefill' else 'not_applicable')
                except (ValueError,OSError,KeyError):
                    job.stage='orphaned_process';job.error_code='PROCESS_STILL_ACTIVE';job.error_message='A prior task process may still be active; capacity is retained until its exit is confirmed.'
    def execute(self,job_id):
        last_heartbeat=0.0
        cancelled=False
        def pulse():
            nonlocal last_heartbeat,cancelled
            if time.monotonic()-last_heartbeat<1:return
            with self.sessions.begin() as s:
                job=s.scalar(select(AiTask).where(AiTask.id==job_id).with_for_update())
                cancelled=not job or job.owner!=self.owner or job.state=='cancel_requested' or self.stopping.is_set()
                if job and job.owner==self.owner:job.heartbeat_at=now()
            last_heartbeat=time.monotonic()
        try:
            pulse()
            if cancelled:
                self.finish_cancel(job_id);return
            directory=prepare_job(self.sessions,self.settings,job_id)
            with self.sessions.begin() as s:
                job=s.scalar(select(AiTask).where(AiTask.id==job_id).with_for_update())
                if job.state=='cancel_requested':cancelled=True
                else:job.state='running';job.stage='model_running';job.heartbeat_at=now()
                timeout=job.timeout_seconds
            if cancelled:
                self.finish_cancel(job_id);return
            result=self.runner(directory,timeout_seconds=timeout,heartbeat=pulse,should_cancel=lambda:cancelled or self.stopping.is_set(),sandboxed=True)
            if result['state'].get('process_cleanup_confirmed') is False:
                raise ValueError('Process cleanup remains unconfirmed')
            reconcile_processes(directory)
            deliver_result(self.sessions,self.settings,job_id,result['state'])
        except Exception as e:
            try:
                reconcile_processes(job_directory(self.settings,job_id)/'job',cancel=True)
                cleanup_confirmed=True
            except (ValueError,OSError,KeyError):
                cleanup_confirmed=False
            with self.sessions.begin() as s:
                job=s.scalar(select(AiTask).where(AiTask.id==job_id).with_for_update())
                if job and job.owner==self.owner and job.state in ACTIVE:
                    if not cleanup_confirmed:
                        job.state='cancel_requested';job.stage='orphaned_process';job.heartbeat_at=now()
                        job.error_code='PROCESS_STILL_ACTIVE';job.error_message='Owned task processes have not stopped; capacity is retained while cleanup is retried.'
                        return
                    if job.state=='cancel_requested':
                        job.state='superseded' if job.result_summary.get('invalidated') else 'cancelled'
                    else:job.state='failed'
                    job.stage=job.state;job.finished_at=now();job.heartbeat_at=now()
                    job.error_code=e.code if isinstance(e,TaskError) or getattr(e,'code',None)=='TOOL_EXECUTION_UNAVAILABLE' else 'PREPARATION_OR_DELIVERY_FAILED'
                    job.error_message=str(e) if isinstance(e,TaskError) or getattr(e,'code',None)=='TOOL_EXECUTION_UNAVAILABLE' else 'Task preparation or validated delivery failed. No automatic retry was started; inspect the operator diagnostics.'
                    if job.delivery_state=='pending':job.delivery_state='not_applied'
    def finish_cancel(self,job_id):
        reconcile_processes(job_directory(self.settings,job_id)/'job',cancel=True)
        with self.sessions.begin() as s:
            job=s.scalar(select(AiTask).where(AiTask.id==job_id).with_for_update())
            if not job or job.owner!=self.owner:return
            job.state='superseded' if job.result_summary.get('invalidated') else 'cancelled'
            job.stage=job.state;job.finished_at=now();job.heartbeat_at=now()
            job.delivery_state='conflict' if job.result_summary.get('invalidated') else ('not_applied' if job.action=='prefill' else 'not_applicable')
