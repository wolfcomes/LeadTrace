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
from app.assets.storage import LocalAssetStore
from app.config import Settings
from app.database import DatabaseResources
from app.imports.models import ImportAssetLink, ImportBatch
from app.main import create_app
from app.papers.models import Paper
from app.reviews.models import ReviewTask
from app.users.models import UserRole
from app.users.service import UserService


PASSWORD = "Document test password 2026!"


@dataclass(frozen=True, slots=True)
class DocumentFixture:
    client: TestClient
    session_factory: sessionmaker[Session]
    paper_id: UUID
    article_asset_id: UUID
    si_asset_id: UUID
    article_payload: bytes
    si_payload: bytes
    reviewer_id: UUID
    other_reviewer_id: UUID


def _pdf_bytes(label: str) -> bytes:
    return (
        b"%PDF-1.7\n"
        + f"1 0 obj\n<< /Type /Catalog >>\nendobj\n% {label}\n".encode()
        + b"%%EOF\n"
    )


@pytest.fixture
def document_fixture(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> Iterator[DocumentFixture]:
    article_payload = _pdf_bytes("article-document")
    si_payload = _pdf_bytes("supporting-information")
    store = LocalAssetStore(tmp_path)
    article_file = store.put_bytes(article_payload, suffix=".pdf")
    source_root = tmp_path / "source"
    source_root.mkdir()
    source_file = source_root / "supporting-information.pdf"
    source_file.write_bytes(si_payload)
    source_store = LocalAssetStore(tmp_path, source_roots={"baseline": source_root})
    si_file = source_store.inspect("source/baseline/supporting-information.pdf")

    with auth_session_factory.begin() as session:
        user_service = UserService()
        admin = user_service.create_user(
            session,
            username="document.admin",
            display_name="Document Admin",
            role=UserRole.ADMIN,
            initial_password=PASSWORD,
        )
        reviewer = user_service.create_user(
            session,
            username="document.reviewer",
            display_name="Assigned Reviewer",
            role=UserRole.REVIEWER,
            initial_password=PASSWORD,
        )
        other_reviewer = user_service.create_user(
            session,
            username="document.other",
            display_name="Unassigned Reviewer",
            role=UserRole.REVIEWER,
            initial_password=PASSWORD,
        )
        visitor = user_service.create_user(
            session,
            username="document.visitor",
            display_name="Document Visitor",
            role=UserRole.VISITOR,
            initial_password=PASSWORD,
        )
        for user in (admin, reviewer, other_reviewer, visitor):
            user.must_change_password = False

        paper = Paper(paper_key="paper-document-1")
        session.add(paper)
        session.flush()
        batch = ImportBatch(
            source_fingerprint="a" * 64,
            status="applied",
            counts={},
            integrity={},
            asset_linkage={},
        )
        session.add(batch)
        session.flush()
        article_asset = Asset(
            storage_key=article_file.storage_key,
            original_filename="article-document.pdf",
            sha256=article_file.sha256,
            byte_size=article_file.byte_size,
            mime_type="application/pdf",
            category=AssetCategory.ARTICLE_PDF,
            access_level=AssetAccessLevel.REVIEWER,
            integrity_state=AssetIntegrityState.VERIFIED,
            import_batch_id=batch.id,
            derivation_metadata={},
            source_metadata={"source_root_key": "baseline"},
        )
        si_asset = Asset(
            storage_key="source/baseline/supporting-information.pdf",
            original_filename="supporting-information.pdf",
            sha256=si_file.sha256,
            byte_size=si_file.byte_size,
            mime_type="application/pdf",
            category=AssetCategory.SI_PDF,
            access_level=AssetAccessLevel.REVIEWER,
            integrity_state=AssetIntegrityState.VERIFIED,
            import_batch_id=batch.id,
            derivation_metadata={},
            source_metadata={"source_root_key": "baseline"},
        )
        session.add_all([article_asset, si_asset])
        session.flush()
        session.add_all(
            [
                ImportAssetLink(
                    import_batch_id=batch.id,
                    record_type="paper",
                    original_id=paper.paper_key,
                    asset_id=article_asset.id,
                    link_role="article_pdf",
                    source_reference="source_pdfs/articles/article-document.pdf",
                ),
                ImportAssetLink(
                    import_batch_id=batch.id,
                    record_type="paper",
                    original_id=paper.paper_key,
                    asset_id=si_asset.id,
                    link_role="si_pdf",
                    source_reference="source_pdfs/articles/supporting-information.pdf",
                ),
            ]
        )
        session.add(
            ReviewTask(
                paper_id=paper.id,
                assigned_reviewer_id=reviewer.id,
                created_by_id=admin.id,
                priority=10,
            )
        )
        session.flush()
        paper_id = paper.id
        article_asset_id = article_asset.id
        si_asset_id = si_asset.id
        reviewer_id = reviewer.id
        other_reviewer_id = other_reviewer.id

    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=empty_postgresql_database_url,
        redis_url="redis://127.0.0.1:6379/0",
        session_secret="document-api-session-secret-more-than-thirty-two-characters",
        allowed_hosts=["testserver"],
        asset_root=tmp_path,
        source_roots={"baseline": source_root},
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
        yield DocumentFixture(
            client=client,
            session_factory=auth_session_factory,
            paper_id=paper_id,
            article_asset_id=article_asset_id,
            si_asset_id=si_asset_id,
            article_payload=article_payload,
            si_payload=si_payload,
            reviewer_id=reviewer_id,
            other_reviewer_id=other_reviewer_id,
        )


def login(client: TestClient, username: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return str(response.json()["csrf_token"])
