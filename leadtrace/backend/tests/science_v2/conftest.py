from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import pytest
import pymupdf
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.assets.models import (
    Asset,
    AssetAccessLevel,
    AssetCategory,
    AssetIntegrityState,
)
from app.assets.storage import LocalAssetStore
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
    PaperWorkspace,
    ReviewTask,
    WorkspaceState,
)


PASSWORD = "Science model password 2026!"


@dataclass(frozen=True, slots=True)
class ScienceAggregate:
    paper_id: UUID
    workspace_id: UUID
    reviewer_id: UUID
    asset_id: UUID


@dataclass(frozen=True, slots=True)
class ScienceContext:
    session_factory: sessionmaker[Session]
    first: ScienceAggregate
    second: ScienceAggregate


@dataclass(frozen=True, slots=True)
class ScienceApiContext:
    client: TestClient
    session_factory: sessionmaker[Session]
    first: ScienceAggregate
    second: ScienceAggregate
    reviewer_id: UUID
    other_reviewer_id: UUID
    admin_id: UUID
    visitor_id: UUID
    asset_root: Path

    def login(self, username: str) -> str:
        self.client.cookies.clear()
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": PASSWORD},
        )
        assert response.status_code == 200
        return str(response.json()["csrf_token"])


def _create_aggregate(
    session: Session,
    *,
    ordinal: int,
    admin: User,
    reviewer: User,
) -> ScienceAggregate:
    asset = Asset(
        storage_key=f"source/source_pdfs/volume67 issue5/science-{ordinal}.pdf",
        original_filename=f"science-{ordinal}.pdf",
        sha256=f"{ordinal:x}" * 64,
        byte_size=10_000 + ordinal,
        mime_type="application/pdf",
        page_count=12,
        category=AssetCategory.ARTICLE_PDF,
        access_level=AssetAccessLevel.REVIEWER,
        integrity_state=AssetIntegrityState.VERIFIED,
        derivation_metadata={},
        source_metadata={},
    )
    session.add(asset)
    session.flush()
    source = PaperSource(
        asset_id=asset.id,
        source_root_key="source_pdfs",
        source_key=f"volume67 issue5/science-{ordinal}.pdf",
        sha256=asset.sha256,
        byte_size=asset.byte_size,
        page_count=asset.page_count,
        integrity_state=PaperSourceIntegrityState.VERIFIED,
    )
    session.add(source)
    session.flush()
    paper = Paper(
        paper_key=f"LT-JMC-2024-67-05-S{ordinal:02d}",
        source_id=source.id,
        title=f"Science paper {ordinal}",
        journal="Journal of Medicinal Chemistry",
        publication_year=2024,
        volume="67",
        issue="5",
        doi=f"10.1021/acs.jmedchem.4s{ordinal:04d}",
        catalog_state=PaperCatalogState.EXTRACTED,
    )
    session.add(paper)
    session.flush()
    task = ReviewTask(
        paper_id=paper.id,
        assigned_reviewer_id=reviewer.id,
        created_by_id=admin.id,
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
            )
            for section in PaperSection
        ]
    )
    return ScienceAggregate(
        paper_id=paper.id,
        workspace_id=workspace.id,
        reviewer_id=reviewer.id,
        asset_id=asset.id,
    )


@pytest.fixture
def science_context(
    auth_session_factory: sessionmaker[Session],
) -> ScienceContext:
    with auth_session_factory.begin() as session:
        admin = UserService().create_user(
            session,
            username="science.admin",
            display_name="Science Admin",
            role=UserRole.ADMIN,
            initial_password=PASSWORD,
        )
        reviewer = UserService().create_user(
            session,
            username="science.reviewer",
            display_name="Science Reviewer",
            role=UserRole.REVIEWER,
            initial_password=PASSWORD,
        )
        first = _create_aggregate(
            session,
            ordinal=1,
            admin=admin,
            reviewer=reviewer,
        )
        second = _create_aggregate(
            session,
            ordinal=2,
            admin=admin,
            reviewer=reviewer,
        )
    return ScienceContext(
        session_factory=auth_session_factory,
        first=first,
        second=second,
    )


@pytest.fixture
def science_api_context(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> Iterator[ScienceApiContext]:
    with auth_session_factory.begin() as session:
        admin = UserService().create_user(
            session,
            username="science.api.admin",
            display_name="Science API Admin",
            role=UserRole.ADMIN,
            initial_password=PASSWORD,
        )
        reviewer = UserService().create_user(
            session,
            username="science.api.reviewer",
            display_name="Science API Reviewer",
            role=UserRole.REVIEWER,
            initial_password=PASSWORD,
        )
        other_reviewer = UserService().create_user(
            session,
            username="science.api.other",
            display_name="Other Science API Reviewer",
            role=UserRole.REVIEWER,
            initial_password=PASSWORD,
        )
        visitor = UserService().create_user(
            session,
            username="science.api.visitor",
            display_name="Science API Visitor",
            role=UserRole.VISITOR,
            initial_password=PASSWORD,
        )
        first = _create_aggregate(
            session,
            ordinal=11,
            admin=admin,
            reviewer=reviewer,
        )
        second = _create_aggregate(
            session,
            ordinal=12,
            admin=admin,
            reviewer=other_reviewer,
        )
        ids = {
            "reviewer_id": reviewer.id,
            "other_reviewer_id": other_reviewer.id,
            "admin_id": admin.id,
            "visitor_id": visitor.id,
        }

    asset_root = tmp_path / "managed"
    source_root = tmp_path / "source_pdfs"
    for aggregate, ordinal in ((first, 11), (second, 12)):
        source_path = source_root / "volume67 issue5" / f"science-{ordinal}.pdf"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        document = pymupdf.open()
        for page_number in range(1, 4):
            page = document.new_page(width=320, height=240)
            page.insert_text((36, 48), f"Science paper {ordinal}, page {page_number}")
            page.draw_rect(pymupdf.Rect(70, 80, 210, 180), color=(0, 0, 0))
        document.save(source_path)
        document.close()
        inspected = LocalAssetStore(
            asset_root,
            source_roots={"source_pdfs": source_root},
        ).inspect(
            f"source/source_pdfs/volume67 issue5/science-{ordinal}.pdf"
        )
        with auth_session_factory.begin() as session:
            asset = session.get(Asset, aggregate.asset_id)
            source = session.scalar(
                select(PaperSource).where(PaperSource.asset_id == aggregate.asset_id)
            )
            assert asset is not None and source is not None
            asset.sha256 = inspected.sha256
            asset.byte_size = inspected.byte_size
            asset.page_count = inspected.page_count
            source.sha256 = inspected.sha256
            source.byte_size = inspected.byte_size
            source.page_count = inspected.page_count or 3
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=empty_postgresql_database_url,
        redis_url="redis://127.0.0.1:6379/0",
        session_secret="science-api-session-secret-more-than-thirty-two-characters",
        allowed_hosts=["testserver"],
        asset_root=asset_root,
        source_roots={"source_pdfs": source_root},
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
        yield ScienceApiContext(
            client=client,
            session_factory=auth_session_factory,
            first=first,
            second=second,
            asset_root=asset_root,
            **ids,
        )
