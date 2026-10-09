"""Admin enqueue and capacity arbitration. Paper mutation locks precede job locks."""
from datetime import datetime,UTC,timedelta
import hashlib,json,shutil
from uuid import UUID,uuid4
from sqlalchemy import select,func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from app.ai_tasks.models import AiTask,AiTaskSettings
from app.ai_tasks.contracts import StartTask
from app.config import Settings
from app.papers.models import Paper
from app.catalog.models import PaperSource
from app.workspaces.models import PaperWorkspace,ReviewTask,WorkspaceState
from app.ai_prefill.service import AiPrefillService

ACTIVE={'preparing','running','validating','cancel_requested'}
OPEN=ACTIVE|{'queued'}
RETRYABLE={'failed','timed_out','partial','cancelled','interrupted','needs_revision','configuration_mismatch'}

def now():return datetime.now(UTC)

class TaskError(ValueError):
    def __init__(self,code,message):self.code=code;super().__init__(message)

def capacity(session:Session,*,lock=False)->AiTaskSettings:
    session.execute(insert(AiTaskSettings).values(id=1,max_concurrent=4).on_conflict_do_nothing(index_elements=['id']))
    statement=select(AiTaskSettings).where(AiTaskSettings.id==1)
    return session.scalar(statement.with_for_update() if lock else statement)

def set_limit(session,limit):
    if not 1<=limit<=16:raise TaskError('INVALID_CAPACITY','Concurrent task limit must be between 1 and 16')
    capacity(session,lock=True).max_concurrent=limit

def presets(settings:Settings)->list[dict]:
    from leadtrace.ops.ai_prefill.runtime import RuntimeConfig
    result=[]
    for raw in settings.ai_task_presets:
        try:
            identifier=str(raw['id']);adapter=str(raw['adapter']);model=str(raw['model']);efforts=list(raw['efforts']);default=str(raw['default_effort'])
            if not identifier or len(identifier)>64 or default not in efforts:continue
            for effort in efforts:RuntimeConfig(adapter=adapter,model=model,reasoning_effort=effort)
            blocked_reason=raw.get('unavailable_reason')
            available=shutil.which(adapter) is not None and not blocked_reason
            result.append({'id':identifier,'label':str(raw.get('label',model)),'adapter':adapter,'model':model,'efforts':efforts,'default_effort':default,'available':available,'unavailable_reason':None if available else str(blocked_reason or 'Model runner is not installed')})
        except (ValueError,KeyError,TypeError):continue
    return result

def select_preset(settings,preset_id,effort):
    preset=next((p for p in presets(settings) if p['id']==preset_id),None)
    if not preset:raise TaskError('MODEL_NOT_CONFIGURED','Choose a configured model preset')
    if effort not in preset['efforts']:raise TaskError('EFFORT_NOT_SUPPORTED','This reasoning effort is not configured for the model')
    if not preset['available']:raise TaskError('RUNNER_UNAVAILABLE',preset['unavailable_reason'] or 'The selected model runner is unavailable')
    return preset

def options(session,settings):
    row=capacity(session)
    return {'settings':{'max_concurrent':row.max_concurrent},'worker':{'online':row.worker_seen_at is not None and row.worker_seen_at>now()-timedelta(seconds=30),'last_seen_at':row.worker_seen_at},'presets':presets(settings)}

def target(session,paper_id):
    paper=session.scalar(select(Paper).where(Paper.id==paper_id).with_for_update())
    if not paper:raise TaskError('PAPER_NOT_FOUND','Article not found')
    workspace=session.scalar(select(PaperWorkspace).join(ReviewTask,ReviewTask.id==PaperWorkspace.review_task_id).where(PaperWorkspace.paper_id==paper_id,ReviewTask.status.notin_(['archived','approved'])).with_for_update(of=PaperWorkspace))
    task=session.scalar(select(ReviewTask).where(ReviewTask.id==workspace.review_task_id).with_for_update()) if workspace else None
    return paper,workspace,task

def enqueue(session:Session,settings:Settings,*,paper_id:UUID,actor_id:UUID,request:StartTask,parent_job:AiTask|None=None)->AiTask:
    if request.action=='repair' and (parent_job is None or parent_job.action not in {'review','repair'}):
        raise TaskError('REVIEW_REQUIRED','Start repair from a saved independent review')
    digest_input={'paper':str(paper_id),'request':request.model_dump(mode='json')}
    if request.action=='repair':digest_input['repair_parent']=str(parent_job.id)
    digest=hashlib.sha256(json.dumps(digest_input,sort_keys=True).encode()).hexdigest()
    paper,workspace,task=target(session,paper_id)
    existing=session.scalar(select(AiTask).where(AiTask.requested_by_id==actor_id,AiTask.idempotency_key==str(request.idempotency_key)))
    if existing:
        if existing.request_digest!=digest:raise TaskError('IDEMPOTENCY_CONFLICT','This request key was already used for different settings')
        return existing
    if not settings.ai_task_worker_enabled:raise TaskError('WORKER_DISABLED','AI task worker is not enabled on this server')
    preset=select_preset(settings,request.preset_id,request.reasoning_effort)
    if request.auto_review:
        if request.action!='prefill':raise TaskError('INVALID_AUTO_REVIEW','Automatic review is only available after first generation')
        select_preset(settings,request.auto_review.preset_id,request.auto_review.reasoning_effort)
    if session.scalar(select(AiTask.id).where(AiTask.paper_id==paper_id,AiTask.state.in_(OPEN))):
        raise TaskError('PAPER_TASK_ACTIVE','This article already has a queued or running AI task')
    if workspace is None:
        if request.expected_workspace_version is not None or request.expected_workspace_id is not None or request.expected_task_version is not None or request.action!='prefill':raise TaskError('WORKSPACE_CHANGED','No current draft matches this request')
        from app.workspaces.lifecycle import ensure_admin_workspace
        workspace=ensure_admin_workspace(session,paper_id=paper_id,admin_id=actor_id)
        task=session.get(ReviewTask,workspace.review_task_id)
    elif (request.expected_workspace_id!=workspace.id or request.expected_workspace_version!=workspace.version or request.expected_task_version!=task.version):
        raise TaskError('WORKSPACE_CHANGED','The working draft changed; reload before starting')
    if workspace.state!=WorkspaceState.EDITING:raise TaskError('WORKSPACE_READ_ONLY','The current draft is not editable')
    if request.action=='prefill':
        reason=AiPrefillService().unavailable_reason(session,workspace=workspace)
        if reason:raise TaskError('FIRST_GENERATION_REQUIRES_BLANK','First generation requires an untouched blank draft; archive and restart to generate again')
    elif not AiPrefillService._workspace_has_science(session,workspace.id):
        raise TaskError('NOTHING_TO_REVIEW','The current draft contains no scientific records')
    source=session.get(PaperSource,paper.source_id)
    from app.workspaces.assignment import AssignmentService
    AssignmentService._verified_source(session,paper)
    job=AiTask(id=uuid4(),paper_id=paper.id,workspace_id=workspace.id,requested_by_id=actor_id,
        idempotency_key=str(request.idempotency_key),request_digest=digest,action=request.action,
        preset_id=preset['id'],adapter=preset['adapter'],model=preset['model'],reasoning_effort=request.reasoning_effort,
        workspace_version=workspace.version,task_version=task.version,source_sha256=source.sha256,
        timeout_seconds=request.timeout_seconds,state='queued',delivery_state='pending' if request.action=='prefill' else 'not_applicable',stage='queued',
        attempt=parent_job.attempt+1 if parent_job else 1,parent_job_id=parent_job.id if parent_job else None,
        config={'auto_review':request.auto_review.model_dump() if request.auto_review else None},result_summary={})
    session.add(job);session.flush()
    return job

def claim_next(session:Session,*,owner:str):
    settings=capacity(session,lock=True)
    settings.worker_seen_at=now()
    active=session.scalar(select(func.count()).select_from(AiTask).where(AiTask.state.in_(ACTIVE)))
    if active>=settings.max_concurrent:return None
    job=session.scalar(select(AiTask).where(AiTask.state=='queued').order_by(AiTask.created_at,AiTask.id).with_for_update(skip_locked=True).limit(1))
    if not job:return None
    job.state='preparing';job.stage='preparing';job.owner=owner;job.lease_token=uuid4();job.started_at=now();job.heartbeat_at=now()
    session.flush();return job.id

def cancel_job(session,job):
    if job.state=='queued':job.state='cancelled';job.stage='cancelled';job.finished_at=now();job.delivery_state='not_applied'
    elif job.state in ACTIVE:job.state='cancel_requested';job.stage='stopping'
    session.flush();return job

def invalidate_paper_jobs(session,paper_id,reason):
    for job in session.scalars(select(AiTask).where(AiTask.paper_id==paper_id,AiTask.state.in_(OPEN)).with_for_update()):
        job.result_summary={**job.result_summary,'invalidated':True,'invalidation_reason':reason}
        if job.state=='queued':job.state='superseded';job.stage='superseded';job.finished_at=now();job.delivery_state='conflict'
        else:job.state='cancel_requested';job.stage='stopping';job.delivery_state='conflict'
    session.flush()

def check_target(job,workspace,task,source):
    return (workspace is not None and task is not None and workspace.id==job.workspace_id
        and workspace.state==WorkspaceState.EDITING and workspace.version==job.workspace_version
        and task.version==job.task_version and task.status.value not in {'archived','approved','submitted'}
        and source.sha256==job.source_sha256 and not job.result_summary.get('invalidated'))

def can_deliver_saved(job):
    return job.action=='prefill' and job.delivery_state=='not_applied' and (
        job.state in {'needs_revision','partial'} or
        (job.state=='failed' and job.error_code in {'DELIVERY_CONFLICT','DELIVERY_WRITE_FAILED'}))


def job_response(session,job):
    from app.ai_tasks.repair import review_eligible
    workspace=session.get(PaperWorkspace,job.workspace_id)
    current=workspace is not None and workspace.version==job.workspace_version and workspace.state==WorkspaceState.EDITING
    paper=session.get(Paper,job.paper_id)
    fields=['id','paper_id','workspace_id','workspace_version','action','preset_id','model','reasoning_effort','state','delivery_state','stage','error_code','error_message','created_at','started_at','finished_at','heartbeat_at','timeout_seconds','attempt','parent_job_id','result_summary']
    summary={k:v for k,v in job.result_summary.items() if k not in {'producer_report','review_report','proposal','findings'}}
    if job.result_summary.get('proposal'):
        summary['proposal']={k:v for k,v in job.result_summary['proposal'].items() if k!='changes'}
    return {**{k:getattr(job,k) for k in fields},'result_summary':summary,'paper_key':paper.paper_key,'paper_title':paper.title,
            'can_repair':False,
            'can_accept':current and job.action in {'repair','review'} and job.state=='proposal_ready' and job.delivery_state!='applied',
            'can_deliver':can_deliver_saved(job),'can_cancel':job.state in OPEN,'can_retry':job.action!='repair' and job.state in RETRYABLE and job.delivery_state!='applied'}
