from __future__ import annotations

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.compounds.models import Compound
from app.evidence.models import Evidence, EvidenceKind, EdgeEvidenceLink, EvidenceRole
from app.lineages.models import Lineage, LineageEdge, LineageEdgeReviewStatus, LineageMember, LineageMemberRole
from app.structures.models import Structure, StructureInputMethod, StructureStatus
from app.workspaces.models import (
    ChangeEvent,
    PaperSection,
    PaperSectionReview,
    PaperSectionState,
    PaperSubmission,
    PaperWorkspace,
    ReviewTask,
    ReviewTaskState,
    WorkspaceState,
)
from app.workspaces.submission import SubmissionService


def _complete_sections(session, fixture, *, not_reported: set[PaperSection] | None = None):
    not_reported = not_reported or set()
    rows = list(
        session.scalars(
            select(PaperSectionReview).where(
                PaperSectionReview.workspace_id == fixture.workspace_id
            )
        )
    )
    for row in rows:
        row.state = (
            PaperSectionState.NOT_REPORTED
            if row.section_key in not_reported
            else PaperSectionState.COMPLETED
        )


def _add_confirmed_structure(session, fixture, compound):
    session.add(
        Structure(
            paper_id=fixture.paper_id,
            workspace_id=fixture.workspace_id,
            compound_id=compound.id,
            smiles="CCO",
            canonical_smiles="CCO",
            molfile="molfile",
            inchi="InChI=1S/C2H6O/c1-2-3/h3H,2H2,1H3",
            inchikey="LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
            status=StructureStatus.REVIEWER_CONFIRMED,
            input_method=StructureInputMethod.MANUAL_SMILES,
        )
    )


def _add_supported_edge(session, fixture, compound, *, with_evidence: bool = False):
    child = Compound(
        paper_id=fixture.paper_id,
        workspace_id=fixture.workspace_id,
        compound_label="SUB-2",
        sort_order=1,
        created_by_kind="reviewer",
    )
    session.add(child)
    session.flush()
    _add_confirmed_structure(session, fixture, compound)
    _add_confirmed_structure(session, fixture, child)
    lineage = Lineage(
        paper_id=fixture.paper_id,
        workspace_id=fixture.workspace_id,
        lineage_label="Series A",
        sort_order=0,
    )
    session.add(lineage)
    session.flush()
    session.add_all(
        [
            LineageMember(
                paper_id=fixture.paper_id,
                workspace_id=fixture.workspace_id,
                lineage_id=lineage.id,
                compound_id=compound.id,
                role=LineageMemberRole.ROOT,
                sort_order=0,
            ),
            LineageMember(
                paper_id=fixture.paper_id,
                workspace_id=fixture.workspace_id,
                lineage_id=lineage.id,
                compound_id=child.id,
                role=LineageMemberRole.TERMINAL,
                sort_order=1,
            ),
        ]
    )
    session.flush()
    edge = LineageEdge(
        paper_id=fixture.paper_id,
        workspace_id=fixture.workspace_id,
        lineage_id=lineage.id,
        parent_compound_id=compound.id,
        child_compound_id=child.id,
        relation_type="lead_optimization",
        review_status=LineageEdgeReviewStatus.REVIEWER_CONFIRMED,
        sort_order=0,
    )
    session.add(edge)
    session.flush()
    if with_evidence:
        evidence = Evidence(
            paper_id=fixture.paper_id,
            workspace_id=fixture.workspace_id,
            kind=EvidenceKind.TEXT,
            source_sha256="a" * 64,
            page_number=1,
            quoted_text="lead optimization evidence",
        )
        session.add(evidence)
        session.flush()
        session.add(
            EdgeEvidenceLink(
                paper_id=fixture.paper_id,
                workspace_id=fixture.workspace_id,
                edge_id=edge.id,
                evidence_id=evidence.id,
                role=EvidenceRole.SUPPORTS,
            )
        )
        session.flush()
    return edge


def test_submission_reports_record_addressable_pending_and_scientific_blockers(
    workspace_fixture,
):
    fixture = workspace_fixture
    service = SubmissionService()
    with fixture.session_factory.begin() as session:
        result = service.validate(session, workspace_id=fixture.workspace_id)
        codes = {item.code for item in result.blockers}
        assert "SECTION_PENDING" in codes
        assert all(item.entity_type == "paper_section_review" for item in result.blockers)

        _complete_sections(session, fixture)
        compound = Compound(
            paper_id=fixture.paper_id,
            workspace_id=fixture.workspace_id,
            compound_label="SUB-1",
            sort_order=0,
            created_by_kind="reviewer",
        )
        session.add(compound)
        session.flush()
        result = service.validate(session, workspace_id=fixture.workspace_id)
        assert any(item.code == "STRUCTURE_NOT_CONFIRMED" for item in result.blockers)
        structure = Structure(
            paper_id=fixture.paper_id,
            workspace_id=fixture.workspace_id,
            compound_id=compound.id,
            smiles="CCO",
            canonical_smiles="   ",
            status=StructureStatus.REVIEWER_CONFIRMED,
            input_method=StructureInputMethod.MANUAL_SMILES,
        )
        session.add(structure)
        session.flush()
        result = service.validate(session, workspace_id=fixture.workspace_id)
        assert any(item.code == "STRUCTURE_NOT_CONFIRMED" for item in result.blockers)


def test_submission_allows_explicit_unresolved_and_not_reported_and_is_idempotent(
    workspace_fixture,
):
    fixture = workspace_fixture
    service = SubmissionService()
    with fixture.session_factory.begin() as session:
        _complete_sections(
            session,
            fixture,
            not_reported={PaperSection.ACTIVITIES},
        )
        compound = Compound(
            paper_id=fixture.paper_id,
            workspace_id=fixture.workspace_id,
            compound_label="SUB-1",
            sort_order=0,
            created_by_kind="reviewer",
        )
        session.add(compound)
        session.flush()
        _add_supported_edge(session, fixture, compound, with_evidence=True)
        submission = service.submit(
            session,
            workspace_id=fixture.workspace_id,
            reviewer_id=fixture.reviewer_id,
            expected_workspace_version=1,
            idempotency_key="submit-1",
            reviewer_note="Ready for admin review",
        )
        assert submission.submission_number == 1
        assert submission.workspace_version == 2
        assert len(submission.content_hash) == 64
        assert session.get(PaperWorkspace, fixture.workspace_id).state is WorkspaceState.SUBMITTED
        assert session.get(ReviewTask, fixture.task_id).status is ReviewTaskState.SUBMITTED

        repeated = service.submit(
            session,
            workspace_id=fixture.workspace_id,
            reviewer_id=fixture.reviewer_id,
            expected_workspace_version=1,
            idempotency_key="submit-1",
            reviewer_note="Different note must be ignored",
        )
        assert repeated.id == submission.id
        assert repeated.submission_number == 1
        assert session.scalar(select(func.count()).select_from(PaperSubmission)) == 1
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == 1


def test_submission_rejects_confirmed_edge_without_supporting_evidence(
    workspace_fixture,
):
    fixture = workspace_fixture
    service = SubmissionService()
    with fixture.session_factory.begin() as session:
        _complete_sections(session, fixture)
        compound = Compound(
            paper_id=fixture.paper_id,
            workspace_id=fixture.workspace_id,
            compound_label="SUB-1",
            sort_order=0,
            created_by_kind="reviewer",
        )
        session.add(compound)
        session.flush()
        edge = _add_supported_edge(session, fixture, compound)
        edge.review_status = LineageEdgeReviewStatus.REVIEWER_CONFIRMED
        result = service.validate(session, workspace_id=fixture.workspace_id)
        assert any(item.code == "EDGE_SUPPORTING_EVIDENCE_REQUIRED" for item in result.blockers)


def test_submission_rejects_empty_supporting_evidence(workspace_fixture):
    fixture = workspace_fixture
    service = SubmissionService()
    with fixture.session_factory.begin() as session:
        _complete_sections(session, fixture)
        compound = Compound(
            paper_id=fixture.paper_id,
            workspace_id=fixture.workspace_id,
            compound_label="SUB-1",
            sort_order=0,
            created_by_kind="reviewer",
        )
        session.add(compound)
        session.flush()
        edge = _add_supported_edge(session, fixture, compound)
        evidence = Evidence(
            paper_id=fixture.paper_id,
            workspace_id=fixture.workspace_id,
            kind=EvidenceKind.TEXT,
            source_sha256="a" * 64,
            page_number=1,
            quoted_text=None,
            caption=None,
        )
        session.add(evidence)
        session.flush()
        session.add(
            EdgeEvidenceLink(
                paper_id=fixture.paper_id,
                workspace_id=fixture.workspace_id,
                edge_id=edge.id,
                evidence_id=evidence.id,
                role=EvidenceRole.SUPPORTS,
            )
        )
        session.flush()

        result = service.validate(session, workspace_id=fixture.workspace_id)

        assert any(
            item.code == "EDGE_SUPPORTING_EVIDENCE_REQUIRED"
            and item.entity_id == edge.id
            for item in result.blockers
        )


def test_submission_requires_edge_disposition_but_allows_explicit_unresolved(
    workspace_fixture,
):
    fixture = workspace_fixture
    service = SubmissionService()
    with fixture.session_factory.begin() as session:
        _complete_sections(session, fixture)
        compound = Compound(
            paper_id=fixture.paper_id,
            workspace_id=fixture.workspace_id,
            compound_label="SUB-1",
            sort_order=0,
            created_by_kind="reviewer",
        )
        session.add(compound)
        session.flush()
        edge = _add_supported_edge(session, fixture, compound)
        edge.review_status = LineageEdgeReviewStatus.DRAFT
        result = service.validate(session, workspace_id=fixture.workspace_id)
        assert any(item.code == "EDGE_NOT_DISPOSITIONED" for item in result.blockers)

        edge.review_status = LineageEdgeReviewStatus.UNRESOLVED
        result = service.validate(session, workspace_id=fixture.workspace_id)
        assert result.valid


@pytest.mark.parametrize(
    "status",
    [StructureStatus.UNRESOLVED, StructureStatus.NOT_REPORTED],
)
def test_submission_allows_explicit_non_structural_dispositions(
    workspace_fixture,
    status,
):
    fixture = workspace_fixture
    service = SubmissionService()
    with fixture.session_factory.begin() as session:
        _complete_sections(session, fixture)
        compound = Compound(
            paper_id=fixture.paper_id,
            workspace_id=fixture.workspace_id,
            compound_label="SUB-1",
            sort_order=0,
            created_by_kind="reviewer",
        )
        session.add(compound)
        session.flush()
        session.add(
            Structure(
                paper_id=fixture.paper_id,
                workspace_id=fixture.workspace_id,
                compound_id=compound.id,
                status=status,
                input_method=StructureInputMethod.AI_PREFILL,
            )
        )
        session.flush()
        assert service.validate(session, workspace_id=fixture.workspace_id).valid


def test_structures_section_not_reported_does_not_bypass_compound_disposition(
    workspace_fixture,
):
    fixture = workspace_fixture
    service = SubmissionService()
    with fixture.session_factory.begin() as session:
        _complete_sections(
            session,
            fixture,
            not_reported={PaperSection.STRUCTURES},
        )
        compound = Compound(
            paper_id=fixture.paper_id,
            workspace_id=fixture.workspace_id,
            compound_label="SUB-1",
            sort_order=0,
            created_by_kind="reviewer",
        )
        session.add(compound)
        session.flush()
        blockers = service.validate(
            session, workspace_id=fixture.workspace_id
        ).blockers
        assert any(
            blocker.code == "STRUCTURE_NOT_CONFIRMED"
            and blocker.entity_id == compound.id
            for blocker in blockers
        )


def test_submission_requires_lineage_roots_and_terminals(workspace_fixture):
    fixture = workspace_fixture
    service = SubmissionService()
    with fixture.session_factory.begin() as session:
        _complete_sections(session, fixture)
        lineage = Lineage(
            paper_id=fixture.paper_id,
            workspace_id=fixture.workspace_id,
            lineage_label="Undispositioned series",
            sort_order=0,
        )
        session.add(lineage)
        session.flush()
        codes = {
            blocker.code
            for blocker in service.validate(
                session, workspace_id=fixture.workspace_id
            ).blockers
        }
        assert {"LINEAGE_ROOT_REQUIRED", "LINEAGE_TERMINAL_REQUIRED"} <= codes


def test_submission_allows_multiple_roots_terminals_and_branching(workspace_fixture):
    fixture = workspace_fixture
    service = SubmissionService()
    with fixture.session_factory.begin() as session:
        _complete_sections(session, fixture)
        compounds = [
            Compound(
                paper_id=fixture.paper_id,
                workspace_id=fixture.workspace_id,
                compound_label=label,
                sort_order=order,
                created_by_kind="reviewer",
            )
            for order, label in enumerate(("R1", "R2", "T1", "T2"))
        ]
        session.add_all(compounds)
        session.flush()
        for compound in compounds:
            _add_confirmed_structure(session, fixture, compound)
        lineage = Lineage(
            paper_id=fixture.paper_id,
            workspace_id=fixture.workspace_id,
            lineage_label="Branched series",
            sort_order=0,
        )
        session.add(lineage)
        session.flush()
        roles = (
            LineageMemberRole.ROOT,
            LineageMemberRole.ROOT,
            LineageMemberRole.TERMINAL,
            LineageMemberRole.TERMINAL,
        )
        session.add_all(
            [
                LineageMember(
                    paper_id=fixture.paper_id,
                    workspace_id=fixture.workspace_id,
                    lineage_id=lineage.id,
                    compound_id=compound.id,
                    role=role,
                    sort_order=order,
                )
                for order, (compound, role) in enumerate(zip(compounds, roles))
            ]
        )
        session.flush()
        session.add_all(
            [
                LineageEdge(
                    paper_id=fixture.paper_id,
                    workspace_id=fixture.workspace_id,
                    lineage_id=lineage.id,
                    parent_compound_id=compounds[parent].id,
                    child_compound_id=compounds[child].id,
                    relation_type="lead_optimization",
                    review_status=LineageEdgeReviewStatus.UNRESOLVED,
                    sort_order=order,
                )
                for order, (parent, child) in enumerate(((0, 2), (0, 3), (1, 2)))
            ]
        )
        session.flush()
        assert service.validate(session, workspace_id=fixture.workspace_id).valid


def test_submission_api_enforces_csrf_assignment_version_and_blockers(
    workspace_fixture,
):
    fixture = workspace_fixture
    url = f"/api/v2/workspaces/{fixture.workspace_id}/submit"
    reviewer_csrf = fixture.login("workspace.reviewer")

    missing_csrf = fixture.client.post(
        url,
        json={"expected_workspace_version": 1, "idempotency_key": "no-csrf"},
    )
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["code"] == "CSRF_VALIDATION_FAILED"

    oversized_key = fixture.client.post(
        url,
        headers={
            "X-CSRF-Token": reviewer_csrf,
            "Idempotency-Key": "x" * 256,
        },
        json={"expected_workspace_version": 1},
    )
    assert oversized_key.status_code == 422
    assert oversized_key.json()["code"] == "INVALID_REQUEST"

    blocked = fixture.client.post(
        url,
        headers={"X-CSRF-Token": reviewer_csrf},
        json={"expected_workspace_version": 1, "idempotency_key": "pending"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "SUBMISSION_BLOCKED"
    blockers = blocked.json()["details"]["blockers"]
    assert {item["section_key"] for item in blockers} == {
        section.value for section in PaperSection
    }
    assert all(item["entity_type"] == "paper_section_review" for item in blockers)

    with fixture.session_factory.begin() as session:
        _complete_sections(session, fixture, not_reported=set(PaperSection))

    stale = fixture.client.post(
        url,
        headers={"X-CSRF-Token": reviewer_csrf},
        json={"expected_workspace_version": 9, "idempotency_key": "stale"},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "WORKSPACE_VERSION_CONFLICT"

    other_csrf = fixture.login("workspace.other")
    concealed = fixture.client.post(
        url,
        headers={"X-CSRF-Token": other_csrf},
        json={"expected_workspace_version": 1, "idempotency_key": "other"},
    )
    assert concealed.status_code == 404
    assert concealed.json()["code"] == "RESOURCE_NOT_FOUND"

    admin_csrf = fixture.login("workspace.admin")
    admin = fixture.client.post(
        url,
        headers={"X-CSRF-Token": admin_csrf},
        json={"expected_workspace_version": 1, "idempotency_key": "admin"},
    )
    assert admin.status_code == 403
    assert admin.json()["code"] == "PERMISSION_DENIED"

    with fixture.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PaperSubmission)) == 0
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == 0


def test_submission_validation_api_returns_record_addressable_blockers_only_to_assignee(
    workspace_fixture,
):
    fixture = workspace_fixture
    fixture.login("workspace.reviewer")
    url = f"/api/v2/workspaces/{fixture.workspace_id}/submission-validation"

    response = fixture.client.get(url)

    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is False
    assert {item["section_key"] for item in payload["blockers"]} == {
        section.value for section in PaperSection
    }
    assert all(item["entity_type"] == "paper_section_review" for item in payload["blockers"])

    fixture.login("workspace.other")
    concealed = fixture.client.get(url)
    assert concealed.status_code == 404
    assert concealed.json()["code"] == "RESOURCE_NOT_FOUND"


def test_submission_api_freezes_safe_snapshot_and_replays_idempotently(
    workspace_fixture,
):
    fixture = workspace_fixture
    with fixture.session_factory.begin() as session:
        _complete_sections(session, fixture, not_reported=set(PaperSection))

    csrf = fixture.login("workspace.reviewer")
    url = f"/api/v2/workspaces/{fixture.workspace_id}/submit"
    request = {
        "expected_workspace_version": 1,
        "idempotency_key": "body-key",
        "reviewer_note": "Ready for Admin review",
    }
    first = fixture.client.post(
        url,
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": "header-key"},
        json=request,
    )
    replay = fixture.client.post(
        url,
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": "header-key"},
        json={**request, "reviewer_note": "ignored replay note"},
    )
    new_key = fixture.client.post(
        url,
        headers={"X-CSRF-Token": csrf},
        json={"expected_workspace_version": 2, "idempotency_key": "new-key"},
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    payload = first.json()
    assert payload["workspace_version"] == 2
    assert payload["submission"]["workspace_version"] == 2
    assert payload["submission"]["idempotency_key"] == "header-key"
    assert payload["submission"]["snapshot"]["workspace_version"] == 2
    assert payload["submission"]["snapshot"]["source"] == {
        "asset_id": str(fixture.asset_id),
        "source_root_key": "source_pdfs",
        "source_key": "volume67 issue5/paper-01.pdf",
        "sha256": "a" * 64,
        "page_count": 12,
    }
    assert "/srv/private" not in first.text
    assert "must-never-be-returned" not in first.text
    assert "password" not in first.text.casefold()
    assert new_key.status_code == 409
    assert new_key.json()["code"] == "WORKSPACE_READ_ONLY"

    with fixture.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PaperSubmission)) == 1
        assert session.scalar(select(func.count()).select_from(ChangeEvent)) == 1


def test_submission_rows_reject_update_and_delete(workspace_fixture):
    fixture = workspace_fixture
    service = SubmissionService()
    with fixture.session_factory.begin() as session:
        _complete_sections(session, fixture, not_reported=set(PaperSection))
        submission = service.submit(
            session,
            workspace_id=fixture.workspace_id,
            reviewer_id=fixture.reviewer_id,
            expected_workspace_version=1,
            idempotency_key="immutable",
            reviewer_note=None,
        )
        submission_id = submission.id

    with pytest.raises(DBAPIError) as update_error:
        with fixture.session_factory.begin() as session:
            session.execute(
                text(
                    "UPDATE paper_submissions SET reviewer_note = 'tampered' "
                    "WHERE id = :submission_id"
                ),
                {"submission_id": submission_id},
            )
    assert getattr(update_error.value.orig, "sqlstate", None) == "55000"

    with pytest.raises(DBAPIError) as delete_error:
        with fixture.session_factory.begin() as session:
            session.execute(
                text("DELETE FROM paper_submissions WHERE id = :submission_id"),
                {"submission_id": submission_id},
            )
    assert getattr(delete_error.value.orig, "sqlstate", None) == "55000"
