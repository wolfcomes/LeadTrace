from __future__ import annotations

from sqlalchemy import select

from app.papers.models import Paper
from app.users.models import UserRole
from app.workspaces.models import ChangeEvent, PaperSection, PaperSectionReview


def test_reviewer_lists_only_their_tasks_and_reads_safe_workspace_aggregate(
    workspace_fixture,
) -> None:
    workspace_fixture.login("workspace.reviewer")

    listing = workspace_fixture.client.get("/api/v2/review/tasks")
    detail = workspace_fixture.client.get(
        f"/api/v2/workspaces/{workspace_fixture.workspace_id}"
    )

    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert len(listing.json()["items"]) == 1
    assert listing.json()["items"][0]["workspace_id"] == str(
        workspace_fixture.workspace_id
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["id"] == str(workspace_fixture.workspace_id)
    assert payload["version"] == 1
    assert payload["state"] == "editing"
    assert payload["bibliography"]["title"] == "Extracted title"
    assert payload["source"] == {
        "asset_id": str(workspace_fixture.asset_id),
        "source_root_key": "source_pdfs",
        "source_key": "volume67 issue5/paper-01.pdf",
    }
    assert len(payload["sections"]) == 6
    assert "storage_key" not in detail.text
    assert "source_metadata" not in detail.text
    assert "sha256" not in detail.text
    assert "/srv/private" not in detail.text
    assert "must-never-be-returned" not in detail.text
    assert "csrf" not in detail.text.casefold()


def test_reviewer_updates_bibliography_and_section_with_versioned_history(
    workspace_fixture,
) -> None:
    csrf = workspace_fixture.login("workspace.reviewer")

    bibliography = workspace_fixture.client.patch(
        f"/api/v2/workspaces/{workspace_fixture.workspace_id}/bibliography",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": 1,
            "title": "Reviewer corrected title",
            "doi": None,
        },
    )
    section = workspace_fixture.client.put(
        f"/api/v2/workspaces/{workspace_fixture.workspace_id}/sections/compounds",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": 2,
            "state": "not_reported",
            "note": "No compound series was reported.",
        },
    )

    assert bibliography.status_code == 200
    assert bibliography.json()["version"] == 2
    assert bibliography.json()["bibliography"]["title"] == (
        "Reviewer corrected title"
    )
    assert bibliography.json()["bibliography"]["doi"] is None
    assert section.status_code == 200
    assert section.json()["version"] == 3
    compounds = next(
        item
        for item in section.json()["sections"]
        if item["section_key"] == "compounds"
    )
    assert compounds == {
        "section_key": "compounds",
        "state": "not_reported",
        "note": "No compound series was reported.",
    }

    with workspace_fixture.session_factory() as session:
        paper = session.get(Paper, workspace_fixture.paper_id)
        section_row = session.scalar(
            select(PaperSectionReview).where(
                PaperSectionReview.workspace_id == workspace_fixture.workspace_id,
                PaperSectionReview.section_key == PaperSection.COMPOUNDS,
            )
        )
        events = list(
            session.scalars(select(ChangeEvent).order_by(ChangeEvent.occurred_at))
        )
        assert paper is not None
        assert section_row is not None
        assert paper.title == "Reviewer corrected title"
        assert paper.doi is None
        assert section_row.state.value == "not_reported"
        assert [event.action for event in events] == [
            "bibliography.update",
            "section.update",
        ]
        assert events[0].before_value == {
            "title": "Extracted title",
            "doi": "10.1021/acs.jmedchem.4c0001",
        }
        assert events[0].after_value == {
            "title": "Reviewer corrected title",
            "doi": None,
        }
        assert events[1].entity_type == "paper_section_review"
        assert events[1].entity_id == section_row.id
        assert events[1].before_value == {
            "section_key": "compounds",
            "state": "pending",
            "note": None,
        }
        assert events[1].after_value == {
            "section_key": "compounds",
            "state": "not_reported",
            "note": "No compound series was reported.",
        }


def test_workspace_authorization_csrf_and_payload_boundaries(workspace_fixture) -> None:
    other_csrf = workspace_fixture.login("workspace.other")

    concealed_read = workspace_fixture.client.get(
        f"/api/v2/workspaces/{workspace_fixture.workspace_id}"
    )
    concealed_write = workspace_fixture.client.patch(
        f"/api/v2/workspaces/{workspace_fixture.workspace_id}/bibliography",
        headers={"X-CSRF-Token": other_csrf},
        json={"expected_workspace_version": 1, "title": "Leaked"},
    )

    assert concealed_read.status_code == 404
    assert concealed_write.status_code == 404
    assert concealed_read.json()["message"] == "Resource not found"
    assert concealed_write.json()["message"] == "Resource not found"
    assert "Extracted title" not in concealed_read.text
    assert "Extracted title" not in concealed_write.text

    reviewer_csrf = workspace_fixture.login("workspace.reviewer")
    missing_csrf = workspace_fixture.client.patch(
        f"/api/v2/workspaces/{workspace_fixture.workspace_id}/bibliography",
        json={"expected_workspace_version": 1, "title": "No CSRF"},
    )
    immutable_source = workspace_fixture.client.patch(
        f"/api/v2/workspaces/{workspace_fixture.workspace_id}/bibliography",
        headers={"X-CSRF-Token": reviewer_csrf},
        json={
            "expected_workspace_version": 1,
            "title": "Attempted source rewrite",
            "source_key": "other.pdf",
        },
    )

    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["code"] == "CSRF_VALIDATION_FAILED"
    assert immutable_source.status_code == 422
    with workspace_fixture.session_factory() as session:
        paper = session.get(Paper, workspace_fixture.paper_id)
        assert paper is not None
        assert paper.title == "Extracted title"
        assert list(session.scalars(select(ChangeEvent))) == []


def test_admin_can_read_workspace_but_visitor_cannot(workspace_fixture) -> None:
    workspace_fixture.login("workspace.admin")
    admin_read = workspace_fixture.client.get(
        f"/api/v2/workspaces/{workspace_fixture.workspace_id}"
    )
    assert admin_read.status_code == 200

    workspace_fixture.login("workspace.visitor")
    visitor_list = workspace_fixture.client.get("/api/v2/review/tasks")
    visitor_read = workspace_fixture.client.get(
        f"/api/v2/workspaces/{workspace_fixture.workspace_id}"
    )
    assert visitor_list.status_code == 403
    assert visitor_read.status_code == 403
