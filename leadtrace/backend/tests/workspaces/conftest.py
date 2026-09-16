from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.assets.models import (
    Asset,
    AssetAccessLevel,
    AssetCategory,
    AssetIntegrityState,
)
from app.catalog.models import PaperSource, PaperSourceIntegrityState
from app.config import Settings
from app.database import DatabaseResources
from app.main import create_app
from app.papers.models import Paper, PaperCatalogState
from app.users.models import User, UserRole
from app.users.service import UserService
from app.workspaces.models import (
    PaperSection,
    PaperSectionReview,
    PaperSectionState,
    PaperWorkspace,
    ReviewTask,
    ReviewTaskState,
    WorkspaceState,
)


PASSWORD = "Workspace API password 2026!"


@dataclass(frozen=True, slots=True)
class WorkspaceFixture:
    client: TestClient
    session_factory: sessionmaker[Session]
    workspace_id: UUID
    task_id: UUID
    paper_id: UUID
    source_id: UUID
    asset_id: UUID
    reviewer_id: UUID
    other_reviewer_id: UUID
    admin_id: UUID
    visitor_id: UUID

    def login(self, username: str) -> str:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": PASSWORD},
        )
        assert response.status_code == 200
        return str(response.json()["csrf_token"])


@pytest.fixture
def workspace_fixture(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> Iterator[WorkspaceFixture]:
    with auth_session_factory.begin() as session:
        admin = UserService().create_user(
            session,
            username="workspace.admin",
            display_name="Workspace Admin",
            role=UserRole.ADMIN,
            initial_password=PASSWORD,
        )
        reviewer = UserService().create_user(
            session,
            username="workspace.reviewer",
            display_name="Workspace Reviewer",
            role=UserRole.REVIEWER,
            initial_password=PASSWORD,
        )
        other_reviewer = UserService().create_user(
            session,
            username="workspace.other",
            display_name="Other Reviewer",
            role=UserRole.REVIEWER,
            initial_password=PASSWORD,
        )
        visitor = UserService().create_user(
            session,
            username="workspace.visitor",
            display_name="Workspace Visitor",
            role=UserRole.VISITOR,
            initial_password=PASSWORD,
        )
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
                "physical_path": "/srv/private/source_pdfs/paper-01.pdf",
                "credential": "must-never-be-returned",
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
            title="Extracted title",
            journal="Journal of Medicinal Chemistry",
            publication_year=2024,
            volume="67",
            issue="5",
            doi="10.1021/acs.jmedchem.4c0001",
            catalog_state=PaperCatalogState.EXTRACTED,
        )
        session.add(paper)
        session.flush()
        task = ReviewTask(
            paper_id=paper.id,
            assigned_reviewer_id=reviewer.id,
            created_by_id=admin.id,
            status=ReviewTaskState.ASSIGNED,
            version=1,
        )
        session.add(task)
        session.flush()
        workspace = PaperWorkspace(
            paper_id=paper.id,
            review_task_id=task.id,
            state=WorkspaceState.EDITING,
            version=1,
        )
        session.add(workspace)
        session.flush()
        session.add_all(
            [
                PaperSectionReview(
                    paper_id=paper.id,
                    workspace_id=workspace.id,
                    section_key=section,
                    state=PaperSectionState.PENDING,
                    note=None,
                )
                for section in PaperSection
            ]
        )
        ids = {
            "workspace_id": workspace.id,
            "task_id": task.id,
            "paper_id": paper.id,
            "source_id": source.id,
            "asset_id": asset.id,
            "reviewer_id": reviewer.id,
            "other_reviewer_id": other_reviewer.id,
            "admin_id": admin.id,
            "visitor_id": visitor.id,
        }

    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=empty_postgresql_database_url,
        redis_url="redis://127.0.0.1:6379/0",
        session_secret="workspace-api-session-secret-more-than-thirty-two-characters",
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
        yield WorkspaceFixture(
            client=client,
            session_factory=auth_session_factory,
            **ids,
        )
