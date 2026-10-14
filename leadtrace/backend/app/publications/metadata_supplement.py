"""Operator-only article-metadata revisions of pending submissions.

Call inside a transaction. No HTTP endpoint or Reviewer impersonation is used.
The old immutable submission is returned for the stated administrative reason;
the replacement remains pending, with its bibliography explicitly unconfirmed.
"""
from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import AuditService, canonical_content_hash
from app.catalog.models import PaperSource
from app.papers.metadata import ArticleMetadata, ARTICLE_METADATA_DEFAULTS, metadata_values
from app.publications.models import AdminDecisionAction
from app.publications.service import PublicationService
from app.users.models import User, UserRole
from app.workspaces.history import lock_workspace
from app.workspaces.models import (
    ChangeActorKind, ChangeEvent, PaperSection, PaperSectionReview,
    PaperSectionState, PaperSubmission, ReviewTaskState, WorkspaceState,
)
from app.workspaces.snapshot import build_paper_snapshot, canonical_snapshot_hash

FIELDS = frozenset(ARTICLE_METADATA_DEFAULTS)


def validate_evidence_additions(before: dict, after: dict) -> None:
    """Allow only appended evidence; identity, order and all human fields stay exact."""
    additions = 0
    def entries(old, new):
        nonlocal additions
        if len(old) != len(new):
            raise ValueError('Evidence supplement must preserve every entry')
        for a, b in zip(old, new):
            if {k: v for k, v in a.items() if k != 'evidence'} != {k: v for k, v in b.items() if k != 'evidence'}:
                raise ValueError('Evidence supplement cannot change existing scientific fields')
            if 'evidence' in a and 'evidence' not in b:
                raise ValueError('Evidence supplement cannot remove evidence fields')
            previous, current = a.get('evidence', []), b.get('evidence', [])
            additions += len(current) - len(previous)
            if current[:len(previous)] != previous or len(current) < len(previous):
                raise ValueError('Evidence supplement must retain prior evidence')
    if set(before) != set(after):
        raise ValueError('Evidence baseline must cover every updated metadata field')
    for field in before:
        if field == 'research_profile':
            if set(before[field]) != set(after[field]):
                raise ValueError('Evidence supplement must preserve profile groups')
            for group in before[field]:
                entries(before[field][group], after[field][group])
        elif field == 'pdb_references':
            entries(before[field], after[field])
        else:
            raise ValueError('Evidence supplement accepts profile and PDB evidence only')
    if additions <= 0:
        raise ValueError('Evidence supplement must add evidence')


def supplement_metadata(
    session: Session, *, submission_id: UUID, content_hash: str,
    expected_workspace_version: int, updates: dict, reason: str,
    actor: User, request_id: str,
    expected_existing: dict | None = None,
    expected_section_note: str | None = None,
    expected_evidence_baseline: dict | None = None,
) -> PaperSubmission:
    if actor.role is not UserRole.ADMIN or not actor.is_enabled:
        raise PermissionError('An enabled Admin is required')
    reason = reason.strip()
    if not reason or not updates or not set(updates) <= FIELDS:
        raise ValueError('A reason and an article-metadata-only patch are required')
    expected_existing = expected_existing or {}
    if not set(expected_existing) <= {'abstract_note'} or not set(expected_existing) <= set(updates):
        raise ValueError('Only an explicitly matched Abstract note may be replaced')
    if expected_evidence_baseline is not None:
        if expected_existing or expected_section_note is not None:
            raise ValueError('Evidence supplements cannot clean up other metadata')
        validate_evidence_additions(expected_evidence_baseline, updates)
    original = session.get(PaperSubmission, submission_id)
    if original is None:
        raise ValueError('Submission not found')
    context = lock_workspace(session, original.workspace_id)
    if context is None:
        raise ValueError('Active workspace not found')
    request_identity = {
        'original': str(submission_id), 'hash': content_hash,
        'version': expected_workspace_version, 'updates': updates,
        'reason': reason, 'actor': str(actor.id),
    }
    # Keep the original key shape for already executed additive requests.
    if expected_existing:
        request_identity['expected_existing'] = expected_existing
    if expected_section_note is not None:
        request_identity['expected_section_note'] = expected_section_note
    if expected_evidence_baseline is not None:
        request_identity['expected_evidence_baseline'] = expected_evidence_baseline
    key = 'metadata-supplement:' + canonical_content_hash(request_identity)
    replay = session.scalar(select(PaperSubmission).where(
        PaperSubmission.workspace_id == original.workspace_id,
        PaperSubmission.idempotency_key == key,
    ))
    if replay is not None:
        return replay
    workspace, task, paper = context.workspace, context.task, context.paper
    session.refresh(workspace)
    if workspace.version != expected_workspace_version:
        raise RuntimeError('Workspace changed; read and review a fresh baseline')
    if original.content_hash != content_hash or canonical_snapshot_hash(original.snapshot) != content_hash:
        raise RuntimeError('Frozen submission hash mismatch')
    current = build_paper_snapshot(session, workspace.id)
    # Progress-derived section states can differ from stored rows on submission.
    # All scientific content and bibliography must still match the frozen record.
    excluded = {'sections', 'review_progress', 'paper'}
    if ({k: v for k, v in current.items() if k not in excluded}
            != {k: v for k, v in original.snapshot.items() if k not in excluded}):
        raise RuntimeError('Workspace no longer matches frozen submission')
    if (ARTICLE_METADATA_DEFAULTS | current['paper']) != (ARTICLE_METADATA_DEFAULTS | original.snapshot['paper']):
        raise RuntimeError('Bibliography no longer matches frozen submission')
    validated = ArticleMetadata.model_validate(metadata_values(paper) | updates).model_dump(mode='json')
    patch = {field: validated[field] for field in updates}
    if expected_evidence_baseline is not None:
        if any(getattr(paper, field) != baseline for field, baseline in expected_evidence_baseline.items()):
            raise ValueError('Evidence baseline changed; preserve current human edits')
        # Validate above but retain exact historical serialization and human fields.
        patch = deepcopy(updates)
    for field, value in patch.items():
        if expected_evidence_baseline is not None:
            continue
        if field in expected_existing:
            if getattr(paper, field) != expected_existing[field] or value == expected_existing[field]:
                raise ValueError('Abstract note changed or replacement is unchanged')
            continue
        if value == ARTICLE_METADATA_DEFAULTS[field] or getattr(paper, field) != ARTICLE_METADATA_DEFAULTS[field]:
            raise ValueError('Only missing metadata may be supplemented')
    if 'pdb_references' in patch:
        source = session.get(PaperSource, paper.source_id)
        if source is None or any(ref.get('source_page') and ref['source_page'] > source.page_count for ref in patch['pdb_references']):
            raise ValueError('PDB source page is outside the article')
    source = session.get(PaperSource, paper.source_id)
    if source is None:
        raise ValueError('Article source is missing')
    for entries in [*patch.get('research_profile', {}).values(), patch.get('pdb_references', [])]:
        for entry in entries:
            for evidence in entry.get('evidence', []):
                if evidence['source_kind'] == 'main_pdf' and (evidence['page_number'] > source.page_count or (evidence.get('source_sha256') and evidence['source_sha256'] != source.sha256)):
                    raise ValueError('Article evidence page or source identity mismatch')
    section = session.scalar(select(PaperSectionReview).where(
        PaperSectionReview.workspace_id == workspace.id,
        PaperSectionReview.section_key == PaperSection.BIBLIOGRAPHY,
    ))
    if section is None:
        raise ValueError('Bibliography section is missing')
    note = section.note
    if expected_section_note is not None:
        if section.note != expected_section_note:
            raise ValueError('Bibliography note changed; preserve the new note')
        note = None

    PublicationService().decide(
        session, submission_id=original.id, content_hash=content_hash,
        action=AdminDecisionAction.REQUEST_CHANGES, reason=reason,
        idempotency_key=key + ':return', actor=actor,
    )
    before = {field: deepcopy(getattr(paper, field)) for field in patch}
    for field, value in patch.items():
        setattr(paper, field, value)
    workspace.version += 1
    session.add(ChangeEvent(
        paper_id=paper.id, workspace_id=workspace.id, entity_type='paper', entity_id=paper.id,
        action='bibliography.update', before_value=before, after_value=patch,
        actor_kind=ChangeActorKind.ADMIN, actor_id=actor.id,
        occurred_at=datetime.now(timezone.utc),
    ))
    # Keep human notes unless an explicit, exact-value cleanup was requested.
    # Operator attribution and explanations remain in history/audit.
    session.add(ChangeEvent(
        paper_id=paper.id, workspace_id=workspace.id, entity_type='paper_section_review', entity_id=section.id,
        action='section.update', before_value={'section_key': 'bibliography', 'state': section.state.value, 'note': section.note},
        after_value={'section_key': 'bibliography', 'state': 'pending', 'note': note}, actor_kind=ChangeActorKind.ADMIN,
        actor_id=actor.id, occurred_at=datetime.now(timezone.utc),
    ))
    section.state, section.note = PaperSectionState.PENDING, note
    workspace.state, task.status = WorkspaceState.SUBMITTED, ReviewTaskState.SUBMITTED
    workspace.version += 1
    task.version += 1
    snapshot = deepcopy(original.snapshot)
    snapshot['paper'].update(patch)
    snapshot['workspace_version'] = workspace.version
    for row in snapshot['sections']:
        if row['section_key'] == 'bibliography':
            row.update(state='pending', note=note)
    replacement = PaperSubmission(
        paper_id=paper.id, workspace_id=workspace.id, review_task_id=task.id,
        submission_number=original.submission_number + 1, idempotency_key=key,
        snapshot=snapshot, content_hash=canonical_snapshot_hash(snapshot),
        workspace_version=workspace.version, submitted_by_id=actor.id,
        reviewer_note=None,
    )
    session.add(replacement)
    session.flush()
    event = ChangeEvent(
        paper_id=paper.id, workspace_id=workspace.id, entity_type='paper_submission', entity_id=replacement.id,
        action='workspace.submit', before_value={'submission_id': str(original.id), 'content_hash': content_hash},
        after_value={'submission_id': str(replacement.id), 'content_hash': replacement.content_hash,
                     'workspace_version': workspace.version, 'metadata_supplement': True},
        actor_kind=ChangeActorKind.ADMIN, actor_id=actor.id, occurred_at=datetime.now(timezone.utc),
    )
    session.add(event)
    session.flush()
    AuditService().append_event(
        session, actor_id=actor.id, action='submission.metadata_supplement',
        target_type='paper_submission', target_id=replacement.id, paper_id=paper.id,
        changeset_id=None, release_id=None, ip_address='127.0.0.1', request_id=request_id,
        result='success', reason=reason, before_hash=content_hash, after_hash=replacement.content_hash,
        details={'previous_submission_id': str(original.id), 'new_submission_id': str(replacement.id),
                 'fields': sorted(patch), 'reviewer_confirmation': False, 'approved': False},
    )
    return replacement
