"""Admin article generations: revocable assignment and verified, non-destructive archives."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
from uuid import UUID, uuid4

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.assets.models import Asset
from app.assets.storage import LocalAssetStore
from app.db.base import Base
from app.papers.models import Paper
from app.workspaces.assignment import AssignmentService, PaperNotFoundError
from app.workspaces.models import (ArticleArchive, ChangeActorKind, ChangeEvent, PaperSection,
    PaperSectionReview, PaperWorkspace, ReviewTask, ReviewTaskState, WorkspaceState)
from app.workspaces.snapshot import build_paper_snapshot


class LifecycleConflict(RuntimeError):
    pass


CATALOG_FIELDS = ('title','journal','publication_year','volume','issue','doi','abstract','abstract_source','pdb_references')


def _json(value):
    if isinstance(value, (UUID, datetime, Path, Decimal)): return str(value)
    if isinstance(value, Enum): return value.value
    raise TypeError(type(value).__name__)


def _record(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def _active(session, paper_id, *, lock=False):
    query = select(PaperWorkspace).join(ReviewTask,ReviewTask.id==PaperWorkspace.review_task_id).where(
        PaperWorkspace.paper_id==paper_id, ReviewTask.status.notin_([ReviewTaskState.ARCHIVED,ReviewTaskState.APPROVED]))
    if lock: query=query.with_for_update(of=PaperWorkspace)
    workspace=session.scalar(query)
    if workspace is None:return None,None
    query=select(ReviewTask).where(ReviewTask.id==workspace.review_task_id).execution_options(populate_existing=True)
    if lock:query=query.with_for_update()
    return workspace,session.scalar(query)


def _paper(session,paper_id,lock=True):
    query=select(Paper).where(Paper.id==paper_id)
    if lock:query=query.with_for_update()
    paper=session.scalar(query)
    if paper is None:raise PaperNotFoundError('Paper not found')
    return paper


def _new_workspace(session,paper,admin_id):
    task=ReviewTask(paper_id=paper.id,assigned_reviewer_id=None,created_by_id=admin_id,status=ReviewTaskState.UNASSIGNED,version=1)
    session.add(task);session.flush()
    workspace=PaperWorkspace(paper_id=paper.id,review_task_id=task.id,state=WorkspaceState.EDITING,version=1)
    session.add(workspace);session.flush()
    session.add_all([PaperSectionReview(paper_id=paper.id,workspace_id=workspace.id,section_key=key) for key in PaperSection])
    session.flush()
    return workspace


def ensure_admin_workspace(session: Session,paper_id: UUID,admin_id: UUID)->PaperWorkspace:
    paper=_paper(session,paper_id)
    workspace,task=_active(session,paper_id,lock=True)
    if workspace is not None:return workspace
    AssignmentService._verified_source(session,paper)
    return _new_workspace(session,paper,admin_id)


def _checked(session,paper_id,expected_workspace_version,expected_task_version,expected_workspace_id):
    paper=_paper(session,paper_id)
    workspace,task=_active(session,paper_id,lock=True)
    if workspace is None:raise LifecycleConflict('No active working draft')
    if workspace.id!=expected_workspace_id or workspace.version!=expected_workspace_version or task.version!=expected_task_version:
        raise LifecycleConflict('Article changed; refresh before continuing')
    if workspace.state==WorkspaceState.SUBMITTED or task.status==ReviewTaskState.SUBMITTED:
        raise LifecycleConflict('Resolve the pending submission before changing article assignment')
    return paper,workspace,task


def _invalidate(session,paper_id,reason):
    from app.ai_tasks.service import invalidate_paper_jobs
    invalidate_paper_jobs(session,paper_id,reason)
    # Legacy workers must also fail their terminal-state check after a recall/reset.
    from app.ai_prefill.models import AiExtractionRun, AiExtractionRunStatus
    for run in session.scalars(select(AiExtractionRun).where(AiExtractionRun.paper_id==paper_id,
            AiExtractionRun.status.in_([AiExtractionRunStatus.QUEUED,AiExtractionRunStatus.RUNNING])).with_for_update()):
        run.status=AiExtractionRunStatus.SUPERSEDED
        run.error_summary='Article assignment or working generation changed'



def _event(session,workspace,admin_id,action,before,after):
    session.add(ChangeEvent(paper_id=workspace.paper_id,workspace_id=workspace.id,
        entity_type='article_lifecycle',entity_id=workspace.id,action=action,
        before_value=before,after_value=after,actor_kind=ChangeActorKind.ADMIN,actor_id=admin_id))


def recall_assignment(session: Session,*,paper_id: UUID,admin_id: UUID,
                      expected_workspace_id:UUID,expected_workspace_version:int,expected_task_version:int):
    paper,workspace,task=_checked(session,paper_id,expected_workspace_version,expected_task_version,expected_workspace_id)
    if task.assigned_reviewer_id is None:raise LifecycleConflict('Article is already unassigned')
    _invalidate(session,paper_id,'assignment_recalled')
    before={'assignee':str(task.assigned_reviewer_id),'task_version':task.version}
    task.assigned_reviewer_id=None;task.status=ReviewTaskState.UNASSIGNED;task.version+=1
    _event(session,workspace,admin_id,'assignment.recall',before,{'assignee':None,'task_version':task.version})
    session.flush()
    return workspace


def _working_export(session,workspace,task):
    """Export scoped rows, including history, layout, viewing, submissions and AI records."""
    rows={}
    for table in Base.metadata.sorted_tables:
        if table.name=='article_archives':continue
        if 'workspace_id' in table.c: condition=table.c.workspace_id==workspace.id
        elif 'review_task_id' in table.c: condition=table.c.review_task_id==task.id
        else:continue
        rows[table.name]=[dict(row) for row in session.execute(select(table).where(condition)).mappings()]
    # Layouts are linked to lineages rather than directly to a workspace.
    lineage_ids=[row['id'] for row in rows.get('lineages',[])]
    for table in Base.metadata.sorted_tables:
        if table.name not in rows and 'lineage_id' in table.c:
            rows[table.name]=[dict(row) for row in session.execute(select(table).where(table.c.lineage_id.in_(lineage_ids))).mappings()]
    submission_ids=[row['id'] for row in rows.get('paper_submissions',[])]
    for table in Base.metadata.sorted_tables:
        if table.name not in rows and 'submission_id' in table.c:
            rows[table.name]=[dict(row) for row in session.execute(select(table).where(table.c.submission_id.in_(submission_ids))).mappings()]
    audit=Base.metadata.tables.get('audit_events')
    if audit is not None:
        rows['audit_events']=[dict(row) for row in session.execute(select(audit).where(audit.c.paper_id==workspace.paper_id)).mappings()]
    return rows


def _asset_ids(value):
    result=set()
    if isinstance(value,dict):
        for key,item in value.items():
            if key.endswith('asset_id') and item:
                try:result.add(UUID(str(item)))
                except ValueError:pass
            result.update(_asset_ids(item))
    elif isinstance(value,list):
        for item in value:result.update(_asset_ids(item))
    return result


def _metadata_baseline(session,paper,workspace):
    # Earliest recorded before-values recover only fields with actual historical evidence.
    baseline={key:getattr(paper,key) for key in CATALOG_FIELDS}
    seen=set()
    for change in session.scalars(select(ChangeEvent).where(ChangeEvent.paper_id==paper.id,
            ChangeEvent.entity_type=='paper').order_by(ChangeEvent.occurred_at,ChangeEvent.id)):
        for key,value in (change.before_value or {}).items():
            if key in baseline and key not in seen:baseline[key]=value;seen.add(key)
    return baseline,sorted(seen)


def archive_reset(session:Session,*,paper_id:UUID,admin_id:UUID,expected_workspace_version:int,
                  expected_workspace_id:UUID,expected_task_version:int,confirm_paper_key:str,archive_root:Path,asset_root:Path,task_root:Path|None=None):
    paper,workspace,task=_checked(session,paper_id,expected_workspace_version,expected_task_version,expected_workspace_id)
    if confirm_paper_key!=paper.paper_key:raise LifecycleConflict('Article key confirmation does not match')
    # Do not snapshot files while a paid worker is still writing them.
    jobs_table=Base.metadata.tables.get('ai_tasks')
    if jobs_table is not None:
        # Lock all paper jobs before checking; a queued job must not be claimed
        # between the check and export. Workers skip these locked queue rows.
        jobs=list(session.execute(select(jobs_table).where(jobs_table.c.paper_id==paper_id).with_for_update()).mappings())
        if any(job['state'] in {'preparing','running','validating','cancel_requested'} for job in jobs):
            raise LifecycleConflict('Stop the running AI task and wait for it to finish before archiving')
    from app.ai_prefill.models import AiExtractionRun,AiExtractionRunStatus
    legacy=list(session.scalars(select(AiExtractionRun).where(AiExtractionRun.paper_id==paper_id).with_for_update()))
    if any(run.status==AiExtractionRunStatus.RUNNING for run in legacy):
        raise LifecycleConflict('Stop the running AI task and wait for it to finish before archiving')
    archive_id=uuid4();now=datetime.now(timezone.utc)
    relative=f'{paper.id}/{now.strftime("%Y%m%dT%H%M%S%fZ")}-{archive_id}'
    root=Path(archive_root).resolve();directory=root/relative
    directory.mkdir(parents=True,exist_ok=False,mode=0o700)
    baseline,restored_fields=_metadata_baseline(session,paper,workspace)
    payload={'format_version':1,'archive_id':archive_id,'created_at':now,'workspace':_record(workspace),
             'review_task':_record(task),'snapshot':build_paper_snapshot(session,workspace.id),
             'history':_working_export(session,workspace,task),'catalog_baseline':baseline,
             'catalog_restored_fields':restored_fields,
             'policy':{'published_versions':'preserved','source_files':'retained_in_source_catalog',
                       'runtime_logs':'new_console_jobs_copied_when_present; historical_external_paths_retained'}}
    files=[]
    def register(path):
        content=path.read_bytes();files.append({'path':str(path.relative_to(directory)),
            'sha256':hashlib.sha256(content).hexdigest(),'byte_size':len(content)})
    try:
        # New console jobs have controlled directories. Copy completed files into the
        # same archive root; retain original paths for non-destructive audit/cleanup.
        payload['runtime_archives']=[]
        if task_root is not None:
            task_base=Path(task_root).resolve()
            for job in payload['history'].get('ai_tasks',[]):
                job_dir=task_base/str(job['id'])
                if not job_dir.exists():continue
                if job_dir.is_symlink():raise LifecycleConflict('AI task directory is a symlink; archive aborted')
                copied=[]
                for source in sorted(job_dir.rglob('*')):
                    if source.is_symlink():raise LifecycleConflict('AI task files contain a symlink; archive aborted')
                    if not source.is_file():continue
                    relative_file=source.relative_to(job_dir)
                    target=directory/'ai-tasks'/str(job['id'])/relative_file
                    target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(source,target)
                    if hashlib.sha256(source.read_bytes()).hexdigest()!=hashlib.sha256(target.read_bytes()).hexdigest():
                        raise LifecycleConflict('AI task file changed during archive')
                    register(target);copied.append(str(target.relative_to(directory)))
                payload['runtime_archives'].append({'job_id':str(job['id']),'original_directory':str(job_dir),'files':copied})
        assets=[]
        store=LocalAssetStore(asset_root)
        for asset_id in sorted(_asset_ids(payload),key=str):
            asset=session.get(Asset,asset_id)
            if asset is None:raise LifecycleConflict('A linked asset record is missing; archive aborted')
            metadata={key:value for key,value in _record(asset).items() if key not in {"source_metadata", "derivation_metadata"}}
            if asset.storage_key.startswith('managed/'):
                source=store.path_for(asset.storage_key)
                target=directory/'assets'/str(asset.id)/source.name
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(source,target)
                digest=hashlib.sha256(target.read_bytes()).hexdigest()
                if digest!=asset.sha256 or target.stat().st_size!=asset.byte_size:
                    raise LifecycleConflict('A linked working asset failed hash verification; archive aborted')
                metadata['archive_path']=str(target.relative_to(directory));register(target)
            assets.append(metadata)
        payload['assets']=assets
        target=directory/'workspace.json'
        target.write_text(json.dumps(payload,default=_json,ensure_ascii=False,sort_keys=True,indent=2)+'\n');register(target)
        manifest={'archive_id':str(archive_id),'workspace_id':str(workspace.id),'paper_id':str(paper.id),'files':files}
        manifest_path=directory/'manifest.json'
        manifest_path.write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
        for entry in files:
            if hashlib.sha256((directory/entry['path']).read_bytes()).hexdigest()!=entry['sha256']:
                raise LifecycleConflict('Archive verification failed')
    except Exception:
        # Only remove this newly created incomplete export, never old archives.
        shutil.rmtree(directory)
        raise
    _invalidate(session,paper_id,'workspace_archived')
    old_assignee=task.assigned_reviewer_id
    workspace.state=WorkspaceState.ARCHIVED
    task.status=ReviewTaskState.ARCHIVED;task.assigned_reviewer_id=None;task.version+=1
    archive=ArticleArchive(id=archive_id,paper_id=paper.id,workspace_id=workspace.id,created_by_id=admin_id,
        created_at=now,relative_path=relative,manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        catalog_metadata=json.loads(json.dumps(baseline,default=_json)))
    session.add(archive)
    _event(session,workspace,admin_id,'workspace.archive',{'assignee':str(old_assignee) if old_assignee else None},
        {'archive_id':str(archive_id),'relative_path':relative,'restored_catalog_fields':restored_fields})
    for key,value in baseline.items():setattr(paper,key,value)
    session.flush()
    new=_new_workspace(session,paper,admin_id)
    return new,archive


def management(session:Session,paper_id:UUID,archive_root:Path):
    paper=_paper(session,paper_id,False)
    workspace,task=_active(session,paper_id)
    counts={}
    if workspace:
        for table in Base.metadata.sorted_tables:
            if table.name=='article_archives':continue
            if 'workspace_id' in table.c:condition=table.c.workspace_id==workspace.id
            elif 'review_task_id' in table.c:condition=table.c.review_task_id==task.id
            else:continue
            counts[table.name]=session.scalar(select(func.count()).select_from(table).where(condition)) or 0
        counts['published_versions']=int(paper.current_published_version_id is not None)
    archives=list(session.scalars(select(ArticleArchive).where(ArticleArchive.paper_id==paper_id).order_by(ArticleArchive.created_at.desc())))
    return {'paper_id':paper.id,'paper_key':paper.paper_key,'workspace_id':workspace.id if workspace else None,
        'workspace_version':workspace.version if workspace else None,'task_version':task.version if task else None,
        'assignment_state':task.status.value if task else 'unassigned',
        'assigned_reviewer_id':task.assigned_reviewer_id if task else None,'counts':counts,
        'archives':[{'id':a.id,'created_at':a.created_at,'relative_path':a.relative_path,'workspace_id':a.workspace_id} for a in archives],
        'archive_root':str(Path(archive_root).resolve())}
