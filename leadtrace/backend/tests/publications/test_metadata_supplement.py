from copy import deepcopy

import pytest
from sqlalchemy import select

from app.audit.service import AuditService, canonical_content_hash
from app.papers.models import Paper
from app.publications.models import AdminDecision, PublishedPaperVersion
from app.publications.service import PublicationService
from app.users.models import User
from app.workspaces.models import ChangeEvent, PaperSection, PaperSectionReview, PaperSubmission, PaperWorkspace
from app.workspaces.snapshot import canonical_snapshot_hash


PATCH = {'pmid': '38126712', 'identifiers_source': 'Matched bibliographic record',
         'abstract': 'A source abstract.', 'abstract_source': 'MED:38126712',
         'abstract_status': 'extracted'}


def amend(f, session, original, **overrides):
    from app.publications.metadata_supplement import supplement_metadata
    args = dict(submission_id=original.id, content_hash=original.content_hash,
                expected_workspace_version=original.workspace_version,
                updates=PATCH, reason='Administrator bibliographic supplement; pending review.',
                actor=session.get(User, f.admin_id), request_id='test-metadata')
    args.update(overrides)
    return supplement_metadata(session, **args)


def test_supplement_preserves_frozen_science_and_records_admin_origin(publication_fixture):
    f = publication_fixture
    first = f.submit()
    original = deepcopy(first.snapshot)
    with f.session_factory.begin() as s:
        second = amend(f, s, first)
        assert second.submission_number == 2
        assert second.submitted_by_id == f.admin_id
        assert second.reviewer_note is None
        assert second.snapshot['paper']['pmid'] == PATCH['pmid']
        assert second.content_hash == canonical_snapshot_hash(second.snapshot)
        assert s.get(PaperSubmission, first.id).snapshot == original
        assert s.get(PaperSubmission, first.id).content_hash == first.content_hash
        for key, value in original.items():
            if key not in {'paper', 'workspace_version', 'sections'}:
                assert second.snapshot[key] == value
        assert all(x['state'] == 'pending' for x in second.snapshot['sections'] if x['section_key'] == 'bibliography')
        assert all(x['note'] is None for x in second.snapshot['sections'] if x['section_key'] == 'bibliography')
        assert not list(s.scalars(select(PublishedPaperVersion)))
        assert len(list(s.scalars(select(AdminDecision)))) == 1
        admin = s.get(User, f.admin_id)
        pending = PublicationService().list_pending_submissions(s, actor=admin)
        assert [x.submission.id for x in pending] == [second.id]
        review = PublicationService().get_submission_review(s, submission_id=second.id, actor=admin)
        # This fixture contains no recorded Reviewer mutations. A supplement
        # must preserve that uncertainty instead of hiding it behind a new baseline.
        assert review.baseline_snapshot is None
        assert review.comparison_warnings
        assert review.reviewer_submission.id == first.id
        assert any(e.action == 'bibliography.update' and e.actor_kind.value == 'admin' for e in review.comparison_events)
        section_event = next(e for e in review.comparison_events if e.action == 'section.update')
        assert section_event.before_value['section_key'] == section_event.after_value['section_key'] == 'bibliography'
        assert AuditService().verify_chain(s).valid
        second_id = second.id
    with f.session_factory.begin() as s:
        assert amend(f, s, first).id == second_id
        assert len(list(s.scalars(select(PaperSubmission)))) == 2


@pytest.mark.parametrize('case', ['stale', 'wrong_hash', 'reviewer', 'title', 'overwrite', 'empty', 'tampered'])
def test_unsafe_supplement_is_atomic(publication_fixture, case):
    f = publication_fixture
    first = f.submit()
    changes = {}
    if case == 'stale': changes['expected_workspace_version'] = first.workspace_version + 1
    if case == 'wrong_hash': changes['content_hash'] = '0' * 64
    if case == 'title': changes['updates'] = {'title': 'Different paper'}
    if case == 'empty': changes['updates'] = {'pmid': ''}
    if case == 'overwrite':
        with f.session_factory.begin() as s:
            s.get(Paper, f.paper_id).pmid = '999'
    if case == 'tampered':
        with f.session_factory.begin() as s:
            s.get(Paper, f.paper_id).title = 'Concurrent title'
    with pytest.raises((ValueError, RuntimeError, PermissionError)):
        with f.session_factory.begin() as s:
            if case == 'reviewer': changes['actor'] = s.get(User, f.reviewer_id)
            amend(f, s, first, **changes)
    with f.session_factory() as s:
        assert len(list(s.scalars(select(PaperSubmission)))) == 1
        assert not list(s.scalars(select(AdminDecision)))
        assert s.get(PaperWorkspace, f.workspace_id).version == first.workspace_version


def test_missing_optional_science_key_is_not_silently_restored(publication_fixture, monkeypatch):
    import app.workspaces.submission as submit_module
    original_builder = submit_module.build_paper_snapshot
    def with_old_highlight(*args):
        value = original_builder(*args)
        value['compound_highlights'] = [{'id': 'previously-present-highlight'}]
        return value
    monkeypatch.setattr(submit_module, 'build_paper_snapshot', with_old_highlight)
    first = publication_fixture.submit()
    # Current builder omits the key after the last highlight disappears.
    with pytest.raises(RuntimeError, match='no longer matches'):
        with publication_fixture.session_factory.begin() as session:
            amend(publication_fixture, session, first)


def test_scoped_note_cleanup_preserves_sources_and_adds_research_profile(publication_fixture):
    f = publication_fixture
    old_note = 'Bibliographic identity matched. 管理员补充，待审核。'
    with f.session_factory.begin() as s:
        s.get(Paper, f.paper_id).abstract_note = old_note
    first = f.submit()
    with f.session_factory.begin() as s:
        revised = amend(f, s, first, updates={
            'abstract_note': 'Bibliographic identity matched.',
            'research_profile': {'targets': [{'name': 'Target A', 'role': 'primary', 'source': 'Page 1'}]},
        }, expected_existing={'abstract_note': old_note})
        assert revised.snapshot['paper']['abstract_note'] == 'Bibliographic identity matched.'
        assert revised.snapshot['paper']['research_profile']['targets'][0]['name'] == 'Target A'
        assert s.get(PaperSubmission, first.id).snapshot['paper']['abstract_note'] == old_note


@pytest.mark.parametrize('case', ['stale_note', 'replace_profile', 'pdb_page'])
def test_scoped_replacement_and_pdb_limits_are_checked(publication_fixture, case):
    f = publication_fixture
    first = f.submit()
    options = {
        'stale_note': {'updates': {'abstract_note': None}, 'expected_existing': {'abstract_note': 'Not the current note'}},
        'replace_profile': {'updates': {'research_profile': {'targets': []}}, 'expected_existing': {'research_profile': {}}},
        'pdb_page': {'updates': {'pdb_references': [{'pdb_id': '1ABC', 'source_page': 2, 'source_context': 'Out of range'}]}},
    }
    with pytest.raises(ValueError):
        with f.session_factory.begin() as s:
            amend(f, s, first, **options[case])


def test_missing_pdb_mentions_can_be_supplemented(publication_fixture):
    f = publication_fixture
    first = f.submit()
    with f.session_factory.begin() as s:
        revised = amend(f, s, first, updates={'pdb_references': [{'pdb_id': '1ABC', 'source_page': 1, 'usage': 'cited_structure'}]})
        assert revised.snapshot['paper']['pdb_references'][0]['pdb_id'] == '1ABC'


def test_legacy_request_retains_its_idempotency_key(publication_fixture):
    f = publication_fixture
    first = f.submit()
    with f.session_factory.begin() as s:
        second = amend(f, s, first)
        legacy_key = 'metadata-supplement:' + canonical_content_hash({
            'original': str(first.id), 'hash': first.content_hash,
            'version': first.workspace_version, 'updates': PATCH,
            'reason': 'Administrator bibliographic supplement; pending review.',
            'actor': str(f.admin_id),
        })
        assert second.idempotency_key == legacy_key


def test_human_bibliography_note_is_preserved(publication_fixture):
    f = publication_fixture
    with f.session_factory.begin() as s:
        section = s.scalar(select(PaperSectionReview).where(PaperSectionReview.workspace_id == f.workspace_id, PaperSectionReview.section_key == PaperSection.BIBLIOGRAPHY))
        section.note = 'Human note: verify the supplied year.'
    first = f.submit()
    with f.session_factory.begin() as s:
        second = amend(f, s, first)
        row = next(x for x in second.snapshot['sections'] if x['section_key'] == 'bibliography')
        assert row['note'] == 'Human note: verify the supplied year.'


@pytest.mark.parametrize('stale', [False, True])
def test_section_note_cleanup_requires_exact_expected_value(publication_fixture, stale):
    f = publication_fixture
    with f.session_factory.begin() as s:
        section = s.scalar(select(PaperSectionReview).where(PaperSectionReview.workspace_id == f.workspace_id, PaperSectionReview.section_key == PaperSection.BIBLIOGRAPHY))
        section.note = 'Previously generated supplement annotation.'
    first = f.submit()
    if stale:
        with pytest.raises(ValueError):
            with f.session_factory.begin() as s:
                amend(f, s, first, expected_section_note='An outdated note')
    else:
        with f.session_factory.begin() as s:
            second = amend(f, s, first, expected_section_note='Previously generated supplement annotation.')
            assert next(x for x in second.snapshot['sections'] if x['section_key'] == 'bibliography')['note'] is None


def test_evidence_supplement_preserves_existing_records_and_immutable_submission(publication_fixture):
    f = publication_fixture
    profile = {'mechanisms': [{'label': 'Inhibitor', 'source': 'Human explanation', 'review_hint': 'Keep me'}]}
    with f.session_factory.begin() as s:
        s.get(Paper, f.paper_id).research_profile = profile
    first = f.submit()
    before = deepcopy(first.snapshot['paper']['research_profile'])
    after = deepcopy(before)
    after['mechanisms'][0]['evidence'] = [{'source_kind': 'main_pdf', 'quoted_text': 'Exact source words.', 'page_number': 1}]
    with f.session_factory.begin() as s:
        second = amend(f, s, first, updates={'research_profile': after}, expected_evidence_baseline={'research_profile': before})
        assert second.snapshot['paper']['research_profile']['mechanisms'][0]['source'] == 'Human explanation'
        assert second.snapshot['paper']['research_profile']['mechanisms'][0]['review_hint'] == 'Keep me'
        assert s.get(PaperSubmission, first.id).snapshot['paper']['research_profile'] == before


@pytest.mark.parametrize('case', ['label', 'removed', 'reordered', 'prior_quote', 'stale', 'page', 'hash'])
def test_evidence_supplement_rejects_nonadditive_or_stale_patch(publication_fixture, case):
    f = publication_fixture
    profile = {'mechanisms': [{'label': 'A', 'source': 'Human', 'evidence': [{'source_kind': 'main_pdf', 'quoted_text': 'Old words', 'page_number': 1}]}, {'label': 'B', 'source': 'Other'}]}
    with f.session_factory.begin() as s:
        s.get(Paper, f.paper_id).research_profile = profile
    first = f.submit()
    before = deepcopy(first.snapshot['paper']['research_profile'])
    after = deepcopy(before)
    after['mechanisms'][0]['evidence'].append({'source_kind': 'main_pdf', 'quoted_text': 'New words', 'page_number': 1})
    if case == 'label': after['mechanisms'][0]['label'] = 'Changed'
    if case == 'removed': after['mechanisms'].pop()
    if case == 'reordered': after['mechanisms'].reverse()
    if case == 'prior_quote': after['mechanisms'][0]['evidence'][0]['quoted_text'] = 'Overwritten'
    if case == 'stale': before['mechanisms'][0]['source'] = 'Stale baseline'
    if case == 'page': after['mechanisms'][0]['evidence'][-1]['page_number'] = 2
    if case == 'hash': after['mechanisms'][0]['evidence'][-1]['source_sha256'] = 'f' * 64
    with pytest.raises((ValueError, RuntimeError)):
        with f.session_factory.begin() as s:
            amend(f, s, first, updates={'research_profile': after}, expected_evidence_baseline={'research_profile': before})
    with f.session_factory() as s:
        assert len(list(s.scalars(select(PaperSubmission)))) == 1
        assert not list(s.scalars(select(AdminDecision)))


@pytest.mark.parametrize('evidence_field', ['research_profile', 'pdb_references'])
def test_combined_missing_metadata_and_evidence_preserves_human_fields(publication_fixture, evidence_field):
    f = publication_fixture
    existing = {
        'research_profile': {'mechanisms': [{'label': 'Inhibitor', 'source': '  Human explanation  '}]},
        'pdb_references': [{'pdb_id': '1abc', 'source_page': 1, 'source_context': '  Human context  '}],
    }[evidence_field]
    with f.session_factory.begin() as s:
        setattr(s.get(Paper, f.paper_id), evidence_field, existing)
    first = f.submit()
    original = deepcopy(first.snapshot)
    after = deepcopy(existing)
    entries = after['mechanisms'] if evidence_field == 'research_profile' else after
    entries[0]['evidence'] = [{'source_kind': 'main_pdf', 'quoted_text': 'Exact source words.', 'page_number': 1}]
    missing = {'pdb_references': [{'pdb_id': '2abc', 'source_page': 1}]} if evidence_field == 'research_profile' else {
        'research_profile': {'mechanisms': [{'label': '  Inhibitor  ', 'source': 'Page 1'}]},
    }
    updates = PATCH | missing | {evidence_field: after, 'pmid': ' 38126712 '}
    baseline = {evidence_field: existing}
    with f.session_factory.begin() as s:
        second = amend(f, s, first, updates=updates, expected_evidence_baseline=baseline)
        assert second.snapshot['paper'][evidence_field] == after
        assert second.snapshot['paper']['pmid'] == '38126712'
        if evidence_field == 'research_profile':
            assert second.snapshot['paper']['pdb_references'][0]['pdb_id'] == '2ABC'
        else:
            assert second.snapshot['paper']['research_profile']['mechanisms'][0]['label'] == 'Inhibitor'
        assert s.get(PaperSubmission, first.id).snapshot == original
        assert s.get(PaperSubmission, first.id).content_hash == first.content_hash
        assert second.content_hash == canonical_snapshot_hash(second.snapshot)
        for key, value in original.items():
            if key not in {'paper', 'workspace_version', 'sections'}:
                assert second.snapshot[key] == value
        for key, value in original['paper'].items():
            if key not in updates:
                assert second.snapshot['paper'][key] == value
        assert not list(s.scalars(select(PublishedPaperVersion)))
        pending = PublicationService().list_pending_submissions(s, actor=s.get(User, f.admin_id))
        assert [x.submission.id for x in pending] == [second.id]
        assert next(x for x in second.snapshot['sections'] if x['section_key'] == 'bibliography')['state'] == 'pending'
        assert AuditService().verify_chain(s).valid
        second_id = second.id
    with f.session_factory.begin() as s:
        assert amend(f, s, first, updates=updates, expected_evidence_baseline=baseline).id == second_id
        assert len(list(s.scalars(select(PaperSubmission)))) == 2


@pytest.mark.parametrize('case', [
    'empty_baseline', 'list_baseline', 'missing_key', 'scalar_field',
    'invalid_profile', 'invalid_group', 'invalid_entry', 'invalid_evidence',
    'overwrite', 'default_value', 'cleanup_note', 'cleanup_section',
    'new_source_page', 'new_source_hash', 'stale_baseline',
])
def test_combined_supplement_rejects_unsafe_updates_atomically(publication_fixture, case):
    f = publication_fixture
    existing = {'mechanisms': [{'label': 'Inhibitor', 'source': 'Human explanation'}]}
    with f.session_factory.begin() as s:
        paper = s.get(Paper, f.paper_id)
        paper.research_profile = existing
        paper.pmid = '12345'
    first = f.submit()
    original = deepcopy(first.snapshot)
    after = deepcopy(existing)
    after['mechanisms'][0]['evidence'] = [{'source_kind': 'main_pdf', 'quoted_text': 'Exact source words.', 'page_number': 1}]
    updates = {'research_profile': after, 'pmcid': 'PMC12345'}
    baseline = {'research_profile': deepcopy(existing)}
    options = {}
    if case == 'empty_baseline': baseline = {}
    if case == 'list_baseline': baseline = ['research_profile']
    if case == 'missing_key': baseline['pdb_references'] = []
    if case == 'scalar_field': baseline['pmcid'] = None
    if case == 'invalid_profile': baseline['research_profile'] = []
    if case == 'invalid_group': baseline['research_profile']['mechanisms'] = None
    if case == 'invalid_entry': baseline['research_profile']['mechanisms'] = [None]
    if case == 'invalid_evidence': baseline['research_profile']['mechanisms'][0]['evidence'] = None
    if case == 'overwrite': updates['pmid'] = '54321'
    if case == 'default_value': updates['pmcid'] = None
    if case == 'cleanup_note':
        updates['abstract_note'] = 'Replacement'
        options['expected_existing'] = {'abstract_note': None}
    if case == 'cleanup_section': options['expected_section_note'] = 'Previous note'
    if case in {'new_source_page', 'new_source_hash'}:
        updates['pdb_references'] = [{'pdb_id': '1ABC', 'evidence': [{
            'source_kind': 'main_pdf', 'quoted_text': 'New entry source.', 'page_number': 1,
        }]}]
        evidence = updates['pdb_references'][0]['evidence'][0]
        if case == 'new_source_page': evidence['page_number'] = 2
        else: evidence['source_sha256'] = 'f' * 64
    if case == 'stale_baseline':
        baseline['research_profile']['mechanisms'][0]['source'] = 'Older explanation'
        after['mechanisms'][0]['source'] = 'Older explanation'
    with pytest.raises(ValueError):
        with f.session_factory.begin() as s:
            amend(f, s, first, updates=updates, expected_evidence_baseline=baseline, **options)
    with f.session_factory() as s:
        assert s.get(PaperSubmission, first.id).snapshot == original
        assert s.get(PaperSubmission, first.id).content_hash == first.content_hash
        assert s.get(Paper, f.paper_id).research_profile == existing
        assert s.get(Paper, f.paper_id).pmid == '12345'
        assert s.get(Paper, f.paper_id).pmcid is None
        assert s.get(PaperWorkspace, f.workspace_id).version == first.workspace_version
        assert len(list(s.scalars(select(PaperSubmission)))) == 1
        assert not list(s.scalars(select(AdminDecision)))


@pytest.mark.parametrize('baseline', [
    [], {'research_profile': []}, {'research_profile': {'mechanisms': None}},
    {'research_profile': {'mechanisms': [None]}},
    {'research_profile': {'mechanisms': [{'label': 'A', 'source': 'Page 1', 'evidence': None}]}},
    {'pdb_references': None},
])
def test_evidence_shape_errors_are_rejected_as_invalid_patches(baseline):
    from app.publications.metadata_supplement import validate_evidence_additions
    with pytest.raises(ValueError):
        validate_evidence_additions(baseline, deepcopy(baseline))


def classification_baseline(f):
    profile = {
        'modalities': [{'label': '直接靶点调节', 'source': 'Legacy classification'}],
        'mechanisms': [{'label': 'Human mechanism', 'source': '  Preserve spaces  '}],
        'targets': [{'name': 'Human target', 'source': 'Page 1'}],
        'diseases': [],
    }
    with f.session_factory.begin() as session:
        session.get(Paper, f.paper_id).research_profile = profile
    return profile


def classification_update(before):
    after = deepcopy(before)
    after['modalities'] = [{
        'label': '小分子抑制剂', 'source': 'Optimized series, page 1',
        'evidence': [{'source_kind': 'main_pdf', 'page_number': 1, 'quoted_text': 'Synthetic inhibitor evidence.'}],
    }, {
        'label': '变构调节', 'source': 'Binding mode, page 1',
        'evidence': [{'source_kind': 'main_pdf', 'page_number': 1, 'quoted_text': 'Synthetic allosteric evidence.'}],
    }]
    return after


def test_classification_replacement_is_scoped_pending_immutable_and_idempotent(publication_fixture):
    f = publication_fixture
    before = classification_baseline(f)
    first = f.submit()
    original = deepcopy(first.snapshot)
    after = classification_update(before)
    with f.session_factory.begin() as session:
        second = amend(f, session, first, updates={'research_profile': after}, expected_classification_baseline=before)
        assert second.snapshot['paper']['research_profile'] == after
        assert session.get(Paper, f.paper_id).research_profile == after
        assert session.get(PaperSubmission, first.id).snapshot == original
        assert session.get(PaperSubmission, first.id).content_hash == first.content_hash
        assert second.content_hash == canonical_snapshot_hash(second.snapshot)
        assert {k: v for k, v in second.snapshot['paper'].items() if k != 'research_profile'} == {
            k: v for k, v in original['paper'].items() if k != 'research_profile'}
        for key in original:
            if key not in {'paper', 'workspace_version', 'sections'}:
                assert second.snapshot[key] == original[key]
        assert next(x for x in second.snapshot['sections'] if x['section_key'] == 'bibliography')['state'] == 'pending'
        assert second.reviewer_note is None
        pending = PublicationService().list_pending_submissions(session, actor=session.get(User, f.admin_id))
        assert [x.submission.id for x in pending] == [second.id]
        assert not list(session.scalars(select(PublishedPaperVersion)))
        assert AuditService().verify_chain(session).valid
        second_id = second.id
    with f.session_factory.begin() as session:
        assert amend(f, session, first, updates={'research_profile': after}, expected_classification_baseline=before).id == second_id
        assert len(list(session.scalars(select(PaperSubmission)))) == 2
    changed_baseline = deepcopy(before)
    changed_baseline['modalities'][0]['source'] = 'Changed request baseline'
    with pytest.raises(RuntimeError, match='Workspace changed'):
        with f.session_factory.begin() as session:
            amend(f, session, first, updates={'research_profile': after}, expected_classification_baseline=changed_baseline)


@pytest.mark.parametrize('case', [
    'stale_baseline', 'stale_version', 'other_group', 'group_removed', 'group_added',
    'extra_field', 'cleanup_note', 'cleanup_empty', 'cleanup_section', 'evidence_mode',
    'no_primary', 'empty', 'unknown', 'duplicate', 'no_source', 'no_evidence',
    'blank_quote', 'unexplained', 'page', 'hash', 'bad_crop', 'external_no_url',
    'invalid_baseline', 'unchanged', 'other_group_source',
])
def test_classification_replacement_rejects_unsafe_changes_atomically(publication_fixture, case):
    f = publication_fixture
    before = classification_baseline(f)
    if case == 'other_group_source':
        before['mechanisms'][0]['evidence'] = [{'source_kind': 'main_pdf', 'quoted_text': 'Existing invalid page', 'page_number': 2}]
        with f.session_factory.begin() as session:
            session.get(Paper, f.paper_id).research_profile = before
    first = f.submit()
    original = deepcopy(first.snapshot)
    after = classification_update(before)
    baseline = deepcopy(before)
    options = {}
    updates = {'research_profile': after}
    if case == 'stale_baseline': baseline['modalities'][0]['source'] = 'Stale'
    if case == 'stale_version': options['expected_workspace_version'] = first.workspace_version + 1
    if case == 'other_group': after['mechanisms'][0]['source'] = 'Changed'
    if case == 'group_removed': after.pop('diseases')
    if case == 'group_added': after['optimization_goals'] = []
    if case == 'extra_field': updates['pmid'] = '12345'
    if case == 'cleanup_note': options['expected_existing'] = {'abstract_note': None}
    if case == 'cleanup_empty': options['expected_existing'] = {}
    if case == 'cleanup_section': options['expected_section_note'] = ''
    if case == 'evidence_mode': options['expected_evidence_baseline'] = {'research_profile': before}
    if case == 'no_primary': after['modalities'] = after['modalities'][1:]
    if case == 'empty': after['modalities'] = []
    if case == 'unknown': after['modalities'][0]['label'] = '直接靶点调节'
    if case == 'duplicate': after['modalities'].append(deepcopy(after['modalities'][0]))
    if case == 'no_source': after['modalities'][0]['source'] = '  '
    if case == 'no_evidence': after['modalities'][0]['evidence'] = []
    if case == 'blank_quote': after['modalities'][0]['evidence'][0]['quoted_text'] = '  '
    if case == 'unexplained': after['modalities'][0]['label'] = '其他'
    if case == 'page': after['modalities'][0]['evidence'][0]['page_number'] = 2
    if case == 'hash': after['modalities'][0]['evidence'][0]['source_sha256'] = 'f' * 64
    if case == 'bad_crop': after['modalities'][0]['evidence'][0]['bbox'] = {'x': 0.9, 'y': 0, 'width': 0.2, 'height': 0.1}
    if case == 'external_no_url': after['modalities'][0]['evidence'][0]['source_kind'] = 'external'
    if case == 'invalid_baseline': baseline = []
    if case == 'unchanged': after['modalities'] = deepcopy(before['modalities'])
    with pytest.raises((ValueError, RuntimeError)):
        with f.session_factory.begin() as session:
            amend(f, session, first, updates=updates, expected_classification_baseline=baseline, **options)
    with f.session_factory() as session:
        assert session.get(PaperSubmission, first.id).snapshot == original
        assert session.get(Paper, f.paper_id).research_profile == before
        assert session.get(PaperWorkspace, f.workspace_id).version == first.workspace_version
        assert len(list(session.scalars(select(PaperSubmission)))) == 1
        assert not list(session.scalars(select(AdminDecision)))


def test_classification_accepts_each_fixed_type_with_its_own_evidence():
    from app.papers.metadata import MOLECULE_PRIMARY_LABELS, MOLECULE_FEATURE_LABELS
    from app.publications.metadata_supplement import validate_classification_replacement
    template = classification_update({})['modalities'][0]
    for label in MOLECULE_PRIMARY_LABELS:
        term = deepcopy(template) | {'label': label}
        if label in ('其他', '待明确'):
            term['review_hint'] = 'Peptide series or unresolved molecular classification explained.'
        validate_classification_replacement({}, {'modalities': [term]})
    for label in MOLECULE_FEATURE_LABELS:
        feature = deepcopy(template) | {'label': label}
        validate_classification_replacement({}, {'modalities': [template, feature]})


@pytest.mark.parametrize('modalities', [None, [None], [{'label': []}], [
    {'label': '其他', 'source': 'Page 1', 'evidence': [{}], 'review_hint': 123},
]])
def test_classification_shape_errors_are_invalid_patches(modalities):
    from app.publications.metadata_supplement import validate_classification_replacement
    with pytest.raises(ValueError):
        validate_classification_replacement({}, {'modalities': modalities})


def test_classification_preserves_json_scalar_types_in_other_groups():
    from app.publications.metadata_supplement import validate_classification_replacement
    before = {'mechanisms': [{'label': 'Human', 'source': 'Page 1', 'evidence': [
        {'source_kind': 'main_pdf', 'page_number': 1, 'quoted_text': 'Human evidence'},
    ]}]}
    after = classification_update(before)
    after['mechanisms'][0]['evidence'][0]['page_number'] = True
    with pytest.raises(ValueError, match='preserve all other profile groups'):
        validate_classification_replacement(before, after)
