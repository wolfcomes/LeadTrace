"""Version-checked, additive metadata delivery into an existing human draft.

Operator-only: callers own the transaction and scientific acceptance. This does
not submit, approve, replace human content, or manufacture AI run attestations.
"""
from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_prefill.models import AiExtractionRun, AiExtractionRunStatus
from app.ai_prefill.provenance import ProvenanceInput
from app.ai_tasks.models import AiTask
from app.audit.models import AuditEvent
from app.audit.service import AuditService, canonical_content_hash
from app.catalog.models import PaperSource
from app.jobs.models import CropJob, CropJobStatus
from app.papers.metadata import (
    ARTICLE_METADATA_DEFAULTS, ArticleMetadata, metadata_values,
    validate_article_evidence_sources,
)
from app.publications.metadata_supplement import (
    validate_classification_replacement, validate_evidence_additions,
)
from app.publications.models import PublishedPaperVersion
from app.publications.service import PublicationService
from app.users.models import User, UserRole
from app.workspaces.history import lock_workspace
from app.workspaces.models import (
    ChangeActorKind, ChangeEvent, PaperSectionReview, PaperSectionState, PaperSubmission,
    PaperWorkspace, ReviewTask, ReviewTaskState, WorkspaceState,
)
from app.workspaces.snapshot import build_paper_snapshot, canonical_snapshot_hash


def additive_metadata_delta(before: dict, after: dict) -> list[tuple[tuple, object, object]]:
    """Return only added field/group/evidence paths; reject replacements/removals.

    The projection uses the same rules as delivery. Whole profile replacement
    would conceal unrelated human edits, so populated groups are never copied.
    """
    if (not isinstance(before, dict) or not isinstance(after, dict) or not before
            or set(before) != set(after) or not set(before) <= ARTICLE_METADATA_DEFAULTS.keys()):
        raise ValueError('An additive article metadata delta is required')
    changes = []

    def evidence(field, old, new, group=None):
        a = {field: {group: old} if group is not None else old}
        b = {field: {group: new} if group is not None else new}
        validate_evidence_additions(a, b)
        for index, (previous, current) in enumerate(zip(old, new)):
            if previous.get('evidence', []) != current.get('evidence', []):
                path = (field, group, index, 'evidence') if group is not None else (field, index, 'evidence')
                changes.append((path, deepcopy(previous.get('evidence', [])), deepcopy(current['evidence'])))

    for field, old in before.items():
        new = after[field]
        if old == new:
            raise ValueError('Metadata updates must change a missing value or add evidence')
        if field == 'research_profile':
            if not isinstance(old, dict) or not isinstance(new, dict):
                raise ValueError('Research profiles must be objects')
            if old.get('molecular_forms', []) != new.get('molecular_forms', []):
                raise ValueError('Preserve legacy molecular_forms; do not add new values')
            for group in set(old) | set(new):
                previous, current = old.get(group, []), new.get(group, [])
                if previous == current:
                    # A present historical group must retain its raw shape.
                    if group in old and group not in new:
                        raise ValueError('Preserve every historical research profile group')
                    continue
                if not isinstance(previous, list) or not isinstance(current, list) or not current:
                    raise ValueError('Only missing profile groups may be supplemented')
                if previous:
                    evidence(field, previous, current, group)
                else:
                    if group == 'modalities':
                        validate_classification_replacement({}, {'modalities': current})
                    changes.append(((field, group), deepcopy(previous), deepcopy(current)))
        elif field == 'pdb_references' and old:
            evidence(field, old, new)
        elif old != ARTICLE_METADATA_DEFAULTS[field] or new == ARTICLE_METADATA_DEFAULTS[field]:
            raise ValueError('Only missing metadata may be supplemented; preserve populated values')
        else:
            changes.append(((field,), deepcopy(old), deepcopy(new)))
    if not changes:
        raise ValueError('Metadata supplement must add a nondefault value or evidence')
    return changes


def validated_runtime_provenance(value: dict, source_sha256: str) -> dict:
    record = ProvenanceInput.model_validate(value)
    if (record.source_sha256 != source_sha256 or record.outcome not in {'completed', 'partial'}
            or record.verification == 'mismatch' or not record.adapter or not record.model
            or not record.completed_at or not record.evidence_sha256 or not record.guide_bundle_sha256
            or record.stage not in {'prefill', 'repair', 'producer_self_check'}):
        raise ValueError('Completed source-matched scientific runtime provenance and acceptance evidence are required')
    return record.model_dump(mode='json')


def _approved_baseline(snapshot):
    result = deepcopy(snapshot)
    # These are operational projections, not scientific records. Submission
    # computes section progress; approvals increment the live workspace version.
    for field in ('workspace_version', 'ai_provenance', 'sections', 'review_progress'):
        result.pop(field, None)
    result['paper'] = ARTICLE_METADATA_DEFAULTS | result['paper']
    return result


def supplement_draft_metadata(session: Session, *, workspace_id: UUID,
        expected_workspace_version: int, expected_snapshot_hash: str,
        updates: dict, reason: str, actor: User, request_id: str, provenance: dict,
        allow_published_revision: bool = False,
        expected_published_version_id: UUID | None = None) -> dict:
    """Apply one accepted additive proposal; return an audited, replayable receipt."""
    actor = session.scalar(select(User).where(User.id == actor.id).execution_options(populate_existing=True))
    if actor is None or actor.role is not UserRole.ADMIN or not actor.is_enabled:
        raise PermissionError('An enabled Admin is required')
    reason, request_id = reason.strip(), request_id.strip()
    if not reason or not request_id or len(request_id) > 128 or not isinstance(updates, dict) or not updates:
        raise ValueError('A reason, request identity and nonempty metadata patch are required')
    if not set(updates) <= ARTICLE_METADATA_DEFAULTS.keys():
        raise ValueError('Only article metadata may be supplemented')
    context = lock_workspace(session, workspace_id)
    if context is None:
        raise ValueError('Active article workspace not found')
    workspace, task, paper = context.workspace, context.task, context.paper
    session.refresh(workspace)
    source = session.scalar(select(PaperSource).where(PaperSource.id == paper.source_id)
        .with_for_update().execution_options(populate_existing=True))
    if source is None:
        raise ValueError('Article source is missing')
    runtime = validated_runtime_provenance(provenance, source.sha256)
    request_identity = dict(workspace_id=str(workspace_id), expected_workspace_version=expected_workspace_version,
        expected_snapshot_hash=expected_snapshot_hash, updates=updates, reason=reason, actor_id=str(actor.id),
        request_id=request_id, provenance=runtime, allow_published_revision=allow_published_revision,
        expected_published_version_id=str(expected_published_version_id) if expected_published_version_id else None)
    request_digest = canonical_content_hash(request_identity)
    prior = session.scalar(select(AuditEvent).where(AuditEvent.actor_id == actor.id,
        AuditEvent.action == 'paper.article_metadata_supplement', AuditEvent.request_id == request_id))
    if prior:
        if prior.details.get('request_payload_sha256') != request_digest:
            raise ValueError('Request identity already has a different metadata payload')
        return deepcopy(prior.details['receipt'])
    if workspace.version != expected_workspace_version:
        raise RuntimeError('Workspace changed; inspect a fresh version')
    current = build_paper_snapshot(session, workspace.id)
    if canonical_snapshot_hash(current) != expected_snapshot_hash:
        raise RuntimeError('Workspace snapshot changed; inspect a fresh baseline')
    PublicationService._require_verified_source(session, paper)
    if session.scalar(select(AiTask.id).where(AiTask.paper_id == paper.id,
            AiTask.state.in_({'queued', 'preparing', 'running', 'validating', 'delivering', 'cancel_requested'})).limit(1)):
        raise RuntimeError('An AI task is active for this article')
    if session.scalar(select(AiExtractionRun.id).where(AiExtractionRun.paper_id == paper.id,
            AiExtractionRun.status.in_({AiExtractionRunStatus.QUEUED, AiExtractionRunStatus.RUNNING})).limit(1)):
        raise RuntimeError('An AI extraction run is active for this article')
    if session.scalar(select(CropJob.id).where(CropJob.source_asset_id == source.asset_id,
            CropJob.status.in_({CropJobStatus.PENDING, CropJobStatus.RUNNING})).limit(1)):
        raise RuntimeError('An article crop job is active')
    active_other = session.scalar(select(ReviewTask.id).where(ReviewTask.paper_id == paper.id,
        ReviewTask.id != task.id, ReviewTask.status.notin_({ReviewTaskState.APPROVED, ReviewTaskState.ARCHIVED})).limit(1))
    if active_other:
        raise RuntimeError('Another active workspace generation exists')
    reopening = workspace.state is WorkspaceState.APPROVED
    if reopening:
        if (not allow_published_revision or not expected_published_version_id
                or paper.current_published_version_id != expected_published_version_id
                or task.status is not ReviewTaskState.APPROVED or not task.assigned_reviewer_id):
            raise RuntimeError('Published revision requires explicit authorization and the exact current published version')
        published = session.get(PublishedPaperVersion, expected_published_version_id)
        published_submission = session.get(PaperSubmission, published.submission_id) if published else None
        if (published_submission is None or published_submission.workspace_id != workspace.id
                or published_submission.review_task_id != task.id):
            raise RuntimeError('Revision must reopen the published submission workspace')
        if (published is None or published.paper_id != paper.id
                or canonical_snapshot_hash(published.snapshot) != published.content_hash
                or _approved_baseline(current) != _approved_baseline(published.snapshot)):
            raise RuntimeError('Approved workspace does not match the current published scientific baseline')
    elif (workspace.state is not WorkspaceState.EDITING
            or task.status not in {ReviewTaskState.ASSIGNED, ReviewTaskState.UNASSIGNED, ReviewTaskState.CHANGES_REQUESTED}):
        raise RuntimeError('Only editable article drafts may be supplemented')
    elif allow_published_revision or expected_published_version_id:
        raise ValueError('Published revision authorization only applies to its approved workspace')

    merged = metadata_values(paper) | deepcopy(updates)
    if 'research_profile' in updates:
        if not isinstance(updates['research_profile'], dict):
            raise ValueError('Research profile must be an object')
        merged['research_profile'] = deepcopy(paper.research_profile) | deepcopy(updates['research_profile'])
    validated = ArticleMetadata.model_validate(merged).model_dump(mode='json')
    # Validate raw nested values but never normalize existing JSON or reorder it.
    patch = {field: deepcopy(merged[field] if field in {'research_profile', 'pdb_references'} else validated[field]) for field in updates}
    before = {field: deepcopy(getattr(paper, field)) for field in patch}
    additive_metadata_delta(before, patch)
    validate_article_evidence_sources(patch, page_count=source.page_count, sha256=source.sha256)
    if any(ref.get('source_page') and ref['source_page'] > source.page_count for ref in patch.get('pdb_references', [])):
        raise ValueError('PDB source page is outside the article')
    # This operator has only the main source identity. A scientific reader may
    # record unavailable SI in its coverage report, but cannot fabricate a source.
    old_evidence = {canonical_content_hash(item) for entry in [
        *(x for group in paper.research_profile.values() for x in group), *paper.pdb_references]
        for item in entry.get('evidence', [])}
    for entry in [*(x for group in patch.get('research_profile', {}).values() for x in group), *patch.get('pdb_references', [])]:
        for item in entry.get('evidence', []):
            if item['source_kind'] == 'supplement' and canonical_content_hash(item) not in old_evidence:
                raise ValueError('New supplement evidence requires separately verified SI sources')
    section = session.scalar(select(PaperSectionReview).where(PaperSectionReview.workspace_id == workspace.id,
        PaperSectionReview.section_key == 'bibliography'))
    if section is None:
        raise ValueError('Bibliography section is missing')

    revision_event = None
    if reopening:
        prior_state = dict(workspace_state=workspace.state.value, workspace_version=workspace.version,
            task_status=task.status.value, task_version=task.version,
            published_version_id=str(paper.current_published_version_id))
        workspace.state, task.status = WorkspaceState.EDITING, ReviewTaskState.ASSIGNED
        task.version += 1
        revision_event = ChangeEvent(paper_id=paper.id, workspace_id=workspace.id,
            entity_type='paper_workspace', entity_id=workspace.id, action='workspace.metadata_revision_started',
            before_value=prior_state,
            after_value=dict(workspace_state='editing', workspace_version=workspace.version + 1,
                task_status='assigned', task_version=task.version,
                published_version_id=str(paper.current_published_version_id)),
            actor_kind=ChangeActorKind.ADMIN, actor_id=actor.id, occurred_at=datetime.now(timezone.utc))
        session.add(revision_event)
    for field, value in patch.items():
        setattr(paper, field, value)
    workspace.version += 1
    event = ChangeEvent(paper_id=paper.id, workspace_id=workspace.id, entity_type='paper', entity_id=paper.id,
        action='bibliography.ai_supplement', before_value=before, after_value=patch,
        actor_kind=ChangeActorKind.AI, actor_id=None, occurred_at=datetime.now(timezone.utc))
    session.add(event)
    if section.state is not PaperSectionState.PENDING:
        session.add(ChangeEvent(paper_id=paper.id, workspace_id=workspace.id,
            entity_type='paper_section_review', entity_id=section.id, action='section.update',
            before_value=dict(section_key='bibliography', state=section.state.value, note=section.note),
            after_value=dict(section_key='bibliography', state='pending', note=section.note),
            actor_kind=ChangeActorKind.AI, actor_id=None, occurred_at=datetime.now(timezone.utc)))
        section.state = PaperSectionState.PENDING
    session.flush()
    after_hash = canonical_snapshot_hash(build_paper_snapshot(session, workspace.id))
    receipt = dict(workspace_id=str(workspace.id), paper_id=str(paper.id), paper_key=paper.paper_key,
        workspace_version=workspace.version, before_hash=expected_snapshot_hash, after_hash=after_hash,
        source_sha256=source.sha256, fields=sorted(patch), change_event_id=str(event.id),
        request_id=request_id, request_payload_sha256=request_digest,
        published_revision_started=reopening,
        current_published_version_id=str(paper.current_published_version_id) if paper.current_published_version_id else None)
    common = dict(actor_id=actor.id, target_type='paper', target_id=paper.id, paper_id=paper.id,
        changeset_id=None, release_id=None, ip_address='127.0.0.1', request_id=request_id,
        result='success', reason=reason, before_hash=expected_snapshot_hash, after_hash=after_hash)
    AuditService().append_event(session, action='paper.article_metadata_supplement', **common,
        details=dict(workspace_id=str(workspace.id), change_event_id=str(event.id),
            event_payload_sha256=canonical_content_hash({'before': before, 'after': patch}),
            source_sha256=source.sha256, request_payload_sha256=request_digest,
            request_identity=request_identity, provenance=runtime, receipt=receipt))
    if revision_event:
        AuditService().append_event(session, action='workspace.metadata_revision_started', **common,
            details=dict(workspace_id=str(workspace.id), change_event_id=str(revision_event.id),
                published_version_id=str(paper.current_published_version_id),
                published_snapshot_unchanged=True, confirmations_preserved=True))
    return receipt
