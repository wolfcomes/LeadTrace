"""Review-bound repair proposals. Generating never writes science; accepting never calls AI."""
from hashlib import sha256
import json
from uuid import UUID
from sqlalchemy import select
from app.ai_tasks.models import AiTask
from app.ai_tasks.contracts import StartTask
from app.ai_tasks.service import TaskError, target, check_target, enqueue, OPEN, now
from app.ai_tasks.producer_report import read_artifact, producer_report
from app.ai_prefill.assistance_contracts import CandidateEnvelope
from app.ai_prefill.assistance_validation import validate_candidate
from app.ai_prefill.provenance import append_provenance, ProvenanceInput
from app.catalog.models import PaperSource
from app.workspaces.snapshot import build_paper_snapshot, canonical_snapshot_hash


def _hash(value):
    return sha256(json.dumps(value,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()


def science_snapshot_hash(snapshot):
    return canonical_snapshot_hash({k:v for k,v in snapshot.items() if k!='ai_provenance'})


def review_eligible(job):
    return job.action=='review' and job.state in {'completed','needs_revision','partial'} and bool(job.result_summary.get('report_available'))


def enqueue_repair(session,settings,*,review_id,actor_id,request):
    raise TaskError('REPAIR_MERGED_IN_REVIEW','Start a new independent review; it now includes the repair proposal in the same model task')


def prepare_repair(session,settings,job,root,workspace):
    from app.ai_tasks.execution import job_directory, save_json
    from app.ai_tasks.report_overview import read_review_rows,actionable_review_rows
    from leadtrace.ops.ai_prefill.tasks import _verify_bundle
    review=session.get(AiTask,UUID(job.config['review_job_id']))
    if not review or not review_eligible(review) or (review.workspace_id,review.workspace_version)!=(job.workspace_id,job.workspace_version):
        raise TaskError('REVIEW_CHANGED','The source review no longer matches this repair')
    directory=job_directory(settings,review.id)/'job';_verify_bundle(directory)
    raw=read_artifact(directory,'inputs/current-candidate.json');rows=read_review_rows(directory,raw)
    if sha256(raw).hexdigest()!=job.config['review_candidate_sha256'] or _hash(rows)!=job.config['review_rows_sha256']:
        raise TaskError('REPORT_CHANGED','The reviewed candidate or report changed')
    baseline=json.loads(read_artifact(directory.parent,'workspace-snapshot.json'))
    snapshot=build_paper_snapshot(session,workspace.id)
    if science_snapshot_hash(baseline)!=science_snapshot_hash(snapshot):raise TaskError('WORKSPACE_CHANGED','The reviewed content changed')
    # Outer files are server-owned; scientific runtime sees only frozen inputs.
    save_json(root/'current-candidate.json',json.loads(raw))
    save_json(root/'compound-inventory.json',json.loads(read_artifact(directory,'inputs/compound-inventory.json')))
    export=json.loads(read_artifact(directory.parent,'review-export.json'))
    save_json(root/'repair-baseline.json',{'snapshot':snapshot,'entity_refs':export['entity_refs']})
    job.config={**job.config,'baseline_sha256':sha256((root/'repair-baseline.json').read_bytes()).hexdigest()}
    feedback={'review_job_id':str(review.id),'candidate_file_sha256':sha256(raw).hexdigest(),
        'findings':actionable_review_rows(CandidateEnvelope.model_validate_json(raw),rows),
        'instructions':'Repair source-supported findings and affected dependencies only. Keep unchanged refs and human content. Preserve unresolved findings without guessing. Return a complete revised candidate; no database access or scientific approval. Preserve list order for unchanged activities and links; do not rewrite unaffected records.'}
    save_json(root/'feedback.json',feedback)
    return {'candidate_path':root/'current-candidate.json','inventory_path':root/'compound-inventory.json',
        'feedback_path':root/'feedback.json','workspace_id':str(workspace.id),'workspace_version':workspace.version}


def require_explicit_collections(before, raw_payload):
    """Pydantic defaults cannot turn incomplete output into deletions."""
    collections=('compounds','activities','lineages','evidence','structure_locators','edge_evidence_links','compound_highlights')
    for name in collections:
        if getattr(before,name) and name not in raw_payload:
            raise TaskError('REPAIR_INCOMPLETE',f'Repair omitted populated {name}; preserve it or propose explicit removals')
    if before.bibliography and 'bibliography' not in raw_payload:
        raise TaskError('REPAIR_INCOMPLETE','Repair omitted bibliography')
    previous={g.ref:g for g in before.lineages}
    for group in raw_payload.get('lineages',[]):
        old=previous.get(group.get('ref'))
        if old:
            for name in ('members','edges'):
                if getattr(old,name) and name not in group:
                    raise TaskError('REPAIR_INCOMPLETE',f'Repair omitted populated lineage {name}')


def _candidate(settings,job,state):
    from app.ai_tasks.execution import job_directory
    from leadtrace.ops.ai_prefill.tasks import _verify_bundle,_same_source
    from app.ai_prefill.assistance_contracts import SourceIdentity
    directory=job_directory(settings,job.id)/'job';_verify_bundle(directory)
    task=json.loads(read_artifact(directory,'task.json'))
    raw=read_artifact(directory,'outputs/candidate.json');candidate=CandidateEnvelope.model_validate_json(raw)
    if (sha256(raw).hexdigest()!=state.get('candidate_file_sha256') or candidate.source.source_sha256!=job.source_sha256
        or not _same_source(candidate.source,SourceIdentity.model_validate(task['source']))
        or candidate.candidate_id!=task['candidate_id'] or candidate.experiment_id!=task['experiment_id']
        or candidate.parent_candidate_id!=task['baseline']['candidate_id'] or candidate.recipe.guide_version!=task['guide_version']):
        raise TaskError('CANDIDATE_IDENTITY_MISMATCH','Repair candidate identity or bytes changed')
    if not validate_candidate(candidate).can_apply:raise TaskError('CANDIDATE_INVALID','Repair contains invalid structure or references')
    before=CandidateEnvelope.model_validate_json(read_artifact(directory,'inputs/current-candidate.json'))
    require_explicit_collections(before.payload,json.loads(raw)['payload'])
    return directory,before,candidate,raw


def finish_proposal(session,settings,job,state,workspace,task,source):
    if not check_target(job,workspace,task,source):
        job.state='superseded';job.delivery_state='conflict';job.error_code='WORKSPACE_CHANGED';job.error_message='The draft changed. Repair output was saved without modifying it.';return
    from app.ai_tasks.repair_apply import design_diff
    directory,before,candidate,raw=_candidate(settings,job,state)
    proposal=design_diff(before.payload,candidate.payload)
    diagnostics=producer_report(directory,candidate,raw)
    proposal['remaining_findings']=diagnostics['findings_total']
    # The approval digest binds content, exact baseline and report, not just a display count.
    proposal['sha256']=_hash({'diff':proposal,'candidate':sha256(raw).hexdigest(),'baseline':job.config['baseline_sha256'],'review':job.config['review_rows_sha256']})
    job.result_summary={**job.result_summary,'report_available':True,'report_kind':'review' if job.action=='review' else 'repair','proposal':proposal,'producer_report':diagnostics,
        'candidate_file_sha256':sha256(raw).hexdigest(),'producer_status':state['status'],'scientific_approval':False}
    if job.action=='review':
        job.result_summary={**job.result_summary,'repair_proposal_status':'ready' if proposal['total_changes'] else 'no_changes'}
    job.state='proposal_ready' if proposal['total_changes'] else ('needs_revision' if job.result_summary.get('review_report',{}).get('findings_total') else 'completed')
    job.delivery_state='not_applied';job.error_code=None;job.error_message=None


def accept_repair(session_factory,settings,job_id,*,actor_id,proposal_sha256):
    from app.ai_tasks.execution import job_directory
    from app.ai_tasks.repair_apply import apply_delta,design_diff
    from app.ai_tasks.coordinator import reconcile_processes
    from leadtrace.ops.ai_prefill.tasks import _verify_bundle
    from leadtrace.ops.ai_prefill.provenance import export_run_provenance
    with session_factory.begin() as session:
        if settings.environment=='preview':
            from app.ai_prefill.preview_identity import verify_preview_connection
            verify_preview_connection(settings,session.connection())
        initial=session.get(AiTask,job_id)
        if initial is None:raise TaskError('TASK_NOT_FOUND','Task not found')
        paper,workspace,task=target(session,initial.paper_id)
        job=session.scalar(select(AiTask).where(AiTask.id==job_id).with_for_update())
        proposal=job.result_summary.get('proposal',{})
        if (job.action!='repair' and not (job.action=='review' and job.config.get('review_with_repair'))) or proposal.get('sha256')!=proposal_sha256:
            raise TaskError('PROPOSAL_CHANGED','Reload the saved repair proposal before accepting')
        if job.delivery_state=='applied':return
        if job.state!='proposal_ready':raise TaskError('PROPOSAL_NOT_READY','This task has no applicable repair proposal')
        source=session.get(PaperSource,paper.source_id)
        if not check_target(job,workspace,task,source):raise TaskError('WORKSPACE_CHANGED','The draft changed; this proposal cannot overwrite later edits')
        if session.scalar(select(AiTask.id).where(AiTask.paper_id==paper.id,AiTask.id!=job.id,AiTask.state.in_(OPEN))):
            raise TaskError('PAPER_TASK_ACTIVE','Another AI task is active for this paper')
        root=job_directory(settings,job.id);directory=root/'job';state=_verify_bundle(directory)
        if job.config.get('review_revalidation'):
            from app.ai_tasks.review_recovery import validated_recovery
            state=validated_recovery(settings,job)['output_state']
        if state.get('status') not in {'ready_for_independent_review','review_complete','needs_revision','partial'} or state.get('process_cleanup_confirmed') is not True:
            raise TaskError('SAVED_RESULT_UNAVAILABLE','Repair process completion could not be verified')
        reconcile_processes(directory)
        directory,before,after,raw=_candidate(settings,job,job.result_summary)
        baseline_raw=read_artifact(root,'repair-baseline.json')
        if sha256(baseline_raw).hexdigest()!=job.config['baseline_sha256']:raise TaskError('BASELINE_CHANGED','Repair baseline changed')
        baseline=json.loads(baseline_raw)
        current_diff=design_diff(before.payload,after.payload)
        comparison={k:v for k,v in proposal.items() if k not in {'sha256','remaining_findings'}}
        if {k:v for k,v in current_diff.items() if k!='sha256'}!=comparison:
            raise TaskError('PROPOSAL_CHANGED','Repair changes no longer match the displayed proposal')
        result=apply_delta(session,settings=settings,workspace=workspace,source=source,actor_id=actor_id,
            before=before.payload,after=after.payload,baseline_snapshot=baseline['snapshot'],entity_refs=baseline['entity_refs'],job_id=job.id)
        if job.config.get('review_revalidation'):
            from app.ai_tasks.review_recovery import revalidated_provenance
            record=revalidated_provenance(settings,job,applied_workspace_version=workspace.version)
        else:
            record=ProvenanceInput.model_validate(export_run_provenance(directory,directory/'outputs/candidate.json',applied_workspace_version=workspace.version,proposal=job.action=='review'))
        append_provenance(session,workspace=workspace,source_sha256=source.sha256,actor_id=actor_id,record=record)
        job.state='needs_revision';job.stage='accepted';job.delivery_state='applied';job.error_code=None;job.error_message=None
        job.result_summary={**job.result_summary,'applied_workspace_version':workspace.version,'accepted_by':str(actor_id),'accepted_at':now().isoformat(),'scientific_approval':False}
