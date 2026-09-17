from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
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
from app.users.models import UserRole
from app.users.service import UserService
from app.workspaces.models import (
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


PASSWORD = "Publication API password 2026!"


@dataclass(frozen=True, slots=True)
class PublicationFixture:
    client: TestClient
    session_factory: sessionmaker[Session]
    workspace_id: UUID
    task_id: UUID
    paper_id: UUID
    unpublished_paper_id: UUID
    source_asset_id: UUID
    reviewer_id: UUID
    admin_id: UUID
    visitor_id: UUID

    def login(self, username: str) -> str:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": PASSWORD},
        )
        assert response.status_code == 200
        return str(response.json()["csrf_token"])

    def submit(self, *, key: str = "submission-1") -> PaperSubmission:
        with self.session_factory.begin() as session:
            for section in session.scalars(
                select(PaperSectionReview).where(
                    PaperSectionReview.workspace_id == self.workspace_id
                )
            ):
                section.state = PaperSectionState.NOT_REPORTED
            workspace = session.get(PaperWorkspace, self.workspace_id)
            assert workspace is not None
            return SubmissionService().submit(
                session,
                workspace_id=self.workspace_id,
                reviewer_id=self.reviewer_id,
                expected_workspace_version=workspace.version,
                idempotency_key=key,
                reviewer_note="Ready for Admin review",
            )


def _source(session: Session, *, suffix: str, digest: str) -> PaperSource:
    asset = Asset(
        storage_key=f"source/source_pdfs/{suffix}.pdf",
        original_filename=f"{suffix}.pdf",
        sha256=digest * 64,
        byte_size=100,
        mime_type="application/pdf",
        page_count=1,
        category=AssetCategory.ARTICLE_PDF,
        access_level=AssetAccessLevel.REVIEWER,
        integrity_state=AssetIntegrityState.VERIFIED,
        derivation_metadata={},
        source_metadata={"physical_path": f"/private/{suffix}.pdf"},
    )
    session.add(asset)
    session.flush()
    source = PaperSource(
        asset_id=asset.id,
        source_root_key="source_pdfs",
        source_key=f"{suffix}.pdf",
        sha256=asset.sha256,
        byte_size=asset.byte_size,
        page_count=asset.page_count,
        integrity_state=PaperSourceIntegrityState.VERIFIED,
    )
    session.add(source)
    session.flush()
    return source


@pytest.fixture
def publication_fixture(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> Iterator[PublicationFixture]:
    with auth_session_factory.begin() as session:
        admin = UserService().create_user(
            session,
            username="publication.admin",
            display_name="Publication Admin",
            role=UserRole.ADMIN,
            initial_password=PASSWORD,
        )
        reviewer = UserService().create_user(
            session,
            username="publication.reviewer",
            display_name="Publication Reviewer",
            role=UserRole.REVIEWER,
            initial_password=PASSWORD,
        )
        visitor = UserService().create_user(
            session,
            username="publication.visitor",
            display_name="Publication Visitor",
            role=UserRole.VISITOR,
            initial_password=PASSWORD,
        )
        source = _source(session, suffix="published-candidate", digest="a")
        other_source = _source(session, suffix="unpublished", digest="b")
        paper = Paper(
            paper_key="LT-PUBLISHED-CANDIDATE",
            source_id=source.id,
            title="Frozen submitted title",
            journal="Journal of Medicinal Chemistry",
            publication_year=2026,
            volume="1",
            issue="1",
            doi="10.1000/published-candidate",
            catalog_state=PaperCatalogState.VERIFIED,
        )
        unpublished_paper = Paper(
            paper_key="LT-UNPUBLISHED",
            source_id=other_source.id,
            title="Never approved title",
            journal="Journal of Medicinal Chemistry",
            publication_year=2026,
            volume="1",
            issue="2",
            doi="10.1000/unpublished",
            catalog_state=PaperCatalogState.VERIFIED,
        )
        session.add_all([paper, unpublished_paper])
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
            "unpublished_paper_id": unpublished_paper.id,
            "source_asset_id": source.asset_id,
            "reviewer_id": reviewer.id,
            "admin_id": admin.id,
            "visitor_id": visitor.id,
        }

    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=empty_postgresql_database_url,
        redis_url="redis://127.0.0.1:6379/0",
        session_secret="publication-session-secret-more-than-thirty-two-characters",
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
        yield PublicationFixture(
            client=client,
            session_factory=auth_session_factory,
            **ids,
        )
