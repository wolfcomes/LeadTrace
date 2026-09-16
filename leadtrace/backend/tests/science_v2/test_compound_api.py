from __future__ import annotations

from uuid import uuid4

from sqlalchemy import func, select

from app.activities.models import Activity, ActivityOperator
from app.compounds.models import Compound
from app.lineages.models import Lineage, LineageMember, LineageMemberRole
from app.structures.models import Structure, StructureInputMethod, StructureStatus
from app.workspaces.models import ChangeEvent, PaperWorkspace, WorkspaceState


def _create_compound(
    science_api_context,
    csrf: str,
    *,
    version: int,
    label: str,
    display_name: str | None = None,
):
    response = science_api_context.client.post(
        f"/api/v2/workspaces/{science_api_context.first.workspace_id}/compounds",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": version,
            "compound_label": label,
            "display_name": display_name,
            "description": None,
        },
    )
    assert response.status_code == 201
    return response


def test_compound_crud_reorder_and_delete_preserve_one_event_per_change(
    science_api_context,
) -> None:
    csrf = science_api_context.login("science.api.reviewer")
    workspace_id = science_api_context.first.workspace_id

    empty = science_api_context.client.get(
        f"/api/v2/workspaces/{workspace_id}/compounds"
    )
    assert empty.status_code == 200
    assert empty.json() == {
        "workspace_id": str(workspace_id),
        "workspace_version": 1,
        "items": [],
        "total": 0,
    }

    first = _create_compound(
        science_api_context,
        csrf,
        version=1,
        label="26a",
        display_name="Lead 26a",
    )
    second = _create_compound(
        science_api_context,
        csrf,
        version=2,
        label="26b",
        display_name="Lead 26b",
    )
    first_id = first.json()["compound"]["id"]
    second_id = second.json()["compound"]["id"]
    assert first.json()["workspace_version"] == 2
    assert first.json()["compound"]["sort_order"] == 0
    assert second.json()["workspace_version"] == 3
    assert second.json()["compound"]["sort_order"] == 1

    updated = science_api_context.client.patch(
        f"/api/v2/compounds/{first_id}",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": 3,
            "compound_label": "26a",
            "display_name": "Optimized lead 26a",
            "description": "Primary series lead",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["workspace_version"] == 4
    assert updated.json()["compound"]["description"] == "Primary series lead"

    identical = science_api_context.client.patch(
        f"/api/v2/compounds/{first_id}",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": 4,
            "compound_label": "26a",
            "display_name": "Optimized lead 26a",
            "description": "Primary series lead",
        },
    )
    assert identical.status_code == 200
    assert identical.json()["workspace_version"] == 4

    reordered = science_api_context.client.put(
        f"/api/v2/workspaces/{workspace_id}/compounds/order",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": 4,
            "compound_ids": [second_id, first_id],
        },
    )
    assert reordered.status_code == 200
    assert reordered.json()["workspace_version"] == 5
    assert [item["id"] for item in reordered.json()["items"]] == [
        second_id,
        first_id,
    ]
    assert [item["sort_order"] for item in reordered.json()["items"]] == [0, 1]

    with science_api_context.session_factory.begin() as session:
        second_row = session.get(Compound, second_id)
        assert second_row is not None
        session.add(
            Structure(
                paper_id=second_row.paper_id,
                workspace_id=second_row.workspace_id,
                compound_id=second_row.id,
                smiles="CCO",
                canonical_smiles="CCO",
                molfile=None,
                inchi="InChI=1S/C2H6O/c1-2-3/h3H,2H2,1H3",
                inchikey="LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
                depiction_asset_id=None,
                status=StructureStatus.DRAFT,
                input_method=StructureInputMethod.MANUAL_SMILES,
            )
        )

    deleted = science_api_context.client.request(
        "DELETE",
        f"/api/v2/compounds/{second_id}",
        headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": 5},
    )
    assert deleted.status_code == 200
    assert deleted.json() == {
        "deleted_compound_id": second_id,
        "workspace_version": 6,
    }

    listing = science_api_context.client.get(
        f"/api/v2/workspaces/{workspace_id}/compounds"
    )
    assert listing.status_code == 200
    assert listing.json()["workspace_version"] == 6
    assert [item["id"] for item in listing.json()["items"]] == [first_id]

    with science_api_context.session_factory() as session:
        workspace = session.get(PaperWorkspace, workspace_id)
        events = list(
            session.scalars(
                select(ChangeEvent)
                .where(ChangeEvent.workspace_id == workspace_id)
                .order_by(ChangeEvent.occurred_at, ChangeEvent.id)
            )
        )
        assert workspace is not None
        assert workspace.version == 6
        assert [event.action for event in events] == [
            "compound.create",
            "compound.create",
            "compound.update",
            "compound.reorder",
            "compound.delete",
        ]
        assert events[2].before_value["display_name"] == "Lead 26a"
        assert events[2].after_value["display_name"] == "Optimized lead 26a"
        deleted_snapshot = events[-1].before_value
        assert deleted_snapshot is not None
        assert deleted_snapshot["compound"]["compound_label"] == "26b"
        assert deleted_snapshot["structure"]["smiles"] == "CCO"
        assert events[-1].after_value is None
        assert session.get(Compound, second_id) is None


def test_reorder_requires_the_complete_unique_workspace_compound_set(
    science_api_context,
) -> None:
    csrf = science_api_context.login("science.api.reviewer")
    workspace_id = science_api_context.first.workspace_id
    first = _create_compound(
        science_api_context, csrf, version=1, label="A"
    ).json()["compound"]["id"]
    second = _create_compound(
        science_api_context, csrf, version=2, label="B"
    ).json()["compound"]["id"]

    invalid_orders = [
        [first],
        [first, first],
        [first, second, str(uuid4())],
    ]
    for compound_ids in invalid_orders:
        response = science_api_context.client.put(
            f"/api/v2/workspaces/{workspace_id}/compounds/order",
            headers={"X-CSRF-Token": csrf},
            json={
                "expected_workspace_version": 3,
                "compound_ids": compound_ids,
            },
        )
        assert response.status_code == 422
        assert response.json()["code"] == "COMPOUND_ORDER_INVALID"

    with science_api_context.session_factory() as session:
        workspace = session.get(PaperWorkspace, workspace_id)
        event_count = session.scalar(
            select(func.count())
            .select_from(ChangeEvent)
            .where(ChangeEvent.workspace_id == workspace_id)
        )
        assert workspace is not None
        assert workspace.version == 3
        assert event_count == 2


def test_delete_referenced_compound_returns_only_safe_reference_counts(
    science_api_context,
) -> None:
    csrf = science_api_context.login("science.api.reviewer")
    aggregate = science_api_context.first
    created = _create_compound(
        science_api_context, csrf, version=1, label="linked"
    )
    compound_id = created.json()["compound"]["id"]

    with science_api_context.session_factory.begin() as session:
        lineage = Lineage(
            paper_id=aggregate.paper_id,
            workspace_id=aggregate.workspace_id,
            lineage_label="Series A",
            description=None,
            sort_order=0,
        )
        session.add(lineage)
        session.flush()
        session.add_all(
            [
                LineageMember(
                    paper_id=aggregate.paper_id,
                    workspace_id=aggregate.workspace_id,
                    lineage_id=lineage.id,
                    compound_id=compound_id,
                    role=LineageMemberRole.ROOT,
                    sort_order=0,
                ),
                Activity(
                    paper_id=aggregate.paper_id,
                    workspace_id=aggregate.workspace_id,
                    compound_id=compound_id,
                    evidence_id=None,
                    assay_name="Cell potency",
                    metric="IC50",
                    operator=ActivityOperator.EQUAL,
                    value=10,
                    unit="nM",
                    context=None,
                    sort_order=0,
                ),
            ]
        )

    response = science_api_context.client.request(
        "DELETE",
        f"/api/v2/compounds/{compound_id}",
        headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": 2},
    )
    assert response.status_code == 409
    assert response.json() == {
        "code": "COMPOUND_REFERENCED",
        "message": "Compound is referenced by scientific records",
        "details": {
            "lineage_references": 1,
            "activity_references": 1,
        },
        "request_id": response.headers["X-Request-ID"],
    }
    assert "lineage_members" not in response.text
    assert "activities" not in response.text

    with science_api_context.session_factory() as session:
        workspace = session.get(PaperWorkspace, aggregate.workspace_id)
        event_count = session.scalar(
            select(func.count())
            .select_from(ChangeEvent)
            .where(ChangeEvent.workspace_id == aggregate.workspace_id)
        )
        assert workspace is not None
        assert workspace.version == 2
        assert event_count == 1
        assert session.get(Compound, compound_id) is not None


def test_compound_writes_enforce_assignment_role_state_csrf_and_version(
    science_api_context,
) -> None:
    csrf = science_api_context.login("science.api.reviewer")
    aggregate = science_api_context.first
    created = _create_compound(
        science_api_context, csrf, version=1, label="secured"
    )
    compound_id = created.json()["compound"]["id"]

    stale = science_api_context.client.post(
        f"/api/v2/workspaces/{aggregate.workspace_id}/compounds",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": 1,
            "compound_label": "stale",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "WORKSPACE_VERSION_CONFLICT"
    assert stale.json()["details"] == {
        "expected_workspace_version": 1,
        "current_workspace_version": 2,
    }

    other_csrf = science_api_context.login("science.api.other")
    concealed = science_api_context.client.patch(
        f"/api/v2/compounds/{compound_id}",
        headers={"X-CSRF-Token": other_csrf},
        json={
            "expected_workspace_version": 2,
            "compound_label": "leaked",
        },
    )
    assert concealed.status_code == 404
    assert concealed.json()["message"] == "Resource not found"

    admin_csrf = science_api_context.login("science.api.admin")
    admin_write = science_api_context.client.patch(
        f"/api/v2/compounds/{compound_id}",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "expected_workspace_version": 2,
            "compound_label": "admin-edit",
        },
    )
    assert admin_write.status_code == 403

    science_api_context.login("science.api.reviewer")
    missing_csrf = science_api_context.client.patch(
        f"/api/v2/compounds/{compound_id}",
        json={
            "expected_workspace_version": 2,
            "compound_label": "no-csrf",
        },
    )
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["code"] == "CSRF_VALIDATION_FAILED"

    with science_api_context.session_factory.begin() as session:
        workspace = session.get(PaperWorkspace, aggregate.workspace_id)
        assert workspace is not None
        workspace.state = WorkspaceState.SUBMITTED

    reviewer_csrf = science_api_context.login("science.api.reviewer")
    readonly = science_api_context.client.patch(
        f"/api/v2/compounds/{compound_id}",
        headers={"X-CSRF-Token": reviewer_csrf},
        json={
            "expected_workspace_version": 2,
            "compound_label": "read-only",
        },
    )
    assert readonly.status_code == 409
    assert readonly.json()["code"] == "WORKSPACE_READ_ONLY"

    with science_api_context.session_factory() as session:
        compound = session.get(Compound, compound_id)
        workspace = session.get(PaperWorkspace, aggregate.workspace_id)
        event_count = session.scalar(
            select(func.count())
            .select_from(ChangeEvent)
            .where(ChangeEvent.workspace_id == aggregate.workspace_id)
        )
        assert compound is not None
        assert workspace is not None
        assert compound.compound_label == "secured"
        assert workspace.version == 2
        assert event_count == 1
