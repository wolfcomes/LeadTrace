from __future__ import annotations

from sqlalchemy import func, select

from app.lineages.models import LineageEdge, LineageMember
from app.workspaces.models import ChangeEvent, PaperWorkspace, WorkspaceState


def _create_compound(context, csrf: str, workspace_id, version: int, label: str):
    response = context.client.post(
        f"/api/v2/workspaces/{workspace_id}/compounds",
        headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": version, "compound_label": label},
    )
    assert response.status_code == 201
    return response.json()["compound"]


def _create_lineage(context, csrf: str, workspace_id, version: int, label: str):
    return context.client.post(
        f"/api/v2/workspaces/{workspace_id}/lineages",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": version,
            "lineage_label": label,
            "description": f"{label} optimization series",
        },
    )


def _add_member(context, csrf: str, lineage_id: str, version: int, compound_id: str, role: str):
    return context.client.post(
        f"/api/v2/lineages/{lineage_id}/members",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": version,
            "compound_id": compound_id,
            "role": role,
        },
    )


def _create_edge(
    context,
    csrf: str,
    lineage_id: str,
    version: int,
    parent_id: str,
    child_id: str,
):
    return context.client.post(
        f"/api/v2/lineages/{lineage_id}/edges",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": version,
            "parent_compound_id": parent_id,
            "child_compound_id": child_id,
            "relation_type": "lead_optimization",
            "modification_summary": "Substituent optimization",
            "review_status": "draft",
        },
    )


def _assert_history(context, workspace_id, expected_version: int) -> None:
    with context.session_factory() as session:
        workspace = session.get(PaperWorkspace, workspace_id)
        event_count = session.scalar(
            select(func.count())
            .select_from(ChangeEvent)
            .where(ChangeEvent.workspace_id == workspace_id)
        )
        assert workspace is not None and workspace.version == expected_version
        assert event_count == expected_version - 1


def test_multiple_lineages_shared_members_and_branching_edges(science_api_context):
    context = science_api_context
    csrf = context.login("science.api.reviewer")
    workspace_id = context.first.workspace_id
    root = _create_compound(context, csrf, workspace_id, 1, "L-1")
    middle = _create_compound(context, csrf, workspace_id, 2, "L-2")
    terminal = _create_compound(context, csrf, workspace_id, 3, "L-3")

    first = _create_lineage(context, csrf, workspace_id, 4, "Series A")
    second = _create_lineage(context, csrf, workspace_id, 5, "Series B")
    assert first.status_code == second.status_code == 201
    first_id = first.json()["lineage"]["id"]
    second_id = second.json()["lineage"]["id"]

    mutations = [
        _add_member(context, csrf, first_id, 6, root["id"], "root"),
        _add_member(context, csrf, first_id, 7, middle["id"], "intermediate"),
        _add_member(context, csrf, first_id, 8, terminal["id"], "terminal"),
        _add_member(context, csrf, second_id, 9, root["id"], "terminal"),
        _add_member(context, csrf, second_id, 10, middle["id"], "root"),
    ]
    assert all(response.status_code == 201 for response in mutations)

    first_edge = _create_edge(
        context, csrf, first_id, 11, root["id"], middle["id"]
    )
    second_edge = _create_edge(
        context, csrf, first_id, 12, root["id"], terminal["id"]
    )
    assert first_edge.status_code == second_edge.status_code == 201
    assert first_edge.json()["edge"]["parent_compound_id"] == root["id"]
    assert second_edge.json()["edge"]["parent_compound_id"] == root["id"]

    listing = context.client.get(f"/api/v2/workspaces/{workspace_id}/lineages")
    assert listing.status_code == 200
    assert listing.json()["workspace_version"] == 13
    assert [item["lineage_label"] for item in listing.json()["items"]] == [
        "Series A",
        "Series B",
    ]
    assert len(listing.json()["items"][0]["members"]) == 3
    assert len(listing.json()["items"][0]["edges"]) == 2
    assert listing.json()["items"][1]["members"][0]["role"] == "terminal"
    _assert_history(context, workspace_id, 13)


def test_lineage_rejects_cross_workspace_nonmember_self_and_duplicate_edges(
    science_api_context,
):
    context = science_api_context
    csrf = context.login("science.api.reviewer")
    root = _create_compound(context, csrf, context.first.workspace_id, 1, "B-1")
    child = _create_compound(context, csrf, context.first.workspace_id, 2, "B-2")

    other_csrf = context.login("science.api.other")
    foreign = _create_compound(
        context, other_csrf, context.second.workspace_id, 1, "FOREIGN"
    )
    csrf = context.login("science.api.reviewer")
    lineage_response = _create_lineage(
        context, csrf, context.first.workspace_id, 3, "Boundary Series"
    )
    assert lineage_response.status_code == 201
    lineage_id = lineage_response.json()["lineage"]["id"]
    root_member = _add_member(
        context, csrf, lineage_id, 4, root["id"], "root"
    )
    assert root_member.status_code == 201

    cross_workspace = _add_member(
        context, csrf, lineage_id, 5, foreign["id"], "terminal"
    )
    nonmember = _create_edge(
        context, csrf, lineage_id, 5, root["id"], child["id"]
    )
    self_edge = _create_edge(
        context, csrf, lineage_id, 5, root["id"], root["id"]
    )
    assert cross_workspace.status_code == 404
    assert nonmember.status_code == self_edge.status_code == 422

    child_member = _add_member(
        context, csrf, lineage_id, 5, child["id"], "terminal"
    )
    assert child_member.status_code == 201
    edge = _create_edge(
        context, csrf, lineage_id, 6, root["id"], child["id"]
    )
    assert edge.status_code == 201
    duplicate = _create_edge(
        context, csrf, lineage_id, 7, root["id"], child["id"]
    )
    referenced_member = context.client.request(
        "DELETE",
        f"/api/v2/lineage-members/{root_member.json()['member']['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": 7},
    )
    assert duplicate.status_code == 409
    assert referenced_member.status_code == 409
    _assert_history(context, context.first.workspace_id, 7)


def test_lineage_update_reorder_and_delete(science_api_context):
    context = science_api_context
    csrf = context.login("science.api.reviewer")
    workspace_id = context.first.workspace_id
    first = _create_lineage(context, csrf, workspace_id, 1, "First")
    second = _create_lineage(context, csrf, workspace_id, 2, "Second")
    assert first.status_code == second.status_code == 201
    first_id = first.json()["lineage"]["id"]
    second_id = second.json()["lineage"]["id"]

    updated = context.client.patch(
        f"/api/v2/lineages/{first_id}",
        headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": 3, "lineage_label": "First revised"},
    )
    reordered = context.client.put(
        f"/api/v2/workspaces/{workspace_id}/lineages/order",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": 4,
            "lineage_ids": [second_id, first_id],
        },
    )
    deleted = context.client.request(
        "DELETE",
        f"/api/v2/lineages/{first_id}",
        headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": 5},
    )
    assert updated.status_code == reordered.status_code == deleted.status_code == 200
    assert [item["id"] for item in reordered.json()["items"]] == [
        second_id,
        first_id,
    ]
    assert deleted.json()["workspace_version"] == 6
    _assert_history(context, workspace_id, 6)


def test_lineage_member_and_edge_update_reorder_and_delete(science_api_context):
    context = science_api_context
    csrf = context.login("science.api.reviewer")
    workspace_id = context.first.workspace_id
    root = _create_compound(context, csrf, workspace_id, 1, "M-1")
    first_child = _create_compound(context, csrf, workspace_id, 2, "M-2")
    second_child = _create_compound(context, csrf, workspace_id, 3, "M-3")
    lineage = _create_lineage(context, csrf, workspace_id, 4, "Editable Series")
    lineage_id = lineage.json()["lineage"]["id"]
    root_member = _add_member(context, csrf, lineage_id, 5, root["id"], "root")
    first_member = _add_member(
        context, csrf, lineage_id, 6, first_child["id"], "terminal"
    )
    second_member = _add_member(
        context, csrf, lineage_id, 7, second_child["id"], "terminal"
    )
    first_edge = _create_edge(
        context, csrf, lineage_id, 8, root["id"], first_child["id"]
    )
    second_edge = _create_edge(
        context, csrf, lineage_id, 9, root["id"], second_child["id"]
    )
    assert first_edge.status_code == second_edge.status_code == 201

    root_member_id = root_member.json()["member"]["id"]
    first_member_id = first_member.json()["member"]["id"]
    second_member_id = second_member.json()["member"]["id"]
    first_edge_id = first_edge.json()["edge"]["id"]
    second_edge_id = second_edge.json()["edge"]["id"]
    member_updated = context.client.patch(
        f"/api/v2/lineage-members/{first_member_id}",
        headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": 10, "role": "intermediate"},
    )
    members_reordered = context.client.put(
        f"/api/v2/lineages/{lineage_id}/members/order",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": 11,
            "member_ids": [second_member_id, first_member_id, root_member_id],
        },
    )
    edge_updated = context.client.patch(
        f"/api/v2/lineage-edges/{first_edge_id}",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": 12,
            "modification_summary": "Reviewed substituent optimization",
            "review_status": "reviewer_confirmed",
        },
    )
    edges_reordered = context.client.put(
        f"/api/v2/lineages/{lineage_id}/edges/order",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": 13,
            "edge_ids": [second_edge_id, first_edge_id],
        },
    )
    edge_deleted = context.client.request(
        "DELETE",
        f"/api/v2/lineage-edges/{second_edge_id}",
        headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": 14},
    )
    member_deleted = context.client.request(
        "DELETE",
        f"/api/v2/lineage-members/{second_member_id}",
        headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": 15},
    )

    assert all(
        response.status_code == 200
        for response in (
            member_updated,
            members_reordered,
            edge_updated,
            edges_reordered,
            edge_deleted,
            member_deleted,
        )
    )
    assert member_updated.json()["member"]["role"] == "intermediate"
    assert [item["id"] for item in members_reordered.json()["items"]] == [
        second_member_id,
        first_member_id,
        root_member_id,
    ]
    assert edge_updated.json()["edge"]["review_status"] == "reviewer_confirmed"
    assert [item["id"] for item in edges_reordered.json()["items"]] == [
        second_edge_id,
        first_edge_id,
    ]
    with context.session_factory() as session:
        assert session.get(LineageEdge, second_edge_id) is None
        assert session.get(LineageMember, second_member_id) is None
    _assert_history(context, workspace_id, 16)


def test_lineage_writes_enforce_assignment_role_state_csrf_and_version(
    science_api_context,
):
    context = science_api_context
    aggregate = context.first
    csrf = context.login("science.api.reviewer")
    created = _create_lineage(context, csrf, aggregate.workspace_id, 1, "Secured")
    lineage_id = created.json()["lineage"]["id"]

    stale = _create_lineage(context, csrf, aggregate.workspace_id, 1, "Stale")
    assert stale.status_code == 409
    assert stale.json()["code"] == "WORKSPACE_VERSION_CONFLICT"

    other_csrf = context.login("science.api.other")
    concealed = context.client.patch(
        f"/api/v2/lineages/{lineage_id}",
        headers={"X-CSRF-Token": other_csrf},
        json={"expected_workspace_version": 2, "lineage_label": "Leaked"},
    )
    assert concealed.status_code == 404

    admin_csrf = context.login("science.api.admin")
    admin_write = context.client.patch(
        f"/api/v2/lineages/{lineage_id}",
        headers={"X-CSRF-Token": admin_csrf},
        json={"expected_workspace_version": 2, "lineage_label": "Admin edit"},
    )
    assert admin_write.status_code == 403

    context.login("science.api.reviewer")
    missing_csrf = context.client.patch(
        f"/api/v2/lineages/{lineage_id}",
        json={"expected_workspace_version": 2, "lineage_label": "No CSRF"},
    )
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["code"] == "CSRF_VALIDATION_FAILED"

    with context.session_factory.begin() as session:
        workspace = session.get(PaperWorkspace, aggregate.workspace_id)
        assert workspace is not None
        workspace.state = WorkspaceState.SUBMITTED
    reviewer_csrf = context.login("science.api.reviewer")
    readonly = context.client.patch(
        f"/api/v2/lineages/{lineage_id}",
        headers={"X-CSRF-Token": reviewer_csrf},
        json={"expected_workspace_version": 2, "lineage_label": "Read only"},
    )
    assert readonly.status_code == 409
    assert readonly.json()["code"] == "WORKSPACE_READ_ONLY"
    _assert_history(context, aggregate.workspace_id, 2)


def test_lineage_type_persists_in_api_history_and_snapshot(science_api_context):
    from app.workspaces.snapshot import build_paper_snapshot, canonical_snapshot_hash
    context = science_api_context
    csrf = context.login("science.api.reviewer")
    workspace_id = context.first.workspace_id
    created = _create_lineage(context, csrf, workspace_id, 1, "Legacy")
    assert created.status_code == 201
    assert created.json()["lineage"]["lineage_type"] == "unspecified"
    lineage_id = created.json()["lineage"]["id"]
    with context.session_factory() as session:
        legacy = build_paper_snapshot(session, workspace_id)
        assert "lineage_type" not in legacy["lineages"][0]
    classified = context.client.patch(
        f"/api/v2/lineages/{lineage_id}", headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": 2, "lineage_type": "sar"},
    )
    assert classified.status_code == 200, classified.text
    assert classified.json()["lineage"]["lineage_type"] == "sar"
    with context.session_factory() as session:
        typed = build_paper_snapshot(session, workspace_id)
        assert typed["lineages"][0]["lineage_type"] == "sar"
        assert canonical_snapshot_hash(typed) != canonical_snapshot_hash(legacy)
        events = session.scalars(select(ChangeEvent).where(ChangeEvent.workspace_id == workspace_id)).all()
        update = next(event for event in events if event.action == "lineage.update")
        assert update.after_value["lineage_type"] == "sar"
    synthesis = context.client.post(
        f"/api/v2/workspaces/{workspace_id}/lineages", headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": 3, "lineage_label": "Synthesis", "lineage_type": "synthesis"},
    )
    assert synthesis.status_code == 201, synthesis.text
    listing = context.client.get(f"/api/v2/workspaces/{workspace_id}/lineages").json()
    assert [item["lineage_type"] for item in listing["items"]] == ["sar", "synthesis"]
