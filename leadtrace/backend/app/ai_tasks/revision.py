"""Fresh-session directed revision; validated deltas auto-apply to the frozen draft."""
import json
from hashlib import sha256
from app.ai_tasks.service import TaskError, check_target, now
from app.ai_tasks.repair import _candidate
from app.ai_tasks.producer_report import producer_report, read_artifact
from app.ai_tasks.repair_apply import apply_delta, design_diff
from app.ai_prefill.provenance import append_provenance, ProvenanceInput
from leadtrace.ops.ai_prefill.provenance import export_run_provenance
from leadtrace.ops.ai_prefill.tasks import _verify_bundle


def export_revision_baseline(parent, snapshot, entity_map=None):
    """Keep reviewer-only notes in the protected snapshot and read-only feedback."""
    from copy import deepcopy
    from app.ai_prefill.workspace_export import _payload_from_snapshot
    scientific=deepcopy(snapshot)
    for collection in ('evidence','structure_source_images'):
        for row in scientific[collection]:
            row['reviewer_note']=None
    payload,refs,metadata=_payload_from_snapshot(parent,scientific,entity_map or {},snapshot['paper'])
    notes=[{'kind':collection,'ref':refs[row['id']],'note':row['reviewer_note']}
           for collection in ('evidence','structure_source_images') for row in snapshot[collection]
           if row.get('reviewer_note')]
    return payload,refs,metadata,notes


def require_explicit_revision_fields(before, raw, path='payload'):
    """Omission is not authorization to clear populated reviewer fields.

    Named entities match stable refs; reference-only collections match their keys.
    Unkeyed metadata lists require all previously populated keys explicitly, even
    after reordering; unknown/new values may be explicitly null. Explicit null or
    empty collections are intentional values, still subject to scientific review.
    """
    if path=='payload' and isinstance(before,dict) and isinstance(raw,dict):
        # Edges keep a global identity when regrouped into another/new Lineage.
        old_edges={edge['ref']:edge for group in before.get('lineages',[]) for edge in group.get('edges',[])}
        for group in raw.get('lineages',[]):
            for edge in group.get('edges',[]):
                if edge.get('ref') in old_edges:
                    require_explicit_revision_fields(old_edges[edge['ref']],edge,f"payload/edges/{edge['ref']}")
    if isinstance(before,dict) and isinstance(raw,dict):
        for key,value in before.items():
            if value is None or value == '' or value == [] or value == {}:
                continue
            if path.endswith('/structure') and key in {'smiles','molfile'} and (raw.get('smiles') or raw.get('molfile')):
                continue  # Either complete representation is permitted.
            if key not in raw:
                raise TaskError('REVISION_INCOMPLETE',f'Revision omitted populated field {path}/{key}; no changes were applied')
            require_explicit_revision_fields(value,raw[key],f'{path}/{key}')
    elif isinstance(before,list) and isinstance(raw,list):
        keys = ('ref',) if any(isinstance(x,dict) and 'ref' in x for x in before) else (
            ('edge_ref','evidence_ref') if path.endswith('/edge_evidence_links') else
            ('compound_ref',) if path.endswith('/members') else ())
        if keys:
            old={tuple(x.get(k) for k in keys):x for x in before if isinstance(x,dict)}
            for index,item in enumerate(raw):
                if isinstance(item,dict):
                    prior=old.get(tuple(item.get(k) for k in keys))
                    if prior is not None:require_explicit_revision_fields(prior,item,f'{path}/{index}')
        elif path.endswith('/activities'):
            from app.ai_tasks.repair_apply import _activity_pairs, _flat
            from app.ai_prefill.contracts import AiActivity, AiPrefillPayload
            def normalized(items):
                # Use exactly the writer's serialization/default/decimal normalization.
                # References were already validated by _candidate, not by this projection.
                projection=AiPrefillPayload(schema_version=1).model_copy(update={
                    'activities':[AiActivity.model_validate(item) for item in items]})
                return list(_flat(projection)['activities'].values())
            matches=_activity_pairs(normalized(before),normalized(raw))
            for index,item in enumerate(raw):
                key=matches[index]
                if not key.startswith('activity:new:'):
                    require_explicit_revision_fields(before[int(key.split(':')[1])],item,f'{path}/{index}')
        else:
            # Without stable IDs, positional matching can silently clear a field
            # after reordering. Require the union of populated field shapes rather
            # than guess identity; explicit null still expresses unknown/cleared data.
            for index,item in enumerate(raw):
                for prior in before:
                    require_explicit_revision_fields(prior,item,f'{path}/{index}')


def deliver_revision(session, settings, job, state, workspace, task, source):
    if not check_target(job,workspace,task,source):
        job.state='superseded';job.delivery_state='conflict';job.error_code='WORKSPACE_CHANGED'
        job.error_message='草稿或分配已变化，AI 修订结果已保留，未覆盖当前草稿。请基于最新草稿重新发起修订。'
        return
    directory,before,after,raw=_candidate(settings,job,state)
    require_explicit_revision_fields(before.payload.model_dump(mode='json'),json.loads(raw)['payload'])
    saved=_verify_bundle(directory)
    if saved.get('process_cleanup_confirmed') is not True or saved.get('status') not in {'ready_for_independent_review','needs_revision','partial'}:
        raise TaskError('SAVED_RESULT_UNAVAILABLE','Revision completion could not be verified')
    baseline_raw=read_artifact(directory.parent,'repair-baseline.json')
    if sha256(baseline_raw).hexdigest()!=job.config['baseline_sha256']:
        raise TaskError('BASELINE_CHANGED','Revision baseline changed')
    baseline=json.loads(baseline_raw)
    diagnostics=producer_report(directory,after,raw)
    # Validate provenance before any mutation; the entire delivery is one transaction.
    provenance=export_run_provenance(directory,directory/'outputs/candidate.json')
    diff=design_diff(before.payload,after.payload)
    result=apply_delta(session,settings=settings,workspace=workspace,source=source,actor_id=job.requested_by_id,
        before=before.payload,after=after.payload,baseline_snapshot=baseline['snapshot'],entity_refs=baseline['entity_refs'],job_id=job.id,automatic_revision=True)
    if diff['total_changes']:
        provenance['applied_workspace_version']=workspace.version
        append_provenance(session,workspace=workspace,source_sha256=source.sha256,actor_id=job.requested_by_id,
                          record=ProvenanceInput.model_validate(provenance))
    job.result_summary={**job.result_summary,'report_available':True,'report_kind':'revise','producer_report':diagnostics,
        'candidate_file_sha256':sha256(raw).hexdigest(),'producer_status':state['status'],'scientific_approval':False,
        'revision_changes':{'counts':diff['counts'],'total_changes':diff['total_changes']},
        'applied_workspace_version':workspace.version,'completed_at':now().isoformat()}
    diagnostics['delivery_notes']=result.get('delivery_notes',[])
    job.state='needs_revision' if diagnostics['status']=='needs_revision' else 'completed'
    job.delivery_state='applied' if diff['total_changes'] else 'not_applicable'
    job.error_code=None;job.error_message=None
