from __future__ import annotations

from sqlalchemy import func, select

from app.compounds.models import Compound
from app.evidence.models import EdgeEvidenceLink, Evidence, EvidenceKind
from app.lineages.models import (
    Lineage,
    LineageEdge,
    LineageEdgeReviewStatus,
    LineageMember,
    LineageMemberRole,
)
from app.workspaces.models import (
    ChangeActorKind,
    ChangeEvent,
    PaperWorkspace,
    WorkspaceState,
)


def _seed_edges(context):
    with context.session_factory.begin() as session:
        aggregate = context.first
        root = Compound(
            paper_id=aggregate.paper_id,
            workspace_id=aggregate.workspace_id,
            compound_label="E-1",
            sort_order=0,
            created_by_kind=ChangeActorKind.REVIEWER,
        )
        first_child = Compound(
            paper_id=aggregate.paper_id,
            workspace_id=aggregate.workspace_id,
            compound_label="E-2",
            sort_order=1,
            created_by_kind=ChangeActorKind.REVIEWER,
        )
        second_child = Compound(
            paper_id=aggregate.paper_id,
            workspace_id=aggregate.workspace_id,
            compound_label="E-3",
            sort_order=2,
            created_by_kind=ChangeActorKind.REVIEWER,
        )
        lineage = Lineage(
            paper_id=aggregate.paper_id,
            workspace_id=aggregate.workspace_id,
            lineage_label="Evidence Series",
            sort_order=0,
        )
        session.add_all([root, first_child, second_child, lineage])
        session.flush()
        session.add_all(
            [
                LineageMember(
                    paper_id=aggregate.paper_id,
                    workspace_id=aggregate.workspace_id,
                    lineage_id=lineage.id,
                    compound_id=compound.id,
                    role=role,
                    sort_order=order,
                )
                for order, (compound, role) in enumerate(
                    [
                        (root, LineageMemberRole.ROOT),
                        (first_child, LineageMemberRole.TERMINAL),
                        (second_child, LineageMemberRole.TERMINAL),
                    ]
                )
            ]
        )
        session.flush()
        edges = [
            LineageEdge(
                paper_id=aggregate.paper_id,
                workspace_id=aggregate.workspace_id,
                lineage_id=lineage.id,
                parent_compound_id=root.id,
                child_compound_id=child.id,
                relation_type="lead_optimization",
                review_status=LineageEdgeReviewStatus.DRAFT,
                sort_order=order,
            )
            for order, child in enumerate([first_child, second_child])
        ]
        session.add_all(edges)
        session.flush()
        return root.id, edges[0].id, edges[1].id


def _source_sha(context, paper_id):
    from app.catalog.models import PaperSource
    from app.papers.models import Paper

    with context.session_factory() as session:
        return session.scalar(
            select(PaperSource.sha256)
            .join(Paper, Paper.source_id == PaperSource.id)
            .where(Paper.id == paper_id)
        )


def _create_evidence(context, csrf: str, version: int):
    return context.client.post(
        f"/api/v2/workspaces/{context.first.workspace_id}/evidence",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": version,
            "kind": "scheme",
            "source_sha256": _source_sha(context, context.first.paper_id),
            "page_number": 2,
            "bbox": {"x0": "0.1", "y0": "0.2", "x1": "0.8", "y1": "0.9"},
            "quoted_text": "Compound E-1 was optimized to the E-2 and E-3 analogues.",
            "caption": "Scheme 2",
            "reviewer_note": "Direct optimization evidence",
        },
    )


def test_one_evidence_can_support_multiple_edges(science_api_context):
    context = science_api_context
    _, first_edge, second_edge = _seed_edges(context)
    csrf = context.login("science.api.reviewer")
    created = _create_evidence(context, csrf, 1)
    assert created.status_code == 201
    evidence = created.json()["evidence"]

    first_link = context.client.post(
        f"/api/v2/lineage-edges/{first_edge}/evidence-links",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": 2,
            "evidence_id": evidence["id"],
            "role": "supports",
        },
    )
    second_link = context.client.post(
        f"/api/v2/lineage-edges/{second_edge}/evidence-links",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": 3,
            "evidence_id": evidence["id"],
            "role": "contextual",
        },
    )
    assert first_link.status_code == second_link.status_code == 201

    listing = context.client.get(
        f"/api/v2/workspaces/{context.first.workspace_id}/evidence"
    )
    assert listing.status_code == 200
    assert listing.json()["workspace_version"] == 4
    assert listing.json()["items"] == [evidence]
    first_links = context.client.get(
        f"/api/v2/lineage-edges/{first_edge}/evidence-links"
    )
    second_links = context.client.get(
        f"/api/v2/lineage-edges/{second_edge}/evidence-links"
    )
    assert first_links.json()["items"][0]["evidence_id"] == evidence["id"]
    assert second_links.json()["items"][0]["role"] == "contextual"

    with context.session_factory() as session:
        event_count = session.scalar(
            select(func.count())
            .select_from(ChangeEvent)
            .where(ChangeEvent.workspace_id == context.first.workspace_id)
        )
        assert event_count == 3


def test_evidence_validates_locator_scope_precision_and_referenced_delete(
    science_api_context,
):
    context = science_api_context
    _, edge_id, _ = _seed_edges(context)
    csrf = context.login("science.api.reviewer")
    wrong_source = _source_sha(context, context.second.paper_id)
    invalid_source = context.client.post(
        f"/api/v2/workspaces/{context.first.workspace_id}/evidence",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": 1,
            "kind": "text",
            "source_sha256": wrong_source,
            "page_number": 1,
            "quoted_text": "Wrong Paper",
        },
    )
    invalid_page = context.client.post(
        f"/api/v2/workspaces/{context.first.workspace_id}/evidence",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": 1,
            "kind": "text",
            "source_sha256": _source_sha(context, context.first.paper_id),
            "page_number": 99,
            "quoted_text": "Wrong page",
        },
    )
    invalid_precision = context.client.post(
        f"/api/v2/workspaces/{context.first.workspace_id}/evidence",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": 1,
            "kind": "image",
            "source_sha256": _source_sha(context, context.first.paper_id),
            "page_number": 1,
            "bbox": {"x0": "0.000000000001", "y0": 0, "x1": 0.5, "y1": 0.5},
        },
    )
    assert invalid_source.status_code == invalid_page.status_code == 422
    assert invalid_precision.status_code == 422

    created = _create_evidence(context, csrf, 1)
    evidence_id = created.json()["evidence"]["id"]
    linked = context.client.post(
        f"/api/v2/lineage-edges/{edge_id}/evidence-links",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": 2,
            "evidence_id": evidence_id,
            "role": "supports",
        },
    )
    assert linked.status_code == 201
    duplicate = context.client.post(
        f"/api/v2/lineage-edges/{edge_id}/evidence-links",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": 3,
            "evidence_id": evidence_id,
            "role": "supports",
        },
    )
    deletion = context.client.request(
        "DELETE",
        f"/api/v2/evidence/{evidence_id}",
        headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": 3},
    )
    assert duplicate.status_code == 409
    assert deletion.status_code == 409


def test_evidence_create_and_update_require_scientific_content(science_api_context):
    context = science_api_context
    csrf = context.login("science.api.reviewer")
    source_sha = _source_sha(context, context.first.paper_id)
    empty_create = context.client.post(
        f"/api/v2/workspaces/{context.first.workspace_id}/evidence",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": 1,
            "kind": "text",
            "source_sha256": source_sha,
            "page_number": 1,
            "bbox": None,
            "quoted_text": "  ",
            "caption": None,
            "reviewer_note": "A note is not scientific Evidence content",
        },
    )
    assert empty_create.status_code == 422
    assert empty_create.json()["code"] == "EVIDENCE_INVALID"

    created = _create_evidence(context, csrf, 1)
    evidence_id = created.json()["evidence"]["id"]
    empty_update = context.client.patch(
        f"/api/v2/evidence/{evidence_id}",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": 2,
            "bbox": None,
            "quoted_text": None,
            "caption": " ",
        },
    )
    assert empty_update.status_code == 422
    assert empty_update.json()["code"] == "EVIDENCE_INVALID"

    listing = context.client.get(
        f"/api/v2/workspaces/{context.first.workspace_id}/evidence"
    )
    assert listing.json()["workspace_version"] == 2
    assert listing.json()["items"][0]["quoted_text"]


def test_evidence_update_link_update_and_delete(science_api_context):
    context = science_api_context
    _, edge_id, _ = _seed_edges(context)
    csrf = context.login("science.api.reviewer")
    created = _create_evidence(context, csrf, 1)
    evidence_id = created.json()["evidence"]["id"]
    linked = context.client.post(
        f"/api/v2/lineage-edges/{edge_id}/evidence-links",
        headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": 2, "evidence_id": evidence_id, "role": "supports"},
    )
    link_id = linked.json()["link"]["id"]
    updated = context.client.patch(
        f"/api/v2/evidence/{evidence_id}",
        headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": 3, "caption": "Scheme 2 revised"},
    )
    link_updated = context.client.patch(
        f"/api/v2/edge-evidence-links/{link_id}",
        headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": 4, "role": "contextual"},
    )
    link_deleted = context.client.request(
        "DELETE",
        f"/api/v2/edge-evidence-links/{link_id}",
        headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": 5},
    )
    evidence_deleted = context.client.request(
        "DELETE",
        f"/api/v2/evidence/{evidence_id}",
        headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": 6},
    )
    assert updated.status_code == link_updated.status_code == 200
    assert link_deleted.status_code == evidence_deleted.status_code == 200
    assert evidence_deleted.json()["workspace_version"] == 7


def test_evidence_link_rejects_cross_workspace_evidence(science_api_context):
    context = science_api_context
    _, edge_id, _ = _seed_edges(context)
    foreign_sha = _source_sha(context, context.second.paper_id)
    with context.session_factory.begin() as session:
        foreign_evidence = Evidence(
            paper_id=context.second.paper_id,
            workspace_id=context.second.workspace_id,
            kind=EvidenceKind.TEXT,
            source_sha256=foreign_sha,
            page_number=1,
            quoted_text="Foreign evidence",
        )
        session.add(foreign_evidence)
        session.flush()
        foreign_evidence_id = foreign_evidence.id

    csrf = context.login("science.api.reviewer")
    response = context.client.post(
        f"/api/v2/lineage-edges/{edge_id}/evidence-links",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": 1,
            "evidence_id": str(foreign_evidence_id),
            "role": "supports",
        },
    )
    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"
    with context.session_factory() as session:
        workspace = session.get(PaperWorkspace, context.first.workspace_id)
        event_count = session.scalar(
            select(func.count())
            .select_from(ChangeEvent)
            .where(ChangeEvent.workspace_id == context.first.workspace_id)
        )
        assert workspace is not None and workspace.version == 1
        assert event_count == 0


def test_lineage_delete_cascades_records_and_snapshots_evidence_links(
    science_api_context,
):
    context = science_api_context
    _, edge_id, _ = _seed_edges(context)
    with context.session_factory() as session:
        edge = session.get(LineageEdge, edge_id)
        assert edge is not None
        lineage_id = edge.lineage_id

    csrf = context.login("science.api.reviewer")
    created = _create_evidence(context, csrf, 1)
    evidence_id = created.json()["evidence"]["id"]
    linked = context.client.post(
        f"/api/v2/lineage-edges/{edge_id}/evidence-links",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": 2,
            "evidence_id": evidence_id,
            "role": "supports",
        },
    )
    assert linked.status_code == 201
    link_id = linked.json()["link"]["id"]
    deleted = context.client.request(
        "DELETE",
        f"/api/v2/lineages/{lineage_id}",
        headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": 3},
    )
    assert deleted.status_code == 200
    assert deleted.json()["workspace_version"] == 4

    with context.session_factory() as session:
        deletion_event = session.scalar(
            select(ChangeEvent).where(
                ChangeEvent.workspace_id == context.first.workspace_id,
                ChangeEvent.entity_id == lineage_id,
                ChangeEvent.action == "lineage.delete",
            )
        )
        assert session.get(Lineage, lineage_id) is None
        assert session.scalar(
            select(func.count())
            .select_from(LineageMember)
            .where(LineageMember.lineage_id == lineage_id)
        ) == 0
        assert session.scalar(
            select(func.count())
            .select_from(LineageEdge)
            .where(LineageEdge.lineage_id == lineage_id)
        ) == 0
        assert session.get(EdgeEvidenceLink, link_id) is None
        assert session.get(Evidence, evidence_id) is not None
        assert deletion_event is not None
        assert deletion_event.before_value["evidence_links"] == [
            {
                "id": link_id,
                "paper_id": str(context.first.paper_id),
                "workspace_id": str(context.first.workspace_id),
                "edge_id": str(edge_id),
                "evidence_id": evidence_id,
                "role": "supports",
            }
        ]


def test_evidence_writes_enforce_assignment_role_state_csrf_and_version(
    science_api_context,
):
    context = science_api_context
    aggregate = context.first
    _seed_edges(context)
    csrf = context.login("science.api.reviewer")
    created = _create_evidence(context, csrf, 1)
    evidence_id = created.json()["evidence"]["id"]

    stale = _create_evidence(context, csrf, 1)
    assert stale.status_code == 409
    assert stale.json()["code"] == "WORKSPACE_VERSION_CONFLICT"

    other_csrf = context.login("science.api.other")
    concealed = context.client.patch(
        f"/api/v2/evidence/{evidence_id}",
        headers={"X-CSRF-Token": other_csrf},
        json={"expected_workspace_version": 2, "caption": "Leaked"},
    )
    assert concealed.status_code == 404

    admin_csrf = context.login("science.api.admin")
    admin_write = context.client.patch(
        f"/api/v2/evidence/{evidence_id}",
        headers={"X-CSRF-Token": admin_csrf},
        json={"expected_workspace_version": 2, "caption": "Admin edit"},
    )
    assert admin_write.status_code == 403

    context.login("science.api.reviewer")
    missing_csrf = context.client.patch(
        f"/api/v2/evidence/{evidence_id}",
        json={"expected_workspace_version": 2, "caption": "No CSRF"},
    )
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["code"] == "CSRF_VALIDATION_FAILED"

    with context.session_factory.begin() as session:
        workspace = session.get(PaperWorkspace, aggregate.workspace_id)
        assert workspace is not None
        workspace.state = WorkspaceState.SUBMITTED
    reviewer_csrf = context.login("science.api.reviewer")
    readonly = context.client.patch(
        f"/api/v2/evidence/{evidence_id}",
        headers={"X-CSRF-Token": reviewer_csrf},
        json={"expected_workspace_version": 2, "caption": "Read only"},
    )
    assert readonly.status_code == 409
    assert readonly.json()["code"] == "WORKSPACE_READ_ONLY"
    with context.session_factory() as session:
        evidence = session.get(Evidence, evidence_id)
        workspace = session.get(PaperWorkspace, aggregate.workspace_id)
        event_count = session.scalar(
            select(func.count())
            .select_from(ChangeEvent)
            .where(ChangeEvent.workspace_id == aggregate.workspace_id)
        )
        assert evidence is not None and evidence.caption == "Scheme 2"
        assert workspace is not None and workspace.version == 2
        assert event_count == 1
