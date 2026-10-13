from __future__ import annotations

from sqlalchemy import func, select

from app.papers.models import Paper
from app.publications.models import (
    AdminDecision,
    AdminDecisionAction,
    PublishedPaperVersion,
)
from app.publications.service import PublicationService
from app.users.models import User
from app.workspaces.models import ChangeActorKind, ChangeEvent


def test_admin_submission_queue_detail_and_approval_api(publication_fixture):
    fixture = publication_fixture
    submission = fixture.submit()
    url = f"/api/v2/admin/submissions/{submission.id}/decisions"

    reviewer_csrf = fixture.login("publication.reviewer")
    reviewer_list = fixture.client.get("/api/v2/admin/submissions")
    reviewer_decision = fixture.client.post(
        url,
        headers={"X-CSRF-Token": reviewer_csrf},
        json={
            "content_hash": submission.content_hash,
            "action": "approve",
            "reason": "Reviewer must not approve.",
            "idempotency_key": "reviewer-approve",
        },
    )
    assert reviewer_list.status_code == 403
    assert reviewer_decision.status_code == 403

    with fixture.session_factory.begin() as session:
        paper = session.get(Paper, fixture.paper_id)
        assert paper is not None
        paper.title = "Mutable title after submission"

    admin_csrf = fixture.login("publication.admin")
    listing = fixture.client.get("/api/v2/admin/submissions")
    detail = fixture.client.get(f"/api/v2/admin/submissions/{submission.id}")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["submission_id"] == str(submission.id)
    assert listing.json()["items"][0]["title"] == "Frozen submitted title"
    assert detail.status_code == 200
    assert set(detail.json()) == {"submission", "bibliography", "change_events", "reviewer_diff"}
    assert set(detail.json()["bibliography"]) == {
        "paper_id", "paper_key", "title", "journal", "publication_year", "volume", "issue", "doi"
    }
    assert detail.json()["submission"]["content_hash"] == submission.content_hash
    assert detail.json()["submission"]["snapshot"] == submission.snapshot
    assert any(
        event["action"] == "workspace.submit"
        for event in detail.json()["change_events"]
    )
    assert "/private/" not in detail.text

    missing_csrf = fixture.client.post(
        url,
        json={
            "content_hash": submission.content_hash,
            "action": "approve",
            "reason": "No CSRF.",
            "idempotency_key": "no-csrf",
        },
    )
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["code"] == "CSRF_VALIDATION_FAILED"

    wrong_hash = fixture.client.post(
        url,
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "content_hash": "0" * 64,
            "action": "approve",
            "reason": "Wrong hash.",
            "idempotency_key": "wrong-hash",
        },
    )
    assert wrong_hash.status_code == 409
    assert wrong_hash.json()["code"] == "SUBMISSION_HASH_MISMATCH"

    approved = fixture.client.post(
        url,
        headers={"X-CSRF-Token": admin_csrf, "Idempotency-Key": "header-key"},
        json={
            "content_hash": submission.content_hash,
            "action": "approve",
            "reason": "Scientific review complete.",
            "idempotency_key": "body-key",
        },
    )
    replay = fixture.client.post(
        url,
        headers={"X-CSRF-Token": admin_csrf, "Idempotency-Key": "header-key"},
        json={
            "content_hash": submission.content_hash,
            "action": "approve",
            "reason": "Scientific review complete.",
        },
    )
    assert approved.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == approved.json()
    assert approved.json()["decision"]["idempotency_key"] == "header-key"
    assert approved.json()["published_version"]["content_hash"] == submission.content_hash

    after = fixture.client.get("/api/v2/admin/submissions")
    assert after.status_code == 200
    assert after.json()["total"] == 0
    with fixture.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(AdminDecision)) == 1
        assert session.scalar(select(func.count()).select_from(PublishedPaperVersion)) == 1


def test_admin_decision_api_requires_nonblank_reason(publication_fixture):
    fixture = publication_fixture
    submission = fixture.submit()
    csrf = fixture.login("publication.admin")
    response = fixture.client.post(
        f"/api/v2/admin/submissions/{submission.id}/decisions",
        headers={"X-CSRF-Token": csrf},
        json={
            "content_hash": submission.content_hash,
            "action": "request_changes",
            "reason": "   ",
            "idempotency_key": "blank-reason",
        },
    )
    assert response.status_code == 422
    with fixture.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(AdminDecision)) == 0


def test_admin_submission_history_is_scoped_to_each_frozen_submission(
    publication_fixture,
):
    fixture = publication_fixture
    first = fixture.submit()
    with fixture.session_factory.begin() as session:
        admin = session.get(User, fixture.admin_id)
        assert admin is not None
        PublicationService().decide(
            session,
            submission_id=first.id,
            content_hash=first.content_hash,
            action=AdminDecisionAction.REQUEST_CHANGES,
            reason="Revise the bibliography.",
            idempotency_key="history-request-changes",
            actor=admin,
        )
        session.add(
            ChangeEvent(
                paper_id=fixture.paper_id,
                workspace_id=fixture.workspace_id,
                entity_type="paper",
                entity_id=fixture.paper_id,
                action="bibliography.update",
                before_value={"title": "Frozen submitted title"},
                after_value={"title": "Second submission title"},
                actor_kind=ChangeActorKind.REVIEWER,
                actor_id=fixture.reviewer_id,
                ai_run_id=None,
            )
        )
    second = fixture.submit(key="submission-2")

    fixture.login("publication.admin")
    first_detail = fixture.client.get(f"/api/v2/admin/submissions/{first.id}")
    second_detail = fixture.client.get(f"/api/v2/admin/submissions/{second.id}")
    assert first_detail.status_code == 200
    assert second_detail.status_code == 200
    assert "bibliography.update" not in {
        event["action"] for event in first_detail.json()["change_events"]
    }
    assert "bibliography.update" not in {
        event["action"] for event in first_detail.json()["reviewer_diff"]
    }
    assert [
        event["action"] for event in second_detail.json()["reviewer_diff"]
    ] == ["bibliography.update"]


def test_initial_comparison_reconstructs_reviewer_start_and_freezes_later_mutations(publication_fixture):
    fixture = publication_fixture
    csrf = fixture.login('publication.reviewer')
    update = fixture.client.patch(
        f'/api/v2/workspaces/{fixture.workspace_id}/bibliography',
        headers={'X-CSRF-Token':csrf},
        json={'expected_workspace_version':1, 'title':'Reviewer corrected title'},
    )
    assert update.status_code == 200
    with fixture.session_factory.begin() as session:
        paper = session.get(Paper, fixture.paper_id)
        paper.title = 'Admin corrected title'
        session.add(ChangeEvent(paper_id=fixture.paper_id, workspace_id=fixture.workspace_id,
            entity_type='paper', entity_id=fixture.paper_id, action='bibliography.update',
            before_value={'title':'Reviewer corrected title'}, after_value={'title':'Admin corrected title'},
            actor_kind=ChangeActorKind.ADMIN, actor_id=fixture.admin_id))
    submission = fixture.submit()
    with fixture.session_factory.begin() as session:
        session.get(Paper, fixture.paper_id).title = 'Later mutable title'
    fixture.login('publication.admin')
    response = fixture.client.get(f'/api/v2/admin/submissions/{submission.id}?include_comparison=true')
    assert response.status_code == 200
    result = response.json()
    comparison = result['comparison']
    assert comparison['kind'] == 'reviewer_start'
    assert comparison['baseline_snapshot']['paper']['title'] == 'Frozen submitted title'
    assert result['submission']['snapshot']['paper']['title'] == 'Admin corrected title'
    assert {e['actor_kind'] for e in comparison['events']} == {'reviewer','admin'}
    assert comparison['warnings'] == []
    assert result['submission']['content_hash'] == submission.content_hash


def test_resubmission_comparison_uses_previous_frozen_snapshot_and_all_round_actors(publication_fixture):
    fixture = publication_fixture
    first = fixture.submit()
    with fixture.session_factory.begin() as session:
        PublicationService().decide(session, submission_id=first.id,
            content_hash=first.content_hash, action=AdminDecisionAction.REQUEST_CHANGES,
            reason='Correct title', idempotency_key='comparison-request',
            actor=session.get(User, fixture.admin_id))
    with fixture.session_factory.begin() as session:
        session.get(Paper, fixture.paper_id).title = 'Admin edit this round'
        session.add(ChangeEvent(paper_id=fixture.paper_id, workspace_id=fixture.workspace_id,
            entity_type='paper', entity_id=fixture.paper_id, action='bibliography.update',
            before_value={'title':'Frozen submitted title'}, after_value={'title':'Admin edit this round'},
            actor_kind=ChangeActorKind.ADMIN, actor_id=fixture.admin_id))
    second = fixture.submit(key='comparison-second')
    fixture.login('publication.admin')
    response = fixture.client.get(f'/api/v2/admin/submissions/{second.id}?include_comparison=true')
    assert response.status_code == 200
    comparison = response.json()['comparison']
    assert comparison['kind'] == 'previous_submission'
    assert comparison['baseline_submission_number'] == 1
    assert comparison['baseline_snapshot'] == first.snapshot
    assert [e['action'] for e in comparison['events']] == [
        'submission.request_changes','bibliography.update','workspace.submit']
    assert comparison['events'][1]['actor_kind'] == 'admin'
    assert comparison['warnings'] == []


def test_missing_reviewer_history_has_explicit_unavailable_comparison(publication_fixture):
    fixture = publication_fixture
    submission = fixture.submit()
    fixture.login('publication.admin')
    response = fixture.client.get(f'/api/v2/admin/submissions/{submission.id}?include_comparison=true')
    assert response.status_code == 200
    comparison = response.json()['comparison']
    assert comparison['kind'] == 'unavailable'
    assert comparison['baseline_snapshot'] is None
    assert comparison['warnings']
    fixture.login('publication.reviewer')
    assert fixture.client.get(f'/api/v2/admin/submissions/{submission.id}?include_comparison=true').status_code == 403
