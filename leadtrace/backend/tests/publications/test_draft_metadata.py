from copy import deepcopy
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.audit.models import AuditEvent
from app.audit.service import AuditService, canonical_content_hash
from app.papers.models import Paper
from app.publications.models import AdminDecision, AdminDecisionAction, PublishedPaperVersion
from app.publications.service import PublicationService
from app.users.models import User
from app.workspaces.models import (
    ChangeActorKind, ChangeEvent, PaperSectionReview, PaperSectionState,
    PaperSubmission, PaperWorkspace, ReviewTask, ReviewTaskState, WorkspaceState,
)
from app.workspaces.snapshot import build_paper_snapshot, canonical_snapshot_hash
from tests.publications.test_reviewer_rounds import round_detail, return_submission
from tests.publications.test_supplement_comparison import reviewer_submission, supplement


def provenance(**overrides):
    return dict(run_key='metadata-batch-fixture', stage='repair', adapter='codex',
        model='gpt-6-astra', reasoning_effort='high', verification='requested_only',
        source_sha256='a' * 64, candidate_file_sha256='b' * 64,
        evidence_sha256='c' * 64, guide_bundle_sha256='d' * 64,
        completed_at='2026-10-15T01:00:00Z', outcome='completed', **overrides)


def arguments(s, f, updates=None, **overrides):
    snapshot = build_paper_snapshot(s, f.workspace_id)
    return dict(workspace_id=f.workspace_id,
        expected_workspace_version=s.get(PaperWorkspace, f.workspace_id).version,
        expected_snapshot_hash=canonical_snapshot_hash(snapshot),
        updates=updates or {'pmid': '12345678'}, reason='Authorized metadata completion',
        actor=s.get(User, f.admin_id), request_id='draft-metadata-test',
        provenance=provenance(), **overrides)


def apply(s, **kwargs):
    from app.publications.draft_metadata import supplement_draft_metadata
    return supplement_draft_metadata(s, **kwargs)


def human_bibliography(f, patch):
    with f.session_factory() as s:
        version = s.get(PaperWorkspace, f.workspace_id).version
    csrf = f.login('publication.reviewer')
    response = f.client.patch(f'/api/v2/workspaces/{f.workspace_id}/bibliography',
        headers={'X-CSRF-Token': csrf}, json={'expected_workspace_version': version, **patch})
    assert response.status_code == 200, response.text


def test_draft_supplement_preserves_assignment_science_notes_and_replays(publication_fixture):
    f = publication_fixture
    with f.session_factory.begin() as s:
        section = s.scalar(select(PaperSectionReview).where(PaperSectionReview.workspace_id == f.workspace_id,
            PaperSectionReview.section_key == 'bibliography'))
        section.state, section.note = PaperSectionState.COMPLETED, 'Real Reviewer note'
        s.flush()
        before = build_paper_snapshot(s, f.workspace_id)
        task = s.get(ReviewTask, f.task_id)
        task_before = (task.status, task.assigned_reviewer_id, task.version)
        args = arguments(s, f)
        receipt = apply(s, **args)
        assert apply(s, **args) == receipt
        assert receipt['workspace_version'] == 2
        assert receipt['fields'] == ['pmid']
        after = build_paper_snapshot(s, f.workspace_id)
        assert after['paper']['pmid'] == '12345678'
        assert after['compounds'] == before['compounds']
        assert [x for x in after['sections'] if x['section_key'] != 'bibliography'] == [x for x in before['sections'] if x['section_key'] != 'bibliography']
        assert section.state == PaperSectionState.PENDING
        assert section.note == 'Real Reviewer note'
        assert (task.status, task.assigned_reviewer_id, task.version) == task_before
        assert s.scalar(select(func.count()).select_from(PaperSubmission)) == 0
        assert s.scalar(select(func.count()).select_from(AdminDecision)) == 0
        event = s.scalar(select(ChangeEvent).where(ChangeEvent.action == 'bibliography.ai_supplement'))
        assert event.actor_kind == ChangeActorKind.AI
        assert event.before_value == {'pmid': None}
        assert event.after_value == {'pmid': '12345678'}
        audit = s.scalar(select(AuditEvent).where(AuditEvent.action == 'paper.article_metadata_supplement'))
        assert audit.actor_id == f.admin_id
        assert audit.details['change_event_id'] == str(event.id)
        assert audit.details['event_payload_sha256'] == canonical_content_hash({'before': event.before_value, 'after': event.after_value})
        assert audit.details['source_sha256'] == 'a' * 64
        assert AuditService().verify_chain(s).valid
        with pytest.raises(ValueError, match='[Rr]equest|[Ii]dempotency'):
            apply(s, **{**args, 'updates': {'pmid': '87654321'}})


def test_partial_profile_adds_only_missing_groups_and_preserves_legacy_json(publication_fixture):
    f = publication_fixture
    old = {'mechanisms': [{'label': 'Human mechanism', 'source': 'Human note'}],
        'molecular_forms': [{'label': 'Legacy form', 'source': 'Historical'}]}
    disease = [{'label': 'Source disease', 'source': 'Page 1', 'evidence': [
        {'source_kind': 'main_pdf', 'page_number': 1, 'quoted_text': 'Fixture evidence', 'source_sha256': 'a' * 64}]}]
    with f.session_factory.begin() as s:
        paper = s.get(Paper, f.paper_id)
        paper.research_profile = deepcopy(old)
        s.flush()
        apply(s, **arguments(s, f, {'research_profile': {'diseases': disease}}))
        assert paper.research_profile == {**old, 'diseases': disease}
        with pytest.raises(ValueError, match='populated|preserve|missing|existing'):
            apply(s, **{**arguments(s, f, {'research_profile': {'mechanisms': [{'label': 'Replacement', 'source': 'AI'}]}}), 'request_id': 'overwrite'})


@pytest.mark.parametrize('mutation', ['version', 'hash', 'source', 'disabled', 'submitted', 'archived', 'overwrite', 'noop', 'molecular_forms', 'bad_modality', 'bad_page', 'bad_bbox', 'failed_provenance'])
def test_operator_guards(publication_fixture, mutation):
    f = publication_fixture
    with f.session_factory.begin() as s:
        args = arguments(s, f)
        if mutation == 'version': args['expected_workspace_version'] += 1
        if mutation == 'hash': args['expected_snapshot_hash'] = '0' * 64
        if mutation == 'source': args['provenance']['source_sha256'] = '0' * 64
        if mutation == 'disabled': args['actor'].is_enabled = False
        if mutation == 'submitted':
            s.get(PaperWorkspace, f.workspace_id).state = WorkspaceState.SUBMITTED
            s.get(ReviewTask, f.task_id).status = ReviewTaskState.SUBMITTED
        if mutation == 'archived': s.get(PaperWorkspace, f.workspace_id).state = WorkspaceState.ARCHIVED
        if mutation == 'overwrite':
            s.get(Paper, f.paper_id).pmid = '87654321'
            s.flush()
            args['expected_snapshot_hash'] = canonical_snapshot_hash(build_paper_snapshot(s, f.workspace_id))
        if mutation == 'noop': args['updates'] = {'abstract': None}
        if mutation == 'molecular_forms': args['updates'] = {'research_profile': {'molecular_forms': [{'label': 'New form', 'source': 'AI'}]}}
        if mutation == 'bad_modality': args['updates'] = {'research_profile': {'modalities': [{'label': 'Novel type', 'source': 'AI'}]}}
        if mutation in {'bad_page', 'bad_bbox'}:
            evidence = {'source_kind': 'main_pdf', 'page_number': 2 if mutation == 'bad_page' else 1,
                'quoted_text': 'Fixture evidence', 'source_sha256': 'a' * 64}
            if mutation == 'bad_bbox': evidence['bbox'] = {'x': .9, 'y': .1, 'width': .5, 'height': .1}
            args['updates'] = {'research_profile': {'diseases': [{'label': 'Disease', 'source': 'Page 1', 'evidence': [evidence]}]}}
        if mutation == 'failed_provenance': args['provenance']['outcome'] = 'failed'
        s.flush()
        with pytest.raises((ValueError, RuntimeError, PermissionError)):
            apply(s, **args)
        assert s.scalar(select(func.count()).select_from(ChangeEvent)) == 0


def test_published_revision_retains_published_snapshot_and_real_confirmations(publication_fixture):
    f = publication_fixture
    first = reviewer_submission(f)
    with f.session_factory.begin() as s:
        result = PublicationService().decide(s, submission_id=first.id, content_hash=first.content_hash,
            action=AdminDecisionAction.APPROVE, reason='Approved scientific record',
            idempotency_key='published-first', actor=s.get(User, f.admin_id))
        published_id = result.published_version.id
        old_snapshot = deepcopy(result.published_version.snapshot)
        previous_version = s.get(PaperWorkspace, f.workspace_id).version
        args = arguments(s, f)
        with pytest.raises((RuntimeError, ValueError)):
            apply(s, **args)
        receipt = apply(s, **{**args, 'allow_published_revision': True, 'expected_published_version_id': published_id})
        assert receipt['workspace_version'] > previous_version
        assert s.get(PaperWorkspace, f.workspace_id).state == WorkspaceState.EDITING
        assert s.get(ReviewTask, f.task_id).status == ReviewTaskState.ASSIGNED
        assert s.get(Paper, f.paper_id).current_published_version_id == published_id
        assert s.get(PublishedPaperVersion, published_id).snapshot == old_snapshot
        assert s.get(PaperSubmission, first.id).snapshot == first.snapshot
        assert s.scalar(select(func.count()).select_from(AdminDecision)) == 1
    assert not round_detail(f, first)['review_rounds']['can_decide']
    second = f.submit(key='published-revision-round2')
    detail = round_detail(f, second)
    assert len(detail['review_rounds']['versions']) == 2
    assert detail['review_rounds']['can_decide']
    assert detail['comparison']['baseline_snapshot']['paper']['pmid'] == '12345678'


@pytest.mark.parametrize('later_round', [False, True])
def test_audited_ai_fields_hidden_without_hiding_human_profile_edits(publication_fixture, later_round):
    f = publication_fixture
    if later_round:
        first = reviewer_submission(f)
        return_submission(f, first)
    human_profile = {'mechanisms': [{'label': 'Human mechanism', 'source': 'Human original'}]}
    human_bibliography(f, {'title': 'Actual human title', 'research_profile': human_profile})
    with f.session_factory.begin() as s:
        apply(s, **arguments(s, f, {'pmid': '12345678', 'research_profile': {
            'diseases': [{'label': 'AI disease', 'source': 'Page 1'}]}}))
    submitted = f.submit(key='human-round-after-ai')
    data = round_detail(f, submitted)
    base = data['comparison']['baseline_snapshot']['paper']
    assert base['pmid'] == data['submission']['snapshot']['paper']['pmid']
    assert base['title'] != data['submission']['snapshot']['paper']['title']
    assert base['research_profile']['diseases'] == data['submission']['snapshot']['paper']['research_profile']['diseases']
    assert not base['research_profile'].get('mechanisms')
    assert len(data['review_rounds']['supplements']) == 1
    assert data['review_rounds']['supplements'][0]['phase'] == 'before_submission'
    assert not data['review_rounds']['warnings']


def test_human_correction_after_ai_fill_stays_visible(publication_fixture):
    f = publication_fixture
    human_bibliography(f, {'title': 'First human edit'})
    with f.session_factory.begin() as s:
        apply(s, **arguments(s, f))
    human_bibliography(f, {'pmid': '87654321'})
    data = round_detail(f, f.submit())
    assert data['comparison']['baseline_snapshot']['paper']['pmid'] == '12345678'
    assert data['submission']['snapshot']['paper']['pmid'] == '87654321'


def test_unbound_ai_event_warns_and_remains_in_main_diff(publication_fixture):
    f = publication_fixture
    human_bibliography(f, {'title': 'Human changed title'})
    with f.session_factory.begin() as s:
        s.get(Paper, f.paper_id).pmid = '12345678'
        s.add(ChangeEvent(paper_id=f.paper_id, workspace_id=f.workspace_id, entity_type='paper', entity_id=f.paper_id,
            action='bibliography.ai_supplement', before_value={'pmid': None}, after_value={'pmid': '12345678'},
            actor_kind=ChangeActorKind.AI, actor_id=None, occurred_at=datetime.now(timezone.utc)))
    data = round_detail(f, f.submit())
    assert not data['comparison']['baseline_snapshot']['paper'].get('pmid')
    assert data['submission']['snapshot']['paper']['pmid'] == '12345678'
    assert data['review_rounds']['warnings']
    assert not data['review_rounds']['supplements']


def test_unbound_ai_event_before_first_human_edit_cannot_disappear(publication_fixture):
    f = publication_fixture
    with f.session_factory.begin() as s:
        s.get(Paper, f.paper_id).pmid = '12345678'
        s.add(ChangeEvent(paper_id=f.paper_id, workspace_id=f.workspace_id, entity_type='paper', entity_id=f.paper_id,
            action='bibliography.ai_supplement', before_value={'pmid': None}, after_value={'pmid': '12345678'},
            actor_kind=ChangeActorKind.AI, actor_id=None, occurred_at=datetime.now(timezone.utc)))
    human_bibliography(f, {'title': 'Human title after unbound supplement'})
    data = round_detail(f, f.submit())
    assert data['comparison']['kind'] == 'unavailable'
    assert data['comparison']['baseline_snapshot'] is None
    assert data['submission']['snapshot']['paper']['pmid'] == '12345678'
    assert data['review_rounds']['warnings']


def test_chained_evidence_fills_before_first_human_edit_are_one_complete_context(publication_fixture):
    f = publication_fixture
    evidence = {'source_kind': 'main_pdf', 'page_number': 1, 'quoted_text': 'First fixture evidence', 'source_sha256': 'a' * 64}
    reference = {'pdb_id': '1ABC', 'source_context': 'Original context', 'evidence': [evidence]}
    with f.session_factory.begin() as s:
        apply(s, **arguments(s, f, {'pdb_references': [reference]}))
        appended = reference | {'evidence': [evidence, evidence | {'quoted_text': 'Second fixture evidence'}]}
        apply(s, **{**arguments(s, f, {'pdb_references': [appended]}), 'request_id': 'append-second-evidence'})
    human_bibliography(f, {'title': 'Human title after valid AI evidence'})
    data = round_detail(f, f.submit())
    assert data['comparison']['baseline_snapshot']['paper']['pdb_references'] == data['submission']['snapshot']['paper']['pdb_references']
    assert len(data['review_rounds']['supplements']) == 1
    assert data['review_rounds']['supplements'][0]['count'] == 2
    assert not data['review_rounds']['warnings']


def test_old_technical_and_new_draft_supplements_share_one_phase(publication_fixture):
    f = publication_fixture
    first = reviewer_submission(f)
    technical = supplement(f, first, {'pmid': '12345678'})
    return_submission(f, technical)
    with f.session_factory.begin() as s:
        apply(s, **arguments(s, f, {'pmcid': 'PMC12345678'}))
    second = f.submit(key='round2-with-two-supplement-modes')
    data = round_detail(f, second)
    before = [x for x in data['review_rounds']['supplements'] if x['phase'] == 'before_submission']
    assert len(before) == 1
    assert before[0]['count'] == 2
    assert before[0]['snapshot']['paper']['pmcid'] == 'PMC12345678'
    assert data['comparison']['baseline_snapshot']['paper']['pmid'] == '12345678'
    assert data['comparison']['baseline_snapshot']['paper']['pmcid'] == 'PMC12345678'


def test_draft_additions_visible_after_return_before_reviewer_resubmits(publication_fixture):
    f = publication_fixture
    first = reviewer_submission(f)
    return_submission(f, first)
    with f.session_factory.begin() as s:
        apply(s, **arguments(s, f))
    data = round_detail(f, first)
    assert data['submission']['snapshot'] == first.snapshot
    assert not data['review_rounds']['can_decide']
    assert len(data['review_rounds']['versions']) == 1
    assert data['review_rounds']['supplements'][0]['phase'] == 'after_submission'
    assert data['review_rounds']['supplements'][0]['snapshot']['paper']['pmid'] == '12345678'


@pytest.mark.parametrize('tamper', ['source', 'payload', 'request', 'actor', 'nonadditive'])
def test_corrupt_audit_binding_cannot_hide_metadata(publication_fixture, tamper):
    from app.publications.reviewer_rounds import get_reviewer_round_review
    f = publication_fixture
    first = reviewer_submission(f)
    return_submission(f, first)
    with f.session_factory.begin() as s:
        apply(s, **arguments(s, f))
    second = f.submit(key='round2-test-audit-binding')
    with f.session_factory() as s:
        audit = s.scalar(select(AuditEvent).where(AuditEvent.action == 'paper.article_metadata_supplement'))
        if tamper == 'source': audit.details = audit.details | {'source_sha256': '0' * 64}
        if tamper == 'payload': audit.details = audit.details | {'event_payload_sha256': '0' * 64}
        if tamper == 'request': audit.details = audit.details | {'request_payload_sha256': '0' * 64}
        if tamper == 'actor': audit.actor_id = f.reviewer_id
        if tamper == 'nonadditive':
            event = s.scalar(select(ChangeEvent).where(ChangeEvent.action == 'bibliography.ai_supplement'))
            event.before_value = {'pmid': '87654321'}
            audit.details = audit.details | {'event_payload_sha256': canonical_content_hash({'before': event.before_value, 'after': event.after_value})}
        # Fault injection stays in memory; real immutable rows are never edited.
        with s.no_autoflush:
            review, rounds = get_reviewer_round_review(s, submission_id=second.id, actor=s.get(User, f.admin_id))
        assert not review.baseline_snapshot['paper'].get('pmid')
        assert rounds.warnings
        assert not rounds.supplements


def test_pdb_evidence_only_appends_without_normalizing_existing_fields(publication_fixture):
    f = publication_fixture
    raw = [{'pdb_id': '1ABC', 'source_context': 'Existing human fields'}]
    evidence = {'source_kind': 'main_pdf', 'page_number': 1, 'quoted_text': 'Fixture evidence', 'source_sha256': 'a' * 64}
    with f.session_factory.begin() as s:
        paper = s.get(Paper, f.paper_id)
        paper.pdb_references = deepcopy(raw)
        s.flush()
        apply(s, **arguments(s, f, {'pdb_references': [raw[0] | {'evidence': [evidence]}]}))
        assert paper.pdb_references == [raw[0] | {'evidence': [evidence]}]
        with pytest.raises(ValueError):
            apply(s, **{**arguments(s, f, {'pdb_references': []}), 'request_id': 'remove-pdb'})


@pytest.mark.parametrize('active', ['ai', 'delivering', 'legacy_queued', 'legacy_running', 'crop'])
def test_active_jobs_block_draft_delivery(publication_fixture, active):
    from app.ai_prefill.models import AiExtractionRun
    from app.ai_tasks.models import AiTask
    from app.jobs.models import CropJob
    f = publication_fixture
    with f.session_factory.begin() as s:
        if active in {'ai', 'delivering'}:
            job = AiTask(paper_id=f.paper_id, workspace_id=f.workspace_id, requested_by_id=f.admin_id,
                idempotency_key='job-fixture', request_digest='a' * 64, action='review', preset_id='fixture',
                adapter='codex', model='gpt-6-astra', reasoning_effort='high', workspace_version=1,
                task_version=1, source_sha256='a' * 64, timeout_seconds=1800,
                state='delivering' if active == 'delivering' else 'running')
        elif active.startswith('legacy_'):
            job = AiExtractionRun(paper_id=f.paper_id, workspace_id=f.workspace_id,
                requested_by_id=f.admin_id, starting_workspace_version=1,
                engine='fixture', engine_version='1', status=active.removeprefix('legacy_'))
        else:
            job = CropJob(source_asset_id=f.source_asset_id, input_hash='b' * 64,
                source_pdf_sha256='a' * 64, page_number=1, x0=.1, y0=.1, x1=.2, y1=.2,
                renderer_version='fixture', dpi=300)
        s.add(job)
        s.flush()
        before = build_paper_snapshot(s, f.workspace_id)
        with pytest.raises(RuntimeError, match='active'):
            apply(s, **arguments(s, f))
        assert build_paper_snapshot(s, f.workspace_id) == before
        assert s.scalar(select(func.count()).select_from(ChangeEvent)) == 0


def test_finished_legacy_extraction_does_not_block_additive_delivery(publication_fixture):
    from app.ai_prefill.models import AiExtractionRun
    f = publication_fixture
    with f.session_factory.begin() as s:
        s.add(AiExtractionRun(paper_id=f.paper_id, workspace_id=f.workspace_id,
            requested_by_id=f.admin_id, starting_workspace_version=1,
            engine='fixture', engine_version='1', status='succeeded'))
        s.flush()
        assert apply(s, **arguments(s, f))['workspace_version'] == 2


def test_prior_compound_view_receipt_remains_valid(publication_fixture):
    from app.compounds.models import Compound
    from app.workspaces.models import WorkspaceViewReceipt
    from app.workspaces.review_progress import get_progress, review_items
    f = publication_fixture
    with f.session_factory.begin() as s:
        compound = Compound(paper_id=f.paper_id, workspace_id=f.workspace_id,
            compound_label='1', sort_order=1, created_by_kind=ChangeActorKind.AI)
        s.add(compound)
        s.flush()
        item = review_items(build_paper_snapshot(s, f.workspace_id))[0]
        receipt = WorkspaceViewReceipt(workspace_id=f.workspace_id, reviewer_id=f.reviewer_id,
            kind='compound', entity_id=compound.id, signature=item['signature'], viewed_at=datetime.now(timezone.utc))
        s.add(receipt)
        s.flush()
        before = get_progress(s, f.workspace_id, f.reviewer_id)['items']
        apply(s, **arguments(s, f))
        assert get_progress(s, f.workspace_id, f.reviewer_id)['items'] == before
        assert before[0]['viewed']


@pytest.mark.parametrize('invalid', ['published_id', 'science', 'another_generation'])
def test_published_revision_guards(publication_fixture, invalid):
    from uuid import uuid4
    f = publication_fixture
    first = reviewer_submission(f)
    with f.session_factory.begin() as s:
        result = PublicationService().decide(s, submission_id=first.id, content_hash=first.content_hash,
            action=AdminDecisionAction.APPROVE, reason='Approved', idempotency_key='approve', actor=s.get(User, f.admin_id))
        if invalid == 'science': s.get(Paper, f.paper_id).title = 'Changed since publication'
        if invalid == 'another_generation':
            s.add(ReviewTask(paper_id=f.paper_id, assigned_reviewer_id=f.reviewer_id,
                created_by_id=f.admin_id, status=ReviewTaskState.ASSIGNED, version=1))
        s.flush()
        args = arguments(s, f, allow_published_revision=True,
            expected_published_version_id=uuid4() if invalid == 'published_id' else result.published_version.id)
        with pytest.raises(RuntimeError):
            apply(s, **args)
        assert s.get(PaperWorkspace, f.workspace_id).state == WorkspaceState.APPROVED


def test_published_revision_must_reopen_the_published_submission_workspace(publication_fixture):
    f = publication_fixture
    first = reviewer_submission(f)
    with f.session_factory.begin() as s:
        result = PublicationService().decide(s, submission_id=first.id, content_hash=first.content_hash,
            action=AdminDecisionAction.APPROVE, reason='Approved', idempotency_key='approve', actor=s.get(User, f.admin_id))
        other_task = ReviewTask(paper_id=f.paper_id, assigned_reviewer_id=f.reviewer_id,
            created_by_id=f.admin_id, status=ReviewTaskState.APPROVED, version=1)
        s.add(other_task)
        s.flush()
        other = PaperWorkspace(paper_id=f.paper_id, review_task_id=other_task.id,
            state=WorkspaceState.APPROVED, version=1)
        s.add(other)
        s.flush()
        for row in first.snapshot['sections']:
            s.add(PaperSectionReview(workspace_id=other.id, paper_id=f.paper_id,
                section_key=row['section_key'], state=row['state'], note=row['note']))
        s.flush()
        args = arguments(s, f, allow_published_revision=True, expected_published_version_id=result.published_version.id)
        args.update(workspace_id=other.id, expected_workspace_version=1,
            expected_snapshot_hash=canonical_snapshot_hash(build_paper_snapshot(s, other.id)))
        with pytest.raises(RuntimeError, match='published.*workspace|workspace.*published'):
            apply(s, **args)


def test_cached_source_identity_cannot_bypass_live_source_check(publication_fixture):
    from app.assets.models import Asset
    from app.catalog.models import PaperSource
    f = publication_fixture
    with f.session_factory.begin() as s:
        args = arguments(s, f)
        source = s.get(PaperSource, s.get(Paper, f.paper_id).source_id)
        asset = s.get(Asset, source.asset_id)
        with f.session_factory.begin() as other:
            other.get(PaperSource, source.id).sha256 = 'e' * 64
            other.get(Asset, asset.id).sha256 = 'e' * 64
        with pytest.raises((RuntimeError, ValueError), match='source|snapshot'):
            apply(s, **args)
