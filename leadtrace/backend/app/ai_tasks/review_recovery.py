"""Operator recovery of a completed review rejected by an old output reader.

No model calls or science application. Original run files remain immutable;
server-owned, hash-bound revalidation is required again at explicit acceptance.
"""
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from sqlalchemy import select
from app.ai_tasks.models import AiTask
from app.ai_tasks.producer_report import read_artifact
from app.ai_tasks.service import TaskError, target, check_target, OPEN, now
from app.ai_prefill.provenance import ProvenanceInput, append_provenance
from app.catalog.models import PaperSource
from app.workspaces.snapshot import build_paper_snapshot


def validated_recovery(settings, job):
    from app.ai_tasks.execution import job_directory
    from leadtrace.ops.ai_prefill.tasks import _verify_bundle
    root=job_directory(settings,job.id)
    binding=job.config.get('review_revalidation')
    if not binding or Path(binding['file']).name!=binding['file']:
        raise TaskError('REVALIDATION_MISSING','Saved review revalidation is unavailable')
    raw=read_artifact(root,binding['file'])
    if sha256(raw).hexdigest()!=binding['sha256']:
        raise TaskError('REVALIDATION_CHANGED','Saved review revalidation changed')
    receipt=json.loads(raw)
    if (receipt['job_id']!=str(job.id) or receipt['source_sha256']!=job.source_sha256
        or receipt['workspace_id']!=str(job.workspace_id) or receipt['workspace_version']!=job.workspace_version):
        raise TaskError('REVALIDATION_CHANGED','Revalidation target does not match this task')
    original=_verify_bundle(root/'job')
    if original.get('status')!='failed' or original.get('exit_code')!=0 or original.get('process_cleanup_confirmed') is not True:
        raise TaskError('REVALIDATION_CHANGED','Original completed process can no longer be verified')
    for name,digest in receipt['artifact_hashes'].items():
        if sha256(read_artifact(root/'job',name)).hexdigest()!=digest:
            raise TaskError('REVALIDATION_CHANGED','Saved review artifacts changed after revalidation')
    return receipt


def revalidated_provenance(settings, job, *, applied_workspace_version=None):
    from app.ai_tasks.execution import job_directory
    from leadtrace.ops.ai_prefill.provenance import export_run_provenance
    receipt=validated_recovery(settings,job)
    directory=job_directory(settings,job.id)/'job'
    record=export_run_provenance(directory,directory/'inputs/current-candidate.json')
    # Preserve actual runtime/model evidence, attest only the new deterministic check.
    record.update(run_key=record['run_key']+':revalidation',
        evidence_sha256=job.config['review_revalidation']['sha256'],
        outcome='partial' if receipt['output_state']['status']=='partial' else 'needs_revision',
        completed_at=receipt['revalidated_at'])
    if applied_workspace_version is not None:
        record.update(run_key=record['run_key']+':repair',stage='repair',
            candidate_file_sha256=receipt['output_state']['candidate_file_sha256'],
            applied_workspace_version=applied_workspace_version)
    return ProvenanceInput.model_validate(record)


def recover_saved_review(session_factory, settings, job_id, *, actor_id):
    """Recover only exit-zero, cleaned-up combined reviews with an applicable proposal."""
    from app.ai_tasks.execution import job_directory, save_json, report_for
    from app.ai_tasks.coordinator import reconcile_processes
    from app.ai_tasks.repair import finish_proposal, science_snapshot_hash
    from leadtrace.ops.ai_prefill.tasks import _verify_bundle, _postflight
    from leadtrace.ops.ai_prefill.review_coverage import review_report_name
    from leadtrace.ops.ai_prefill.provenance import export_run_provenance
    with session_factory.begin() as session:
        if settings.environment=='preview':
            from app.ai_prefill.preview_identity import verify_preview_connection
            verify_preview_connection(settings,session.connection())
        initial=session.get(AiTask,job_id)
        if initial is None:raise TaskError('TASK_NOT_FOUND','Task not found')
        paper,workspace,assignment=target(session,initial.paper_id)
        job=session.scalar(select(AiTask).where(AiTask.id==job_id).with_for_update())
        if job.config.get('review_revalidation'):
            validated_recovery(settings,job)
            return
        if job.action!='review' or job.state!='failed' or job.error_code!='RUN_FAILED' or not job.config.get('review_with_repair'):
            raise TaskError('REVALIDATION_NOT_AVAILABLE','Only completed reviews rejected during output validation can be recovered')
        source=session.get(PaperSource,paper.source_id)
        if not check_target(job,workspace,assignment,source):
            raise TaskError('WORKSPACE_CHANGED','The reviewed draft changed; its old proposal cannot overwrite edits')
        if session.scalar(select(AiTask.id).where(AiTask.paper_id==job.paper_id,AiTask.id!=job.id,AiTask.state.in_(OPEN))):
            raise TaskError('PAPER_TASK_ACTIVE','Another AI task is active for this article')
        root=job_directory(settings,job.id);directory=root/'job'
        state=_verify_bundle(directory)
        if state.get('status')!='failed' or state.get('exit_code')!=0 or state.get('process_cleanup_confirmed') is not True:
            raise TaskError('REVALIDATION_NOT_AVAILABLE','The model process did not finish normally with confirmed cleanup')
        reconcile_processes(directory)
        task=json.loads(read_artifact(directory,'task.json'))
        if task['entry']!='review' or not task.get('review_with_repair'):
            raise TaskError('REVALIDATION_NOT_AVAILABLE','Frozen task does not include review and repair')
        attestation=export_run_provenance(directory,directory/'inputs/current-candidate.json')
        if attestation['verification']=='mismatch':
            raise TaskError('CONFIGURATION_MISMATCH','Mismatched model configuration cannot be recovered')
        baseline_raw=read_artifact(root,'repair-baseline.json')
        if sha256(baseline_raw).hexdigest()!=job.config['baseline_sha256']:
            raise TaskError('BASELINE_CHANGED','The server-owned baseline changed')
        if science_snapshot_hash(json.loads(baseline_raw)['snapshot'])!=science_snapshot_hash(build_paper_snapshot(session,workspace.id)):
            raise TaskError('WORKSPACE_CHANGED','The reviewed content changed')
        # Rebuild the baseline report instead of trusting any previous UI recovery.
        previous={'state':job.state,'error_code':job.error_code,'error_message':job.error_message,'result_summary':job.result_summary}
        job.result_summary={}
        report=report_for(settings,job)
        summary=json.loads(read_artifact(directory,'outputs/audit-summary.json'))
        names={'inputs/current-candidate.json','inputs/compound-inventory.json','outputs/audit-summary.json',
            'outputs/candidate.json','outputs/compound-inventory.json','outputs/self-review.json'}
        names.update('outputs/'+review_report_name(name) for name in summary['item_reports'])
        artifacts={name:read_artifact(directory,name) for name in names}
        # Only copy structured outputs; never read source content or modify frozen artifacts.
        with TemporaryDirectory(prefix='leadtrace-review-check-') as temporary:
            check_dir=Path(temporary)
            for name,raw in artifacts.items():
                path=check_dir/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            (check_dir/'checks').mkdir()
            status,details=_postflight(check_dir,task)
        if status not in {'review_complete','partial'} or details.get('repair_proposal_status')!='ready':
            raise TaskError('PROPOSAL_INVALID','Saved output did not produce an applicable review repair proposal')
        output_state={'status':status,**details,'process_cleanup_confirmed':True}
        job.config={**job.config,'review_rows_sha256':report['review_rows_sha256']}
        job.result_summary={'review_report':report,'review_rows_sha256':report['review_rows_sha256'],
            'reviewed_workspace_version':job.workspace_version,'repair_proposal_errors':[]}
        finish_proposal(session,settings,job,output_state,workspace,assignment,source)
        for name in ('state.json','runtime-provenance.json','task.json','bundle-manifest.json'):
            artifacts[name]=read_artifact(directory,name)
        receipt={'version':1,'job_id':str(job.id),'source_sha256':job.source_sha256,
            'workspace_id':str(job.workspace_id),'workspace_version':job.workspace_version,
            'actor_id':str(actor_id),'revalidated_at':now().isoformat(),
            'reason':'Saved completed review revalidated with corrected output reader',
            'original_job':previous,'output_state':output_state,
            'artifact_hashes':{name:sha256(raw).hexdigest() for name,raw in artifacts.items()},
            'model_calls':0,'scientific_approval':False}
        filename='review-revalidation-'+uuid4().hex+'.json'
        save_json(root/filename,receipt)
        job.config={**job.config,'review_revalidation':{'file':filename,'sha256':sha256((root/filename).read_bytes()).hexdigest()}}
        append_provenance(session,workspace=workspace,source_sha256=source.sha256,actor_id=actor_id,
            record=revalidated_provenance(settings,job))
        job.stage=job.state
        job.heartbeat_at=now()
