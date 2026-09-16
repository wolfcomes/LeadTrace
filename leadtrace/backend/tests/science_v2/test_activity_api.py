from __future__ import annotations

from sqlalchemy import func, select

from app.activities.models import Activity
from app.compounds.models import Compound
from app.evidence.models import Evidence, EvidenceKind
from app.workspaces.models import (
    ChangeActorKind,
    ChangeEvent,
    PaperWorkspace,
    WorkspaceState,
)


def _source_sha(context, paper_id):
    from app.catalog.models import PaperSource
    from app.papers.models import Paper

    with context.session_factory() as session:
        return session.scalar(
            select(PaperSource.sha256)
            .join(Paper, Paper.source_id == PaperSource.id)
            .where(Paper.id == paper_id)
        )


def _seed_compounds_and_evidence(context):
    with context.session_factory.begin() as session:
        first = context.first
        second = context.second
        compound = Compound(
            paper_id=first.paper_id,
            workspace_id=first.workspace_id,
            compound_label="A-1",
            sort_order=0,
            created_by_kind=ChangeActorKind.REVIEWER,
        )
        foreign_compound = Compound(
            paper_id=second.paper_id,
            workspace_id=second.workspace_id,
            compound_label="A-X",
            sort_order=0,
            created_by_kind=ChangeActorKind.REVIEWER,
        )
        evidence = Evidence(
            paper_id=first.paper_id,
            workspace_id=first.workspace_id,
            kind=EvidenceKind.TEXT,
            source_sha256=_source_sha(context, first.paper_id),
            page_number=1,
            quoted_text="Activity table",
        )
        foreign_evidence = Evidence(
            paper_id=second.paper_id,
            workspace_id=second.workspace_id,
            kind=EvidenceKind.TEXT,
            source_sha256=_source_sha(context, second.paper_id),
            page_number=1,
            quoted_text="Foreign activity table",
        )
        session.add_all([compound, foreign_compound, evidence, foreign_evidence])
        session.flush()
        return compound.id, foreign_compound.id, evidence.id, foreign_evidence.id


def _create_activity(
    context,
    csrf: str,
    compound_id,
    version: int,
    metric: str,
    value: str,
    evidence_id=None,
):
    return context.client.post(
        f"/api/v2/compounds/{compound_id}/activities",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": version,
            "evidence_id": str(evidence_id) if evidence_id else None,
            "assay_name": "EGFR biochemical assay",
            "metric": metric,
            "operator": "=",
            "value": value,
            "unit": "nM",
            "context": "Cell-free biochemical assay",
        },
    )


def test_multiple_activities_per_compound_can_be_edited_reordered_and_deleted(
    science_api_context,
):
    context = science_api_context
    compound_id, _, evidence_id, _ = _seed_compounds_and_evidence(context)
    csrf = context.login("science.api.reviewer")
    first = _create_activity(context, csrf, compound_id, 1, "IC50", "12.5", evidence_id)
    second = _create_activity(context, csrf, compound_id, 2, "Ki", "3.2")
    assert first.status_code == second.status_code == 201
    first_id = first.json()["activity"]["id"]
    second_id = second.json()["activity"]["id"]

    updated = context.client.patch(
        f"/api/v2/activities/{first_id}",
        headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": 3, "operator": "<", "value": "10"},
    )
    reordered = context.client.put(
        f"/api/v2/compounds/{compound_id}/activities/order",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": 4,
            "activity_ids": [second_id, first_id],
        },
    )
    deleted = context.client.request(
        "DELETE",
        f"/api/v2/activities/{second_id}",
        headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": 5},
    )
    assert updated.status_code == reordered.status_code == deleted.status_code == 200
    assert [item["id"] for item in reordered.json()["items"]] == [second_id, first_id]
    listing = context.client.get(f"/api/v2/compounds/{compound_id}/activities")
    assert listing.status_code == 200
    assert listing.json()["workspace_version"] == 6
    assert [item["id"] for item in listing.json()["items"]] == [first_id]
    with context.session_factory() as session:
        event_count = session.scalar(
            select(func.count())
            .select_from(ChangeEvent)
            .where(ChangeEvent.workspace_id == context.first.workspace_id)
        )
        assert event_count == 5


def test_activity_rejects_cross_workspace_compound_and_evidence(
    science_api_context,
):
    context = science_api_context
    compound_id, foreign_compound_id, _, foreign_evidence_id = _seed_compounds_and_evidence(context)
    csrf = context.login("science.api.reviewer")
    cross_evidence = _create_activity(
        context, csrf, compound_id, 1, "IC50", "20", foreign_evidence_id
    )
    cross_compound = _create_activity(
        context, csrf, foreign_compound_id, 1, "IC50", "20"
    )
    assert cross_evidence.status_code == 404
    assert cross_compound.status_code == 404
    assert cross_evidence.json()["code"] == "RESOURCE_NOT_FOUND"
    assert cross_compound.json()["code"] == "RESOURCE_NOT_FOUND"
    with context.session_factory() as session:
        workspace = session.get(PaperWorkspace, context.first.workspace_id)
        event_count = session.scalar(
            select(func.count())
            .select_from(ChangeEvent)
            .where(ChangeEvent.workspace_id == context.first.workspace_id)
        )
        assert workspace is not None and workspace.version == 1
        assert event_count == 0


def test_activity_writes_enforce_assignment_role_state_csrf_and_version(
    science_api_context,
):
    context = science_api_context
    aggregate = context.first
    compound_id, _, evidence_id, _ = _seed_compounds_and_evidence(context)
    csrf = context.login("science.api.reviewer")
    created = _create_activity(
        context, csrf, compound_id, 1, "IC50", "12.5", evidence_id
    )
    activity_id = created.json()["activity"]["id"]

    stale = _create_activity(context, csrf, compound_id, 1, "Ki", "3.2")
    assert stale.status_code == 409
    assert stale.json()["code"] == "WORKSPACE_VERSION_CONFLICT"

    other_csrf = context.login("science.api.other")
    concealed = context.client.patch(
        f"/api/v2/activities/{activity_id}",
        headers={"X-CSRF-Token": other_csrf},
        json={"expected_workspace_version": 2, "value": "99"},
    )
    assert concealed.status_code == 404

    admin_csrf = context.login("science.api.admin")
    admin_write = context.client.patch(
        f"/api/v2/activities/{activity_id}",
        headers={"X-CSRF-Token": admin_csrf},
        json={"expected_workspace_version": 2, "value": "99"},
    )
    assert admin_write.status_code == 403

    context.login("science.api.reviewer")
    missing_csrf = context.client.patch(
        f"/api/v2/activities/{activity_id}",
        json={"expected_workspace_version": 2, "value": "99"},
    )
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["code"] == "CSRF_VALIDATION_FAILED"

    with context.session_factory.begin() as session:
        workspace = session.get(PaperWorkspace, aggregate.workspace_id)
        assert workspace is not None
        workspace.state = WorkspaceState.SUBMITTED
    reviewer_csrf = context.login("science.api.reviewer")
    readonly = context.client.patch(
        f"/api/v2/activities/{activity_id}",
        headers={"X-CSRF-Token": reviewer_csrf},
        json={"expected_workspace_version": 2, "value": "99"},
    )
    assert readonly.status_code == 409
    assert readonly.json()["code"] == "WORKSPACE_READ_ONLY"
    with context.session_factory() as session:
        activity = session.get(Activity, activity_id)
        workspace = session.get(PaperWorkspace, aggregate.workspace_id)
        event_count = session.scalar(
            select(func.count())
            .select_from(ChangeEvent)
            .where(ChangeEvent.workspace_id == aggregate.workspace_id)
        )
        assert activity is not None and str(activity.value) == "12.5"
        assert workspace is not None and workspace.version == 2
        assert event_count == 1
