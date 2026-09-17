from __future__ import annotations

from app.papers.models import Paper
from app.publications.models import AdminDecisionAction
from app.publications.service import PublicationService
from app.users.models import User


def test_formal_paper_endpoints_only_expose_approved_snapshot(publication_fixture):
    fixture = publication_fixture
    submission = fixture.submit()
    fixture.login("publication.visitor")

    before_list = fixture.client.get("/api/v2/papers")
    before_detail = fixture.client.get(f"/api/v2/papers/{fixture.paper_id}")
    assert before_list.status_code == 200
    assert before_list.json() == {"items": [], "total": 0}
    assert before_detail.status_code == 404

    with fixture.session_factory.begin() as session:
        admin = session.get(User, fixture.admin_id)
        assert admin is not None
        PublicationService().decide(
            session,
            submission_id=submission.id,
            content_hash=submission.content_hash,
            action=AdminDecisionAction.APPROVE,
            reason="Approved for formal publication.",
            idempotency_key="publish-visible",
            actor=admin,
        )
        paper = session.get(Paper, fixture.paper_id)
        assert paper is not None
        paper.title = "Mutable title after publication"

    listing = fixture.client.get("/api/v2/papers")
    detail = fixture.client.get(f"/api/v2/papers/{fixture.paper_id}")
    hidden = fixture.client.get(f"/api/v2/papers/{fixture.unpublished_paper_id}")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["title"] == "Frozen submitted title"
    assert detail.status_code == 200
    assert detail.json()["bibliography"]["title"] == "Frozen submitted title"
    assert detail.json()["content_hash"] == submission.content_hash
    assert detail.json()["snapshot"]["paper"]["title"] == "Frozen submitted title"
    assert detail.json()["snapshot"]["source"] == {
        "sha256": "a" * 64,
        "page_count": 1,
    }
    assert "workspace_version" not in detail.json()["snapshot"]
    assert "asset_id" not in detail.json()["snapshot"]["source"]
    assert "Mutable title after publication" not in detail.text
    assert "/private/" not in detail.text
    assert hidden.status_code == 404


def test_anonymous_users_cannot_read_formal_papers(publication_fixture):
    response = publication_fixture.client.get("/api/v2/papers")
    assert response.status_code == 401
