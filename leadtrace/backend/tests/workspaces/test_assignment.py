from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.assets.models import (
    Asset,
    AssetAccessLevel,
    AssetCategory,
    AssetIntegrityState,
)
from app.audit.models import AuditChainHead, AuditEvent
from app.catalog.models import PaperSource, PaperSourceIntegrityState
from app.config import Settings
from app.database import DatabaseResources
from app.main import create_app
from app.papers.models import Paper, PaperCatalogState
from app.users.models import User, UserRole
from app.users.service import UserService
from app.workspaces.models import (
    ChangeEvent,
    PaperSection,
    PaperSectionReview,
    PaperSectionState,
    PaperWorkspace,
    ReviewTask,
    ReviewTaskState,
    WorkspaceState,
)
from app.workspaces.assignment import AssignmentService


PASSWORD = "Assignment API password 2026!"


@dataclass(frozen=True, slots=True)
class AssignmentFixture:
    client: TestClient
    session_factory: sessionmaker[Session]
    paper_id: UUID
    source_id: UUID
    asset_id: UUID
    reviewer_id: UUID
    disabled_reviewer_id: UUID
    visitor_id: UUID
    admin_id: UUID


@pytest.fixture
def assignment_client(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> Iterator[AssignmentFixture]:
    with auth_session_factory.begin() as session:
        users: dict[UserRole, User] = {}
        for role in UserRole:
            users[role] = UserService().create_user(
                session,
                username=f"assignment.{role.value}",
                display_name=f"Assignment {role.value.title()}",
                role=role,
                initial_password=PASSWORD,
            )
        disabled_reviewer = UserService().create_user(
            session,
            username="assignment.disabled",
            display_name="Disabled Reviewer",
            role=UserRole.REVIEWER,
            initial_password=PASSWORD,
        )
        disabled_reviewer.is_enabled = False
        asset = Asset(
            storage_key="source/source_pdfs/volume67 issue5/paper-01.pdf",
            original_filename="paper-01.pdf",
            sha256="a" * 64,
            byte_size=12345,
            mime_type="application/pdf",
            page_count=12,
            category=AssetCategory.ARTICLE_PDF,
            access_level=AssetAccessLevel.REVIEWER,
            integrity_state=AssetIntegrityState.VERIFIED,
            derivation_metadata={},
            source_metadata={
                "credential": "must-never-enter-audit",
                "physical_path": "/srv/private/paper-01.pdf",
            },
        )
        session.add(asset)
        session.flush()
        source = PaperSource(
            asset_id=asset.id,
            source_root_key="source_pdfs",
            source_key="volume67 issue5/paper-01.pdf",
            sha256=asset.sha256,
            byte_size=asset.byte_size,
            page_count=asset.page_count,
            integrity_state=PaperSourceIntegrityState.VERIFIED,
        )
        session.add(source)
        session.flush()
        paper = Paper(
            paper_key="LT-JMC-2024-67-05-001",
            source_id=source.id,
            title="Manual blank-workspace paper",
            journal="Journal of Medicinal Chemistry",
            publication_year=2024,
            volume="67",
            issue="5",
            doi="10.1021/acs.jmedchem.4c0001",
            catalog_state=PaperCatalogState.EXTRACTED,
        )
        session.add(paper)
        session.flush()
        fixture_ids = {
            "paper_id": paper.id,
            "source_id": source.id,
            "asset_id": asset.id,
            "reviewer_id": users[UserRole.REVIEWER].id,
            "disabled_reviewer_id": disabled_reviewer.id,
            "visitor_id": users[UserRole.VISITOR].id,
            "admin_id": users[UserRole.ADMIN].id,
        }

    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=empty_postgresql_database_url,
        redis_url="redis://127.0.0.1:6379/0",
        session_secret="assignment-api-session-secret-more-than-thirty-two-characters",
        allowed_hosts=["testserver"],
        asset_root=tmp_path / "managed",
    )
    resources = DatabaseResources(
        engine=auth_session_factory.kw["bind"],
        session_factory=auth_session_factory,
    )
    application = create_app(
        settings=settings,
        database_probe=lambda _: True,
        database_bootstrap=lambda _: resources,
    )
    with TestClient(application) as client:
        yield AssignmentFixture(
            client=client,
            session_factory=auth_session_factory,
            **fixture_ids,
        )


def _login(client: TestClient, role: UserRole) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": f"assignment.{role.value}", "password": PASSWORD},
    )
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


def _assign(
    fixture: AssignmentFixture,
    *,
    reviewer_id: UUID | None = None,
    csrf_token: str | None,
):
    headers = {"X-CSRF-Token": csrf_token} if csrf_token else {}
    return fixture.client.post(
        f"/api/v2/admin/papers/{fixture.paper_id}/assign",
        headers=headers,
        json={"reviewer_id": str(reviewer_id or fixture.reviewer_id)},
    )


def _aggregate_counts(session: Session) -> tuple[int, int, int, int]:
    return (
        int(session.scalar(select(func.count()).select_from(ReviewTask)) or 0),
        int(session.scalar(select(func.count()).select_from(PaperWorkspace)) or 0),
        int(session.scalar(select(func.count()).select_from(PaperSectionReview)) or 0),
        int(session.scalar(select(func.count()).select_from(ChangeEvent)) or 0),
    )


def test_admin_assigns_enabled_reviewer_to_complete_blank_workspace_aggregate(
    assignment_client: AssignmentFixture,
) -> None:
    csrf_token = _login(assignment_client.client, UserRole.ADMIN)

    response = _assign(assignment_client, csrf_token=csrf_token)

    assert response.status_code == 201
    payload = response.json()
    assert payload["paper_id"] == str(assignment_client.paper_id)
    assert payload["assigned_reviewer_id"] == str(assignment_client.reviewer_id)
    assert payload["task_status"] == "assigned"
    assert payload["task_version"] == 1
    assert payload["workspace_state"] == "editing"
    assert payload["workspace_version"] == 1
    assert payload["sections"] == [
        {"section_key": section.value, "state": "pending", "note": None}
        for section in PaperSection
    ]
    assert "baseline" not in response.text.casefold()
    assert "release" not in response.text.casefold()

    with assignment_client.session_factory() as session:
        assert _aggregate_counts(session) == (1, 1, 6, 0)
        task = session.scalar(select(ReviewTask))
        workspace = session.scalar(select(PaperWorkspace))
        sections = list(
            session.scalars(
                select(PaperSectionReview).order_by(PaperSectionReview.created_at)
            )
        )
        audit = session.scalar(
            select(AuditEvent).where(AuditEvent.action == "paper.review_assigned")
        )

    assert task is not None
    assert workspace is not None
    assert audit is not None
    assert task.paper_id == assignment_client.paper_id
    assert task.assigned_reviewer_id == assignment_client.reviewer_id
    assert task.created_by_id == assignment_client.admin_id
    assert task.status is ReviewTaskState.ASSIGNED
    assert workspace.paper_id == assignment_client.paper_id
    assert workspace.review_task_id == task.id
    assert workspace.state is WorkspaceState.EDITING
    assert {section.section_key for section in sections} == set(PaperSection)
    assert {section.state for section in sections} == {PaperSectionState.PENDING}
    assert {section.note for section in sections} == {None}
    assert audit.actor_id == assignment_client.admin_id
    assert audit.target_type == "review_task"
    assert audit.target_id == task.id
    assert audit.paper_id == assignment_client.paper_id
    assert audit.details == {
        "assigned_reviewer_id": str(assignment_client.reviewer_id),
        "workspace_id": str(workspace.id),
    }
    assert "credential" not in str(audit.details).casefold()
    assert "/srv/private" not in str(audit.details)


@pytest.mark.parametrize("role", [UserRole.REVIEWER, UserRole.VISITOR])
def test_non_admin_roles_cannot_assign_papers(
    assignment_client: AssignmentFixture,
    role: UserRole,
) -> None:
    csrf_token = _login(assignment_client.client, role)

    response = _assign(assignment_client, csrf_token=csrf_token)

    assert response.status_code == 403
    with assignment_client.session_factory() as session:
        assert _aggregate_counts(session) == (0, 0, 0, 0)


def test_assignment_requires_csrf_without_partial_writes(
    assignment_client: AssignmentFixture,
) -> None:
    _login(assignment_client.client, UserRole.ADMIN)

    response = _assign(assignment_client, csrf_token=None)

    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_VALIDATION_FAILED"
    with assignment_client.session_factory() as session:
        assert _aggregate_counts(session) == (0, 0, 0, 0)


@pytest.mark.parametrize("reviewer_kind", ["disabled", "visitor", "admin"])
def test_assignment_accepts_only_an_enabled_reviewer(
    assignment_client: AssignmentFixture,
    reviewer_kind: str,
) -> None:
    csrf_token = _login(assignment_client.client, UserRole.ADMIN)
    reviewer_ids = {
        "disabled": assignment_client.disabled_reviewer_id,
        "visitor": assignment_client.visitor_id,
        "admin": assignment_client.admin_id,
    }

    response = _assign(
        assignment_client,
        reviewer_id=reviewer_ids[reviewer_kind],
        csrf_token=csrf_token,
    )

    assert response.status_code == 422
    assert response.json()["message"] == "An enabled Reviewer is required"
    with assignment_client.session_factory() as session:
        assert _aggregate_counts(session) == (0, 0, 0, 0)


def test_assignment_rejects_unknown_reviewer(
    assignment_client: AssignmentFixture,
) -> None:
    csrf_token = _login(assignment_client.client, UserRole.ADMIN)

    response = _assign(
        assignment_client,
        reviewer_id=uuid4(),
        csrf_token=csrf_token,
    )

    assert response.status_code == 404
    assert response.json()["code"] == "REVIEWER_NOT_FOUND"
    assert response.json()["message"] == "Reviewer not found"


def test_duplicate_active_assignment_returns_conflict_and_keeps_one_aggregate(
    assignment_client: AssignmentFixture,
) -> None:
    csrf_token = _login(assignment_client.client, UserRole.ADMIN)

    first = _assign(assignment_client, csrf_token=csrf_token)
    duplicate = _assign(assignment_client, csrf_token=csrf_token)

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["message"] == "Paper already has an active assignment"
    with assignment_client.session_factory() as session:
        assert _aggregate_counts(session) == (1, 1, 6, 0)
        assert session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "paper.review_assigned")
        ) == 1


@pytest.mark.parametrize(
    "error_kind",
    ["paper", "source", "asset", "asset_access", "asset_storage_key"],
)
def test_source_or_catalog_integrity_errors_make_paper_unassignable(
    assignment_client: AssignmentFixture,
    error_kind: str,
) -> None:
    csrf_token = _login(assignment_client.client, UserRole.ADMIN)
    with assignment_client.session_factory.begin() as session:
        if error_kind == "paper":
            session.get(Paper, assignment_client.paper_id).catalog_state = (
                PaperCatalogState.SOURCE_ERROR
            )
        elif error_kind == "source":
            session.get(PaperSource, assignment_client.source_id).integrity_state = (
                PaperSourceIntegrityState.MISSING
            )
        elif error_kind == "asset":
            session.get(Asset, assignment_client.asset_id).integrity_state = (
                AssetIntegrityState.CORRUPT
            )
        elif error_kind == "asset_access":
            session.get(Asset, assignment_client.asset_id).access_level = (
                AssetAccessLevel.ADMIN
            )
        else:
            session.get(Asset, assignment_client.asset_id).storage_key = (
                "source/source_pdfs/volume67 issue5/other-paper.pdf"
            )

    response = _assign(assignment_client, csrf_token=csrf_token)

    assert response.status_code == 409
    assert response.json()["message"] == "Paper source is not verified"
    with assignment_client.session_factory() as session:
        assert _aggregate_counts(session) == (0, 0, 0, 0)


def test_assignment_rolls_back_the_aggregate_when_audit_append_fails(
    assignment_client: AssignmentFixture,
) -> None:
    with assignment_client.session_factory.begin() as session:
        session.execute(delete(AuditChainHead))

    with pytest.raises(RuntimeError, match="Audit chain head is not initialized"):
        with assignment_client.session_factory.begin() as session:
            AssignmentService().assign(
                session,
                paper_id=assignment_client.paper_id,
                reviewer_id=assignment_client.reviewer_id,
                admin_id=assignment_client.admin_id,
                request_id="assignment-rollback-test",
                ip_address="127.0.0.1",
            )

    with assignment_client.session_factory() as session:
        assert _aggregate_counts(session) == (0, 0, 0, 0)
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 0
