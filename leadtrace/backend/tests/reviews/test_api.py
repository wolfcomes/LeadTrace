from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError

from app.config import Settings
from app.audit.models import AuditEvent
from app.audit.service import canonical_content_hash
from app.compounds.models import Compound
from app.database import DatabaseResources
from app.main import create_app
from app.papers.models import Paper
from app.releases.models import Release, ReleaseItem
from app.revisions.models import ObjectKind, ObjectRevision
from app.revisions.service import RevisionService
from app.reviews.models import Changeset
from app.reviews.comments import ReviewComment, ReviewCommentEvent
from app.reviews.service import ReviewService
from app.security.policies import WorkflowState
from app.users.models import UserRole
from app.users.service import UserService
from app.visual_objects.models import VisualRegion


PASSWORD = "Review API password 2026!"


def _settings(tmp_path: Path, database_url: str) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        redis_url="redis://127.0.0.1:6379/0",
        session_secret="review-api-session-secret-more-than-thirty-two-characters",
        allowed_hosts=["testserver"],
        asset_root=tmp_path,
    )


def _seed_review(session) -> dict[str, UUID | str]:
    users = UserService()
    identities = {}
    for name, role in (
        ("review-api-reviewer", UserRole.REVIEWER),
        ("review-api-other", UserRole.REVIEWER),
        ("review-api-visitor", UserRole.VISITOR),
        ("review-api-admin", UserRole.ADMIN),
    ):
        user = users.create_user(
            session,
            username=f"{name}-{uuid4().hex[:6]}",
            display_name=name,
            role=role,
            initial_password=PASSWORD,
        )
        user.must_change_password = False
        identities[name] = user.id
        identities[f"{name}-username"] = user.username

    paper = Paper(paper_key=f"review-api-paper-{uuid4().hex[:8]}", doi=None)
    session.add(paper)
    session.flush()
    release = Release(
        release_key=f"review-api-release-{uuid4().hex[:8]}",
        title="Review API release",
        notes="",
        metrics={},
        published_by_id=identities["review-api-admin"],
        published_at=datetime.now(UTC),
        is_current=True,
        manifest_finalized=False,
    )
    session.add(release)
    session.flush()
    paper_revision = RevisionService().create_revision(
        session,
        object_identity=paper,
        actor_id=identities["review-api-admin"],
        reason="Review API published base",
        snapshot={"paper_key": paper.paper_key},
        workflow_state=WorkflowState.PUBLISHED,
        is_current_published=True,
    )
    visual_region = VisualRegion(
        paper_id=paper.id,
        region_key=f"review-api-region-{uuid4().hex[:8]}",
        page_number=1,
    )
    session.add(visual_region)
    session.flush()
    visual_region_revision = RevisionService().create_revision(
        session,
        object_identity=visual_region,
        actor_id=identities["review-api-admin"],
        reason="Review API published visual region base",
        snapshot={"normalized_values": {"label": "Figure 1"}},
        workflow_state=WorkflowState.PUBLISHED,
        is_current_published=True,
        region_bounds=(0.1, 0.2, 0.4, 0.5),
        region_rotation=0,
    )
    session.add(
        ReleaseItem(
            release_id=release.id,
            object_id=paper.id,
            revision_id=paper_revision.id,
            paper_id=paper.id,
            object_kind=ObjectKind.PAPER,
            manifest_order=1,
        )
    )
    session.add(
        ReleaseItem(
            release_id=release.id,
            object_id=visual_region.id,
            revision_id=visual_region_revision.id,
            paper_id=paper.id,
            object_kind=ObjectKind.VISUAL_REGION,
            manifest_order=2,
        )
    )
    session.flush()
    release.manifest_finalized = True
    session.flush()
    task = ReviewService().create_task(
        session,
        paper_id=paper.id,
        assignee_id=identities["review-api-reviewer"],
        created_by_id=identities["review-api-admin"],
    )
    identities["paper"] = paper.id
    identities["release"] = release.id
    identities["task"] = task.id
    identities["paper_revision"] = paper_revision.id
    identities["visual_region"] = visual_region.id
    identities["visual_region_revision"] = visual_region_revision.id
    return identities


def _login(client: TestClient, username: str) -> str:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_review_api_enforces_roles_scope_csrf_and_version_conflicts(
    tmp_path: Path,
    postgresql_database_url: str,
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        seeded = _seed_review(session)

    resources = DatabaseResources(
        engine=auth_session_factory.kw["bind"],
        session_factory=auth_session_factory,
    )
    application = create_app(
        settings=_settings(tmp_path, postgresql_database_url),
        database_probe=lambda _: True,
        database_bootstrap=lambda _: resources,
    )
    with TestClient(application) as client:
        _login(client, str(seeded["review-api-visitor-username"]))
        assert client.get("/api/v1/review/tasks").status_code == 403

        reviewer_csrf = _login(
            client,
            str(seeded["review-api-reviewer-username"]),
        )
        tasks = client.get("/api/v1/review/tasks")
        assert tasks.status_code == 200
        assert [item["id"] for item in tasks.json()] == [str(seeded["task"])]

        long_reason = "r" * 4000
        create_payload = {
            "review_task_id": str(seeded["task"]),
            "paper_id": str(seeded["paper"]),
            "base_release_id": str(seeded["release"]),
            "title": "Correct parent compound",
            "reason": long_reason,
        }
        assert (
            client.post("/api/v1/review/changesets", json=create_payload).status_code
            == 403
        )
        created = client.post(
            "/api/v1/review/changesets",
            headers={"X-CSRF-Token": reviewer_csrf},
            json=create_payload,
        )
        assert created.status_code == 201
        changeset_id = created.json()["id"]
        duplicate = client.post(
            "/api/v1/review/changesets",
            headers={"X-CSRF-Token": reviewer_csrf},
            json=create_payload,
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["code"] == "REVIEW_STATE_CONFLICT"
        listed_changesets = client.get("/api/v1/review/changesets")
        assert listed_changesets.status_code == 200
        assert [item["id"] for item in listed_changesets.json()] == [changeset_id]

        item_created = client.post(
            f"/api/v1/review/changesets/{changeset_id}/items",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={
                "expected_version": 1,
                "object_id": str(seeded["paper"]),
                "object_kind": "paper",
                "base_revision_id": str(seeded["paper_revision"]),
                "proposed_snapshot": {
                    "paper_key": "reviewed-paper",
                    "review_status": "reviewed",
                },
            },
        )
        assert item_created.status_code == 201
        assert item_created.json()["changeset_version"] == 2
        item_id = item_created.json()["id"]
        listed_items = client.get(
            f"/api/v1/review/changesets/{changeset_id}/items"
        )
        assert listed_items.status_code == 200
        assert [item["id"] for item in listed_items.json()] == [item_id]
        structured_diff = client.get(
            f"/api/v1/review/changesets/{changeset_id}/diff"
        )
        assert structured_diff.status_code == 200
        assert structured_diff.json()[0]["object_id"] == str(seeded["paper"])
        assert structured_diff.json()[0]["base_revision_id"] == str(
            seeded["paper_revision"]
        )
        assert structured_diff.json()[0]["change_type"] == "update"
        assert structured_diff.json()[0]["changes"]
        item_updated = client.patch(
            f"/api/v1/review/changesets/{changeset_id}/items/{item_id}",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={
                "expected_version": 2,
                "proposed_snapshot": {
                    "paper_key": "reviewed-paper",
                    "review_status": "confirmed",
                },
            },
        )
        assert item_updated.status_code == 200
        assert item_updated.json()["changeset_version"] == 3
        item_deleted = client.request(
            "DELETE",
            f"/api/v1/review/changesets/{changeset_id}/items/{item_id}",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={"expected_version": 3},
        )
        assert item_deleted.status_code == 200
        assert item_deleted.json()["version"] == 4
        item_recreated = client.post(
            f"/api/v1/review/changesets/{changeset_id}/items",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={
                "expected_version": 4,
                "object_id": str(seeded["paper"]),
                "object_kind": "paper",
                "base_revision_id": str(seeded["paper_revision"]),
                "proposed_snapshot": item_updated.json()["proposed_snapshot"],
            },
        )
        assert item_recreated.status_code == 201
        assert item_recreated.json()["changeset_version"] == 5

        updated = client.patch(
            f"/api/v1/review/changesets/{changeset_id}",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={"expected_version": 5, "title": "Correct direct parent"},
        )
        assert updated.status_code == 200
        assert updated.json()["version"] == 6
        stale = client.patch(
            f"/api/v1/review/changesets/{changeset_id}",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={"expected_version": 5, "title": "Stale overwrite"},
        )
        assert stale.status_code == 409
        assert stale.json()["details"] == {
            "expected_version": 5,
            "current_version": 6,
        }

        _login(client, str(seeded["review-api-other-username"]))
        concealed = client.get(f"/api/v1/review/changesets/{changeset_id}")
        assert concealed.status_code == 404

        reviewer_csrf = _login(
            client,
            str(seeded["review-api-reviewer-username"]),
        )
        submitted = client.post(
            f"/api/v1/review/changesets/{changeset_id}/submit",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={"expected_version": 6},
        )
        assert submitted.status_code == 200
        assert submitted.json()["workflow_state"] == "submitted"
        assert (
            submitted.json()["submitted_snapshot"]["title"] == "Correct direct parent"
        )
        assert submitted.json()["submitted_snapshot"]["reason"] == long_reason
        blocked_edit = client.patch(
            f"/api/v1/review/changesets/{changeset_id}",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={"expected_version": 7, "title": "Edit after submission"},
        )
        assert blocked_edit.status_code == 409
        assert blocked_edit.json()["code"] == "REVIEW_STATE_CONFLICT"
        repeated_submit = client.post(
            f"/api/v1/review/changesets/{changeset_id}/submit",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={"expected_version": 7},
        )
        assert repeated_submit.status_code == 409
        assert repeated_submit.json()["code"] == "REVIEW_STATE_CONFLICT"
        reviewer_approval = client.post(
            f"/api/v1/review/changesets/{changeset_id}/approve",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={
                "expected_version": 7,
                "reason": "Only an Admin may approve this submission.",
            },
        )
        assert reviewer_approval.status_code == 403

        admin_csrf = _login(client, str(seeded["review-api-admin-username"]))
        missing_decision_reason = client.post(
            f"/api/v1/review/changesets/{changeset_id}/approve",
            headers={"X-CSRF-Token": admin_csrf},
            json={"expected_version": 7},
        )
        assert missing_decision_reason.status_code == 422
        blank_decision_reason = client.post(
            f"/api/v1/review/changesets/{changeset_id}/approve",
            headers={"X-CSRF-Token": admin_csrf},
            json={"expected_version": 7, "reason": "   "},
        )
        assert blank_decision_reason.status_code == 422
        decision_reason = "Source evidence and proposed metadata were verified."
        approved = client.post(
            f"/api/v1/review/changesets/{changeset_id}/approve",
            headers={"X-CSRF-Token": admin_csrf},
            json={"expected_version": 7, "reason": decision_reason},
        )
        assert approved.status_code == 200
        assert approved.json()["workflow_state"] == "approved"

    with auth_session_factory() as session:
        changeset = session.get(Changeset, UUID(changeset_id))
        assert changeset is not None
        assert changeset.workflow_state is WorkflowState.APPROVED
        assert session.get(Release, seeded["release"]).is_current
        assert list(
            session.scalars(
                select(AuditEvent.action).order_by(AuditEvent.sequence_number)
            )
        ) == [
            "review.changeset.created",
            "review.changeset_item.created",
            "review.changeset_item.updated",
            "review.changeset_item.deleted",
            "review.changeset_item.created",
            "review.changeset.updated",
            "review.changeset.submitted",
            "review.changeset.approved",
        ]
        approval_event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "review.changeset.approved"
            )
        )
        assert approval_event is not None
        assert approval_event.reason == decision_reason
        assert approval_event.before_hash == canonical_content_hash(
            approval_event.details["before"]
        )
        assert approval_event.after_hash == canonical_content_hash(
            approval_event.details["after"]
        )


def test_changeset_diff_includes_visual_region_revision_columns(
    tmp_path: Path,
    postgresql_database_url: str,
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        seeded = _seed_review(session)
        service = ReviewService()
        changeset = service.create_changeset(
            session,
            paper_id=seeded["paper"],
            actor_id=seeded["review-api-reviewer"],
            review_task_id=seeded["task"],
            base_release_id=seeded["release"],
            title="Correct visual region",
            reason="Align the figure crop with the source PDF",
        )
        base_revision = session.get(
            ObjectRevision,
            seeded["visual_region_revision"],
        )
        visual_region = session.get(VisualRegion, seeded["visual_region"])
        assert base_revision is not None
        assert visual_region is not None
        item = service.add_changeset_item(
            session,
            changeset_id=changeset.id,
            actor_id=seeded["review-api-reviewer"],
            expected_version=1,
            object_id=visual_region.id,
            object_kind=ObjectKind.VISUAL_REGION.value,
            base_revision_id=base_revision.id,
            proposed_snapshot=base_revision.snapshot,
        )
        proposed_revision = RevisionService().create_revision(
            session,
            object_identity=visual_region,
            actor_id=seeded["review-api-reviewer"],
            reason="Correct crop coordinates and rotation",
            snapshot=base_revision.snapshot,
            predecessor=base_revision,
            changeset_id=changeset.id,
            region_bounds=(0.2, 0.2, 0.4, 0.5),
            region_rotation=90,
        )
        submitted = service.submit_changeset(
            session,
            changeset_id=changeset.id,
            actor_id=seeded["review-api-reviewer"],
            expected_version=2,
        )
        session.refresh(item)
        assert item.proposed_revision_id == proposed_revision.id
        changeset_id = submitted.id

    resources = DatabaseResources(
        engine=auth_session_factory.kw["bind"],
        session_factory=auth_session_factory,
    )
    application = create_app(
        settings=_settings(tmp_path, postgresql_database_url),
        database_probe=lambda _: True,
        database_bootstrap=lambda _: resources,
    )
    with TestClient(application) as client:
        _login(client, str(seeded["review-api-reviewer-username"]))
        response = client.get(f"/api/v1/review/changesets/{changeset_id}/diff")

    assert response.status_code == 200
    assert response.json() == [
        {
            "object_id": str(seeded["visual_region"]),
            "object_kind": ObjectKind.VISUAL_REGION.value,
            "base_revision_id": str(seeded["visual_region_revision"]),
            "proposed_revision_id": str(proposed_revision.id),
            "change_type": "update",
            "changes": [
                {
                    "path": "/region/rotation",
                    "category": "region_coordinate",
                    "before_present": True,
                    "after_present": True,
                    "before": 0,
                    "after": 90,
                },
                {
                    "path": "/region/x0",
                    "category": "region_coordinate",
                    "before_present": True,
                    "after_present": True,
                    "before": 0.1,
                    "after": 0.2,
                },
            ],
        }
    ]


def test_admin_can_create_edit_and_submit_for_assigned_reviewer(
    tmp_path: Path,
    postgresql_database_url: str,
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        seeded = _seed_review(session)

    resources = DatabaseResources(
        engine=auth_session_factory.kw["bind"],
        session_factory=auth_session_factory,
    )
    application = create_app(
        settings=_settings(tmp_path, postgresql_database_url),
        database_probe=lambda _: True,
        database_bootstrap=lambda _: resources,
    )
    with TestClient(application) as client:
        admin_csrf = _login(client, str(seeded["review-api-admin-username"]))
        created = client.post(
            "/api/v1/review/changesets",
            headers={"X-CSRF-Token": admin_csrf},
            json={
                "review_task_id": str(seeded["task"]),
                "paper_id": str(seeded["paper"]),
                "base_release_id": str(seeded["release"]),
                "title": "Admin-assisted review",
                "reason": "Admin prepares a draft for the assigned Reviewer",
            },
        )
        assert created.status_code == 201
        assert created.json()["owner_id"] == str(seeded["review-api-reviewer"])
        changeset_id = created.json()["id"]

        item = client.post(
            f"/api/v1/review/changesets/{changeset_id}/items",
            headers={"X-CSRF-Token": admin_csrf},
            json={
                "expected_version": 1,
                "object_id": str(seeded["paper"]),
                "object_kind": "paper",
                "base_revision_id": str(seeded["paper_revision"]),
                "proposed_snapshot": {"paper_key": "admin-reviewed"},
            },
        )
        assert item.status_code == 201
        with auth_session_factory.begin() as session:
            paper = session.get(Paper, seeded["paper"])
            assert paper is not None
            RevisionService().create_revision(
                session,
                object_identity=paper,
                actor_id=seeded["review-api-admin"],
                reason="Admin-assisted draft revision",
                snapshot=item.json()["proposed_snapshot"],
                predecessor=session.get(
                    ObjectRevision,
                    seeded["paper_revision"],
                ),
                changeset_id=UUID(changeset_id),
            )
        blocked_delete = client.request(
            "DELETE",
            f"/api/v1/review/changesets/{changeset_id}/items/{item.json()['id']}",
            headers={"X-CSRF-Token": admin_csrf},
            json={"expected_version": 2},
        )
        assert blocked_delete.status_code == 409
        assert blocked_delete.json()["code"] == "CHANGESET_ITEM_HAS_REVISIONS"
        edited = client.patch(
            f"/api/v1/review/changesets/{changeset_id}",
            headers={"X-CSRF-Token": admin_csrf},
            json={"expected_version": 2, "title": "Admin-assisted correction"},
        )
        assert edited.status_code == 200
        submitted = client.post(
            f"/api/v1/review/changesets/{changeset_id}/submit",
            headers={"X-CSRF-Token": admin_csrf},
            json={"expected_version": 3},
        )
        assert submitted.status_code == 200
        assert submitted.json()["workflow_state"] == "submitted"


def test_comment_api_preserves_resolution_history_and_scope_boundaries(
    tmp_path: Path,
    postgresql_database_url: str,
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        seeded = _seed_review(session)
        changeset = ReviewService().create_changeset(
            session,
            paper_id=seeded["paper"],
            actor_id=seeded["review-api-reviewer"],
            review_task_id=seeded["task"],
            base_release_id=seeded["release"],
            title="Comment-scoped review",
            reason="Discuss a source-bound field",
        )
        service = ReviewService()
        paper_item = service.add_changeset_item(
            session,
            changeset_id=changeset.id,
            actor_id=seeded["review-api-reviewer"],
            expected_version=1,
            object_id=seeded["paper"],
            object_kind="paper",
            base_revision_id=seeded["paper_revision"],
            proposed_snapshot={"title": "Reviewed title"},
        )
        compound = Compound(
            paper_id=seeded["paper"],
            local_identity=f"comment-compound-{uuid4().hex[:8]}",
            display_label="Comment compound",
            normalized_label="comment compound",
        )
        session.add(compound)
        session.flush()
        compound_item = service.add_changeset_item(
            session,
            changeset_id=changeset.id,
            actor_id=seeded["review-api-reviewer"],
            expected_version=2,
            object_id=compound.id,
            object_kind="compound",
            proposed_snapshot={"display_label": "Comment compound"},
        )
        changeset_id = changeset.id
        paper_item_id = paper_item.id
        compound_id = compound.id
        compound_item_id = compound_item.id

    resources = DatabaseResources(
        engine=auth_session_factory.kw["bind"],
        session_factory=auth_session_factory,
    )
    settings = _settings(tmp_path, postgresql_database_url)
    settings.trusted_proxy_addresses = ["testclient"]
    application = create_app(
        settings=settings,
        database_probe=lambda _: True,
        database_bootstrap=lambda _: resources,
    )
    with TestClient(application) as client:
        _login(client, str(seeded["review-api-visitor-username"]))
        assert (
            client.get(
                f"/api/v1/review/changesets/{changeset_id}/comments"
            ).status_code
            == 403
        )

        reviewer_csrf = _login(
            client, str(seeded["review-api-reviewer-username"])
        )
        payload = {
            "target_type": "field",
            "target_id": str(seeded["paper"]),
            "field_path": "/title",
            "body": "The title should match the article PDF.",
        }
        outside_scope = client.post(
            f"/api/v1/review/changesets/{changeset_id}/comments",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={
                "target_type": "compound",
                "target_id": str(uuid4()),
                "body": "This compound is not part of the Changeset.",
            },
        )
        assert outside_scope.status_code == 422
        unanchored_field = client.post(
            f"/api/v1/review/changesets/{changeset_id}/comments",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={
                "target_type": "field",
                "field_path": "/title",
                "body": "A field comment must identify its object or item.",
            },
        )
        assert unanchored_field.status_code == 422
        changeset_with_item_anchor = client.post(
            f"/api/v1/review/changesets/{changeset_id}/comments",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={
                "target_type": "changeset",
                "target_id": str(changeset_id),
                "changeset_item_id": str(paper_item_id),
                "body": "A changeset comment cannot also target an item.",
            },
        )
        assert changeset_with_item_anchor.status_code == 422
        changeset_with_field_anchor = client.post(
            f"/api/v1/review/changesets/{changeset_id}/comments",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={
                "target_type": "changeset",
                "target_id": str(changeset_id),
                "field_path": "/title",
                "body": "A changeset comment cannot also target a field.",
            },
        )
        assert changeset_with_field_anchor.status_code == 422
        compound_with_field_anchor = client.post(
            f"/api/v1/review/changesets/{changeset_id}/comments",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={
                "target_type": "compound",
                "target_id": str(compound_id),
                "field_path": "/display_label",
                "body": "A compound comment cannot also carry a field path.",
            },
        )
        assert compound_with_field_anchor.status_code == 422
        change_item_with_field_anchor = client.post(
            f"/api/v1/review/changesets/{changeset_id}/comments",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={
                "target_type": "change_item",
                "target_id": str(paper_item_id),
                "changeset_item_id": str(paper_item_id),
                "field_path": "/title",
                "body": "A change-item comment cannot also carry a field path.",
            },
        )
        assert change_item_with_field_anchor.status_code == 422
        change_item_mismatched_target = client.post(
            f"/api/v1/review/changesets/{changeset_id}/comments",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={
                "target_type": "change_item",
                "target_id": str(compound_id),
                "changeset_item_id": str(paper_item_id),
                "body": "A change-item target must identify that same item.",
            },
        )
        assert change_item_mismatched_target.status_code == 422
        valid_change_item = client.post(
            f"/api/v1/review/changesets/{changeset_id}/comments",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={
                "target_type": "change_item",
                "target_id": str(paper_item_id),
                "changeset_item_id": str(paper_item_id),
                "body": "The paper item is a valid change-item anchor.",
            },
        )
        assert valid_change_item.status_code == 201
        valid_change_item_id = valid_change_item.json()["id"]
        for target_type in ("field", "compound"):
            cross_item = client.post(
                f"/api/v1/review/changesets/{changeset_id}/comments",
                headers={"X-CSRF-Token": reviewer_csrf},
                json={
                    "target_type": target_type,
                    "target_id": str(compound_id),
                    "changeset_item_id": str(paper_item_id),
                    "field_path": "/display_label"
                    if target_type == "field"
                    else None,
                    "body": "The target cannot come from a different item.",
                },
            )
            assert cross_item.status_code == 422
        anchored_field = client.post(
            f"/api/v1/review/changesets/{changeset_id}/comments",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={
                "target_type": "field",
                "changeset_item_id": str(compound_item_id),
                "field_path": "/display_label",
                "body": "The item itself is a valid field anchor.",
            },
        )
        assert anchored_field.status_code == 201
        anchored_comment_id = anchored_field.json()["id"]
        assert (
            client.post(
                f"/api/v1/review/changesets/{changeset_id}/comments",
                json=payload,
            ).status_code
            == 403
        )
        created = client.post(
            f"/api/v1/review/changesets/{changeset_id}/comments",
            headers={
                "X-CSRF-Token": reviewer_csrf,
                "X-Real-IP": "203.0.113.77",
            },
            json=payload,
        )
        assert created.status_code == 201
        comment_id = created.json()["id"]
        assert created.json()["state"] == "open"
        assert created.json()["body"] == payload["body"]

        listed = client.get(
            f"/api/v1/review/changesets/{changeset_id}/comments"
        )
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == [
            valid_change_item_id,
            anchored_comment_id,
            comment_id,
        ]

        _login(client, str(seeded["review-api-other-username"]))
        assert (
            client.get(
                f"/api/v1/review/changesets/{changeset_id}/comments"
            ).status_code
            == 404
        )

        admin_csrf = _login(client, str(seeded["review-api-admin-username"]))
        resolved = client.post(
            f"/api/v1/review/comments/{comment_id}/resolve",
            headers={"X-CSRF-Token": admin_csrf},
            json={"reason": "Checked against the source PDF."},
        )
        assert resolved.status_code == 200
        assert resolved.json()["state"] == "resolved"

        reviewer_csrf = _login(
            client, str(seeded["review-api-reviewer-username"])
        )
        reopened = client.post(
            f"/api/v1/review/comments/{comment_id}/reopen",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={"reason": "The supporting page reference is still missing."},
        )
        assert reopened.status_code == 200
        assert reopened.json()["state"] == "open"
        history = client.get(f"/api/v1/review/comments/{comment_id}/history")
        assert history.status_code == 200
        assert [event["action"] for event in history.json()] == [
            "created",
            "resolved",
            "reopened",
        ]

    with auth_session_factory() as session:
        audit_events = list(
            session.scalars(select(AuditEvent).order_by(AuditEvent.sequence_number))
        )
        target_events = [
            event
            for event in audit_events
            if event.target_id == UUID(comment_id)
        ]
        assert [event.action for event in target_events] == [
            "review.comment.created",
            "review.comment.resolved",
            "review.comment.reopened",
        ]
        assert target_events[0].ip_address == "203.0.113.77"
        assert target_events[0].after_hash == target_events[1].before_hash
        assert target_events[1].after_hash == target_events[2].before_hash
        comment_event_id = session.scalar(
            select(ReviewCommentEvent.id).where(
                ReviewCommentEvent.comment_id == UUID(comment_id)
            )
        )
        assert comment_event_id is not None

    with auth_session_factory() as session:
        with pytest.raises(DBAPIError):
            session.execute(
                update(ReviewComment)
                .where(ReviewComment.id == UUID(comment_id))
                .values(body="tampered")
            )
        session.rollback()
    with auth_session_factory() as session:
        with pytest.raises(DBAPIError):
            session.execute(
                delete(ReviewCommentEvent).where(
                    ReviewCommentEvent.id == comment_event_id
                )
            )
        session.rollback()


def test_field_comment_can_target_paper_before_paper_item_is_added(
    tmp_path: Path,
    postgresql_database_url: str,
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        seeded = _seed_review(session)
        changeset = ReviewService().create_changeset(
            session,
            paper_id=seeded["paper"],
            actor_id=seeded["review-api-reviewer"],
            review_task_id=seeded["task"],
            base_release_id=seeded["release"],
            title="Paper field review",
            reason="Discuss a Paper field before creating an item",
        )
        changeset_id = changeset.id

    resources = DatabaseResources(
        engine=auth_session_factory.kw["bind"],
        session_factory=auth_session_factory,
    )
    application = create_app(
        settings=_settings(tmp_path, postgresql_database_url),
        database_probe=lambda _: True,
        database_bootstrap=lambda _: resources,
    )
    with TestClient(application) as client:
        reviewer_csrf = _login(
            client,
            str(seeded["review-api-reviewer-username"]),
        )
        response = client.post(
            f"/api/v1/review/changesets/{changeset_id}/comments",
            headers={"X-CSRF-Token": reviewer_csrf},
            json={
                "target_type": "field",
                "target_id": str(seeded["paper"]),
                "field_path": "/title",
                "body": "The Paper title needs source verification.",
            },
        )

    assert response.status_code == 201
    assert response.json()["target_id"] == str(seeded["paper"])
