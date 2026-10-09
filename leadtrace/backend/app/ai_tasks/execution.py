"""Trusted coordinator preparation/delivery; scientific child sees no DB credentials."""
from datetime import datetime,UTC
from hashlib import sha256
import json,sys,shutil
from pathlib import Path
from uuid import UUID,uuid4
from sqlalchemy import select
from app.ai_tasks.models import AiTask
from app.ai_tasks.service import TaskError,check_target,target,now,enqueue
from app.ai_tasks.contracts import StartTask
from app.ai_prefill.assistance_contracts import CandidateEnvelope,SourceIdentity,ProducerProvenance,CandidateRecipe
from app.ai_prefill.assistance_inputs import prepare_input_package
from app.ai_prefill.assistance_coverage import CompoundInventory
from app.ai_prefill.contracts import AiPrefillPayload
from app.ai_prefill.workspace_export import _payload_from_snapshot
from app.ai_prefill.assistance_validation import validate_candidate
from app.ai_prefill.models import AiExtractionRun,AiExtractionRunStatus
from app.ai_prefill.service import AiPrefillService
from app.ai_prefill.provenance import ProvenanceInput,append_provenance
from app.assets.storage import LocalAssetStore
from app.catalog.models import PaperSource
from app.workspaces.models import PaperWorkspace,ReviewTask
from app.workspaces.snapshot import build_paper_snapshot
from app.structure_images.service import StructureSourceImageService
from app.structures.service import StructureDrawingService


def save_json(path:Path,value):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with path.open('x',encoding='utf8') as f:json.dump(value,f,ensure_ascii=False,indent=2,default=str)
    path.chmod(0o600)

def job_directory(settings,job_id):
    root=settings.ai_task_root
    if not root.is_absolute() or root==Path('/') or root.is_symlink():raise TaskError('TASK_ROOT_INVALID','Configure a dedicated absolute AI task directory')
    return root/str(job_id)

def inventory_for(settings,source_sha,preferred=None):
    candidates=[]
    if preferred and preferred.is_file():candidates.append(preferred)
    roots=[settings.ai_task_root,*settings.ai_task_inventory_roots]
    for root in roots:
        if root.is_dir():
            candidates.extend(sorted(root.rglob('compound-inventory.json'),key=lambda p:p.stat().st_mtime,reverse=True))
    for path in candidates:
        if path.is_symlink() or path.stat().st_size>8*1024*1024:continue
        try:inventory=CompoundInventory.model_validate_json(path.read_bytes())
        except (ValueError,OSError):continue
        if inventory.source.source_sha256==source_sha:return path,inventory
    raise TaskError('INVENTORY_REQUIRED','No source inventory is registered for this article. Generate a candidate first or ask the operator to register its existing inventory.')

def prepare_job(session_factory,settings,job_id):
    from leadtrace.ops.ai_prefill.tasks import GUIDE_VERSION,prepare_task
    root=job_directory(settings,job_id);root.mkdir(parents=True,exist_ok=False,mode=0o700)
    with session_factory.begin() as session:
        if settings.environment == 'preview':
            from app.ai_prefill.preview_identity import verify_preview_connection
            verify_preview_connection(settings,session.connection())
        initial=session.get(AiTask,job_id)
        paper,workspace,task=target(session,initial.paper_id)
        job=session.scalar(select(AiTask).where(AiTask.id==job_id).with_for_update())
        source=session.get(PaperSource,paper.source_id)
        if job.state!='preparing' or not check_target(job,workspace,task,source):raise TaskError('WORKSPACE_CHANGED','The target draft or assignment changed before preparation')
        from app.workspaces.assignment import AssignmentService
        AssignmentService._verified_source(session,paper)
        store=LocalAssetStore(settings.asset_root,source_roots=settings.source_roots)
        source_path=store.path_for(f'source/{source.source_root_key}/{source.source_key}')
        # Only byte identity is handled here; source content belongs to the scientific child.
        if sha256(source_path.read_bytes()).hexdigest()!=job.source_sha256:raise TaskError('SOURCE_CHANGED','The article PDF no longer matches its registered identity')
        identity=SourceIdentity(paper_key=paper.paper_key,source_sha256=source.sha256,byte_size=source.byte_size,page_count=source.page_count,doi=paper.doi)
        package=prepare_input_package(experiment_id='admin-'+str(job.id),source=identity,guide_version=GUIDE_VERSION,source_path=source_path,
            recipe={'expected_title':paper.title,'expected_doi':paper.doi,'catalog_paper_id':str(paper.id)})
        save_json(root/'input.json',package.model_dump(mode='json'))
        kwargs={}
        if job.action=='repair':
            from app.ai_tasks.repair import prepare_repair
            kwargs=prepare_repair(session,settings,job,root,workspace)
        elif job.action=='review':
            preferred=job_directory(settings,job.parent_job_id)/'job/outputs/compound-inventory.json' if job.parent_job_id else None
            inventory_path,inventory=inventory_for(settings,source.sha256,preferred)
            snapshot=build_paper_snapshot(session,workspace.id)
            empty=CandidateEnvelope(envelope_version=1,candidate_id='snapshot-'+str(job.id),experiment_id=package.experiment_id,
                source=identity,producer=ProducerProvenance(kind='human-assisted',engine='workspace-export',engine_version='admin-console-v1',generated_at=now()),
                recipe=CandidateRecipe(guide_version=GUIDE_VERSION),payload=AiPrefillPayload(schema_version=1))
            try:payload,refs,review_metadata=_payload_from_snapshot(empty,snapshot,{},snapshot['paper'])
            except ValueError:raise TaskError('DRAFT_NOT_REPRESENTABLE','Current draft has unresolved structures/relations or notes that the candidate format cannot preserve; resolve them before this review.') from None
            candidate=empty.model_copy(update={'payload':payload})
            save_json(root/'current-candidate.json',candidate.model_dump(mode='json'))
            save_json(root/'compound-inventory.json',inventory.model_dump(mode='json'))
            save_json(root/'workspace-snapshot.json',snapshot)
            save_json(root/'review-export.json',{'workspace_id':str(workspace.id),'workspace_version':workspace.version,'entity_refs':refs,'review_metadata':review_metadata,'inventory_sha256':sha256(inventory_path.read_bytes()).hexdigest()})
            save_json(root/'repair-baseline.json',{'snapshot':snapshot,'entity_refs':refs})
            job.config={**job.config,'review_with_repair':True,'baseline_sha256':sha256((root/'repair-baseline.json').read_bytes()).hexdigest()}
            kwargs={'candidate_path':root/'current-candidate.json','inventory_path':root/'compound-inventory.json','review_with_repair':True}
        prepare_task(entry='selfcheck' if job.action=='repair' else job.action,input_path=root/'input.json',output=root/'job',adapter=job.adapter,model=job.model,
            reasoning_effort=job.reasoning_effort,python_executable=str(settings.ai_task_python or Path(sys.executable)),**kwargs)
        job.stage='prepared'
        job.heartbeat_at=now()
    return root/'job'


def report_for(settings,job):
    from app.ai_tasks.producer_report import producer_report,read_artifact
    from app.ai_tasks.report_overview import build_overview,read_review_rows,actionable_review_rows
    directory=job_directory(settings,job.id)/'job'
    if job.action in {'prefill','repair'}:
        saved=job.result_summary.get('producer_report')
        report=dict(saved) if saved else None
        try:
            raw=read_artifact(directory,'outputs/candidate.json')
            expected=job.result_summary.get('candidate_file_sha256')
            if expected and sha256(raw).hexdigest()!=expected:
                raise TaskError('REPORT_CHANGED','The candidate no longer matches the saved result')
            candidate=CandidateEnvelope.model_validate_json(raw)
            report=report or producer_report(directory,candidate,raw)
            if 'overview' not in report:
                try:inventory=CompoundInventory.model_validate_json(read_artifact(directory,'outputs/compound-inventory.json'))
                except (ValueError,OSError):inventory=None
                report={**report,'overview':build_overview(candidate,producer_report=report,inventory=inventory)}
        except (ValueError,OSError) as exc:
            if isinstance(exc,TaskError) or report is None:raise
            # Historical saved diagnostics remain readable without claiming unknown totals.
            report={**report,'overview_unavailable':True}
        result={'job_id':str(job.id),'reviewed_workspace_version':job.result_summary.get('applied_workspace_version',job.workspace_version),**report}
        if job.action=='repair':
            result.update(report_kind='repair',proposal=job.result_summary.get('proposal'))
        return result
    saved=job.result_summary.get('review_report')
    if saved:
        return {**saved,'proposal':job.result_summary.get('proposal'),
            'repair_proposal_status':job.result_summary.get('repair_proposal_status'),
            'repair_proposal_errors':job.result_summary.get('repair_proposal_errors',[]),
            'repair_proposal_reason':job.result_summary.get('repair_proposal_reason')}
    from leadtrace.ops.ai_prefill.tasks import _verify_bundle
    _verify_bundle(directory)
    raw=read_artifact(directory,'inputs/current-candidate.json')
    candidate=CandidateEnvelope.model_validate_json(raw)
    rows=read_review_rows(directory,raw)
    from app.ai_tasks.repair import _hash
    from leadtrace.ops.ai_prefill.review_coverage import review_targets,check_review_rows
    inventory=CompoundInventory.model_validate_json(read_artifact(directory,'inputs/compound-inventory.json'))
    coverage=check_review_rows(review_targets(candidate,inventory),rows)
    findings=[{k:row.get(k) for k in ('domain','ref','verdict','reason','checked_fields','field_results')}
              for row in actionable_review_rows(candidate,rows)]
    return {'report_kind':'review','job_id':str(job.id),'reviewed_workspace_version':job.workspace_version,
        'candidate_file_sha256':sha256(raw).hexdigest(),'scientific_approval':False,'coverage':coverage,
        'findings':findings[:1000],'findings_total':len(findings),'findings_truncated':len(findings)>1000,
        'overview':build_overview(candidate,review_rows=rows,inventory=inventory),'review_rows_sha256':_hash(rows)}


def deliver_result(session_factory,settings,job_id,state,*,deliver_saved=False,delivery_actor_id=None):
    from leadtrace.ops.ai_prefill.provenance import export_run_provenance
    root=job_directory(settings,job_id);directory=root/'job'
    delivery_receipt=None
    with session_factory.begin() as s:
        if settings.environment == 'preview':
            from app.ai_prefill.preview_identity import verify_preview_connection
            verify_preview_connection(settings,s.connection())
        initial=s.get(AiTask,job_id);paper,workspace,task=target(s,initial.paper_id)
        job=s.scalar(select(AiTask).where(AiTask.id==job_id).with_for_update());source=s.get(PaperSource,paper.source_id)
        from app.ai_tasks.service import can_deliver_saved
        saved_eligible=deliver_saved and can_deliver_saved(job)
        if deliver_saved and not saved_eligible:
            if job.delivery_state=='applied':return
            raise TaskError('SAVED_RESULT_UNAVAILABLE','This task has no eligible saved generation to import')
        if saved_eligible:
            from app.ai_tasks.coordinator import reconcile_processes
            from leadtrace.ops.ai_prefill.tasks import _verify_bundle
            state=_verify_bundle(directory)
            if state.get('status') not in {'ready_for_independent_review','needs_revision','partial'} or state.get('process_cleanup_confirmed') is not True:
                raise TaskError('SAVED_RESULT_UNAVAILABLE','Saved task is not eligible for draft delivery')
            reconcile_processes(directory)
            from app.ai_tasks.service import OPEN
            if s.scalar(select(AiTask.id).where(AiTask.paper_id==job.paper_id,AiTask.id!=job.id,AiTask.state.in_(OPEN))):
                raise TaskError('TASK_ALREADY_OPEN','Another task is active for this paper')
        if not saved_eligible and job.state not in {'running','validating','cancel_requested'}:
            return  # Replayed/stale completion cannot rewrite terminal state.
        if job.state=='cancel_requested' or job.result_summary.get('invalidated'):
            job.state='superseded' if job.result_summary.get('invalidated') else 'cancelled';job.stage=job.state;job.finished_at=now();return
        previous_delivery={'state':job.state,'error_code':job.error_code,'error_message':job.error_message} if saved_eligible else None
        outcome=state['status'];job.state='validating';job.stage='validating'
        if outcome in {'cancelled','timed_out','failed','configuration_mismatch'}:
            job.state=outcome;job.stage=outcome;job.delivery_state='not_applied' if job.action=='prefill' else 'not_applicable'
            job.error_code={'failed':'RUN_FAILED','timed_out':'TIME_LIMIT','cancelled':'CANCELLED','configuration_mismatch':'CONFIGURATION_MISMATCH'}[outcome]
            job.error_message={'failed':'Model execution or output validation failed. Check model credentials/capabilities and the operator diagnostics before retrying.','timed_out':'The configured time limit was reached; saved outputs were preserved.','cancelled':'The model process was stopped.','configuration_mismatch':'Observed request configuration differs from the selected settings.'}[outcome]
            if (job.action=='review' and job.config.get('review_with_repair')
                and outcome in {'failed','timed_out'} and state.get('process_cleanup_confirmed') is True):
                # An interrupted repair must not hide a valid audit already saved.
                # Keep the failure state; unfinished proposals cannot be accepted.
                try:
                    report=report_for(settings,job)
                    job.result_summary={**job.result_summary,'report_available':True,'report_kind':'review',
                        'review_report':report,'review_rows_sha256':report.get('review_rows_sha256'),
                        'repair_proposal_status':'unavailable','scientific_approval':False,
                        'repair_proposal_errors':['The task stopped before completing its repair proposal; the validated baseline audit is available.']}
                except (ValueError,OSError):
                    pass
        elif job.action=='repair' and outcome in {'ready_for_independent_review','needs_revision','partial'}:
            from app.ai_tasks.repair import finish_proposal
            finish_proposal(s,settings,job,state,workspace,task,source)
        elif job.action=='review':
            report=report_for(settings,job)
            job.state='needs_revision' if outcome=='review_complete' and report['findings'] else 'completed' if outcome=='review_complete' else 'partial'
            job.result_summary={**job.result_summary,'reviewed_workspace_version':job.workspace_version,'missing_review_targets':len(report['coverage'].get('missing',[])),'findings':report['findings'][:20],'report_available':True,
                'review_report':report,'review_rows_sha256':report.get('review_rows_sha256')}
            candidate=directory/'inputs/current-candidate.json'
            # Review attaches to its frozen old workspace version, never to a replacement draft.
            if workspace and workspace.id==job.workspace_id and task.version==job.task_version and source.sha256==job.source_sha256:
                record=export_run_provenance(directory,candidate)
                record['outcome']='needs_revision' if job.state=='needs_revision' else record['outcome']
                append_provenance(s,workspace=workspace,source_sha256=source.sha256,actor_id=job.requested_by_id,record=ProvenanceInput.model_validate(record))
            else:job.delivery_state='conflict'
            if job.config.get('review_with_repair'):
                job.config={**job.config,'review_rows_sha256':report['review_rows_sha256']}
                job.result_summary={**job.result_summary,'report_kind':'review','repair_proposal_status':state.get('repair_proposal_status','unavailable'),
                    'repair_proposal_errors':state.get('repair_proposal_errors',[]),
                    'repair_proposal_reason':str(state.get('repair_proposal_reason',''))[:2000],'scientific_approval':False}
                if state.get('repair_proposal_status')=='ready':
                    from app.ai_tasks.repair import finish_proposal
                    try:
                        finish_proposal(s,settings,job,state,workspace,task,source)
                    except (ValueError,OSError) as exc:
                        job.state='partial'
                        job.result_summary={**job.result_summary,'repair_proposal_status':'unavailable','repair_proposal_errors':['Saved proposal failed validation; the baseline audit remains available.']}
                elif state.get('repair_proposal_status')!='no_changes':
                    job.state='partial'
        elif outcome in {'ready_for_independent_review','needs_revision','partial'} and (directory/'outputs/candidate.json').is_file():
            if not check_target(job,workspace,task,source):
                job.state='superseded';job.delivery_state='conflict';job.error_code='WORKSPACE_CHANGED';job.error_message='The working draft or assignment changed. AI output was preserved without overwriting the draft.'
            else:
                from app.ai_tasks.producer_report import read_artifact,producer_report
                from leadtrace.ops.ai_prefill.tasks import _verify_bundle,_same_source
                _verify_bundle(directory)
                frozen=json.loads((directory/'task.json').read_text())
                candidate_path=directory/'outputs/candidate.json';raw=read_artifact(directory,'outputs/candidate.json')
                candidate=CandidateEnvelope.model_validate_json(raw)
                if (not _same_source(candidate.source,SourceIdentity.model_validate(frozen['source']))
                    or candidate.source.source_sha256!=job.source_sha256
                    or candidate.candidate_id!=frozen['candidate_id'] or candidate.experiment_id!=frozen['experiment_id']
                    or candidate.parent_candidate_id!=frozen['baseline']['candidate_id'] or candidate.recipe.guide_version!=frozen['guide_version']
                    or sha256(raw).hexdigest()!=state.get('candidate_file_sha256')):
                    raise TaskError('CANDIDATE_IDENTITY_MISMATCH','Candidate identity or bytes changed; draft was not overwritten')
                validation=validate_candidate(candidate,expected_source_sha256=source.sha256,expected_page_count=source.page_count,expected_doi=paper.doi)
                if not validation.can_apply:raise TaskError('CANDIDATE_INVALID','Candidate validation failed; no scientific data was applied')
                diagnostics=producer_report(directory,candidate,raw)
                job.result_summary={**job.result_summary,'candidate_file_sha256':sha256(raw).hexdigest(),'report_available':True,'report_kind':'prefill','producer_report':diagnostics,'producer_status':outcome,'scientific_approval':False}
                service=AiPrefillService(structure_image_service=StructureSourceImageService(settings.asset_root,source_roots=settings.source_roots),drawing_service=StructureDrawingService(settings.asset_root))
                queued=service.queue(s,workspace_id=workspace.id,requested_by_id=job.requested_by_id,engine=job.adapter,engine_version=job.model)
                applied=service.apply(s,run_id=queued.run.id,payload=candidate.payload)
                if not applied.applied:
                    job.state='failed';job.stage='failed';job.delivery_state='not_applied'
                    job.error_code=applied.failure_code or 'DELIVERY_CONFLICT'
                    job.error_message='生成结果已保存，但数据库写入失败；尚未写入草稿。可查看检查报告，修复后重新导入已生成结果，无需重跑模型。' if applied.failure_code else '目标草稿或来源检查未通过，生成结果已保存；未覆盖现有内容。'
                    job.result_summary={**job.result_summary,'delivery_failure':applied.failure_details,'delivery_failure_stage':applied.run.error_summary or applied.run.status.value}
                    if not saved_eligible:job.finished_at=now()
                    job.heartbeat_at=now()
                    return
                record=export_run_provenance(directory,candidate_path,applied_workspace_version=workspace.version)
                append_provenance(s,workspace=workspace,source_sha256=source.sha256,actor_id=job.requested_by_id,record=ProvenanceInput.model_validate(record))
                p=candidate.payload
                job.state='needs_revision' if diagnostics['status']=='needs_revision' else 'completed';job.delivery_state='applied'
                job.error_code=None;job.error_message=None
                job.result_summary={'compounds':len(p.compounds),'activities':len(p.activities),'lineages':len(p.lineages),'edges':sum(len(g.edges) for g in p.lineages),'candidate_file_sha256':sha256(candidate_path.read_bytes()).hexdigest(),'applied_workspace_version':workspace.version,'scientific_approval':False}
                diagnostics['delivery_notes']=applied.delivery_notes
                job.result_summary.update(producer_status=outcome,report_available=True,report_kind='prefill',
                    missing_compounds=len(diagnostics['coverage']['missing']) if diagnostics['coverage_known'] else None,
                    check_issue_counts=diagnostics['issue_counts'],findings=diagnostics['findings'][:20],producer_report=diagnostics)
                if saved_eligible:job.result_summary.update(previous_delivery=previous_delivery,delivered_saved_result=True,delivered_at=now().isoformat(),delivery_actor_id=str(delivery_actor_id or job.requested_by_id))
                delivery_receipt={'job_id':str(job.id),'candidate_file_sha256':job.result_summary['candidate_file_sha256'],'workspace_id':str(workspace.id),'workspace_version':workspace.version,'run_id':str(queued.run.id),'entity_map':applied.entity_map,'scientific_approval':False}
                if job.config.get('auto_review') and not saved_eligible:
                    s.flush()
                    opts=job.config['auto_review']
                    try:
                        with s.begin_nested():
                            child=enqueue(s,settings,paper_id=paper.id,actor_id=job.requested_by_id,request=StartTask(action='review',expected_workspace_id=workspace.id,expected_task_version=task.version,expected_workspace_version=workspace.version,idempotency_key=uuid4(),timeout_seconds=job.timeout_seconds,**opts),parent_job=job)
                        job.result_summary={**job.result_summary,'auto_review_job_id':str(child.id)}
                    except TaskError as exc:
                        job.result_summary={**job.result_summary,'auto_review_error':exc.code}
                        job.error_code='AUTO_REVIEW_NOT_QUEUED'
                        job.error_message='Generation was saved, but independent review could not be queued. Reload model options and start review separately.'
        else:
            job.state='needs_revision' if outcome=='needs_revision' else 'partial';job.delivery_state='not_applied';job.error_code='OUTPUT_INCOMPLETE';job.error_message='Generated output did not pass the full producer checks. It was retained without automatic import.'
        job.stage=job.state
        if not saved_eligible:job.finished_at=now()
        job.heartbeat_at=now()

    if delivery_receipt is not None:
        # A sidecar is evidence of an already committed apply, never a prepared receipt.
        try:
            save_json(root/'delivery.json',delivery_receipt)
        except OSError:
            with session_factory.begin() as s:
                job=s.get(AiTask,job_id)
                job.result_summary={**job.result_summary,'delivery_sidecar_unavailable':True}
