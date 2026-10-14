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
        assert review.baseline_snapshot == original
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
