from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.assets.models import Asset, AssetAccessLevel, AssetCategory, AssetIntegrityState
from app.assets.storage import LocalAssetStore
from app.catalog.models import PaperSource, PaperSourceIntegrityState
from app.config import Settings
from app.database import DatabaseResources
from app.main import create_app
from app.papers.models import Paper, PaperCatalogState
from app.users.models import UserRole
from app.users.service import UserService
from app.workspaces.models import PaperWorkspace, ReviewTask, WorkspaceState

PASSWORD = "Document test password 2026!"


@dataclass(frozen=True, slots=True)
class DocumentFixture:
    client: TestClient
    session_factory: sessionmaker[Session]
    paper_id: UUID
    source_id: UUID
    asset_id: UUID
    payload: bytes
    reviewer_id: UUID
    other_reviewer_id: UUID
    source_path: Path


@pytest.fixture
def document_fixture(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> Iterator[DocumentFixture]:
    source_root = tmp_path / "protected-source"
    source_path = source_root / "volume67 issue5" / "source-document.pdf"
    source_path.parent.mkdir(parents=True)
    document = pymupdf.open()
    page = document.new_page(width=320, height=240)
    page.insert_text((36, 48), "Protected source document")
    document.save(source_path)
    document.close()
    payload = source_path.read_bytes()
    store = LocalAssetStore(
        tmp_path / "managed", source_roots={"source_pdfs": source_root}
    )
    inspected = store.inspect("source/source_pdfs/volume67 issue5/source-document.pdf")

    with auth_session_factory.begin() as session:
        users = UserService()
        admin = users.create_user(session, username="document.admin", display_name="Document Admin", role=UserRole.ADMIN, initial_password=PASSWORD)
        reviewer = users.create_user(session, username="document.reviewer", display_name="Assigned Reviewer", role=UserRole.REVIEWER, initial_password=PASSWORD)
        other = users.create_user(session, username="document.other", display_name="Unassigned Reviewer", role=UserRole.REVIEWER, initial_password=PASSWORD)
        visitor = users.create_user(session, username="document.visitor", display_name="Document Visitor", role=UserRole.VISITOR, initial_password=PASSWORD)
        for user in (admin, reviewer, other, visitor):
            user.must_change_password = False
        asset = Asset(
            storage_key="source/source_pdfs/volume67 issue5/source-document.pdf",
            original_filename="source-document.pdf",
            sha256=inspected.sha256,
            byte_size=inspected.byte_size,
            page_count=inspected.page_count,
            mime_type="application/pdf",
            category=AssetCategory.ARTICLE_PDF,
            access_level=AssetAccessLevel.REVIEWER,
            integrity_state=AssetIntegrityState.VERIFIED,
            derivation_metadata={},
            source_metadata={"source_root_key": "source_pdfs"},
        )
        session.add(asset)
        session.flush()
        source = PaperSource(
            asset_id=asset.id,
            source_root_key="source_pdfs",
            source_key="volume67 issue5/source-document.pdf",
            sha256=asset.sha256,
            byte_size=asset.byte_size,
            page_count=asset.page_count or 1,
            integrity_state=PaperSourceIntegrityState.VERIFIED,
        )
        session.add(source)
        session.flush()
        paper = Paper(
            paper_key="LT-JMC-2024-67-05-DOC",
            source_id=source.id,
            title="Protected document",
            journal="Journal of Medicinal Chemistry",
            publication_year=2024,
            volume="67",
            issue="5",
            catalog_state=PaperCatalogState.EXTRACTED,
        )
        session.add(paper)
        session.flush()
        task = ReviewTask(paper_id=paper.id, assigned_reviewer_id=reviewer.id, created_by_id=admin.id)
        session.add(task)
        session.flush()
        session.add(PaperWorkspace(paper_id=paper.id, review_task_id=task.id, state=WorkspaceState.EDITING, version=1))
        ids = (paper.id, source.id, asset.id, reviewer.id, other.id)

    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=empty_postgresql_database_url,
        redis_url="redis://127.0.0.1:6379/0",
        session_secret="document-api-session-secret-more-than-thirty-two-characters",
        allowed_hosts=["testserver"],
        asset_root=tmp_path / "managed",
        source_roots={"source_pdfs": source_root},
    )
    resources = DatabaseResources(engine=auth_session_factory.kw["bind"], session_factory=auth_session_factory)
    application = create_app(settings=settings, database_probe=lambda _: True, database_bootstrap=lambda _: resources)
    with TestClient(application) as client:
        yield DocumentFixture(client, auth_session_factory, ids[0], ids[1], ids[2], payload, ids[3], ids[4], source_path)


def login(client: TestClient, username: str) -> str:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200
    return str(response.json()["csrf_token"])
