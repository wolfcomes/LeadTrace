from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

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
from app.users.models import UserRole
from app.users.service import UserService


PASSWORD = "Catalog API password 2026!"


@dataclass(frozen=True, slots=True)
class CatalogFixture:
    client: TestClient
    paper_ids: tuple[UUID, ...]
    admin_id: UUID
    reviewer_id: UUID
    session_factory: sessionmaker[Session]


@pytest.fixture
def catalog_client(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> Iterator[CatalogFixture]:
    paper_ids: list[UUID] = []
    with auth_session_factory.begin() as session:
        admin_id: UUID | None = None
        reviewer_id: UUID | None = None
        for role in UserRole:
            user = UserService().create_user(
                session,
                username=f"catalog.{role.value}",
                display_name=f"Catalog {role.value.title()}",
                role=role,
                initial_password=PASSWORD,
            )
            if role is UserRole.REVIEWER:
                reviewer_id = user.id
            if role is UserRole.ADMIN:
                admin_id = user.id
        for index in range(1, 21):
            filename = f"paper-{index:02d}.pdf"
            digest = f"{index:064x}"
            asset = Asset(
                storage_key=f"/srv/private/source_pdfs/volume67 issue5/{filename}",
                original_filename=filename,
                sha256=digest,
                byte_size=1000 + index,
                mime_type="application/pdf",
                page_count=10 + index,
                category=AssetCategory.ARTICLE_PDF,
                access_level=AssetAccessLevel.REVIEWER,
                integrity_state=AssetIntegrityState.VERIFIED,
                derivation_metadata={},
                source_metadata={
                    "physical_path": f"/srv/private/source_pdfs/{filename}",
                    "credential": "must-never-be-returned",
                },
            )
            session.add(asset)
            session.flush()
            source = PaperSource(
                asset_id=asset.id,
                source_root_key="source_pdfs",
                source_key=f"volume67 issue5/{filename}",
                sha256=digest,
                byte_size=asset.byte_size,
                page_count=asset.page_count,
                integrity_state=PaperSourceIntegrityState.VERIFIED,
            )
            session.add(source)
            session.flush()
            paper = Paper(
                paper_key=f"LT-JMC-2024-67-05-{index:03d}",
                source_id=source.id,
                title=f"Pilot paper {index}",
                journal="Journal of Medicinal Chemistry",
                publication_year=2024,
                volume="67",
                issue="5",
                doi=f"10.1021/acs.jmedchem.4c{index:04d}",
                catalog_state=PaperCatalogState.EXTRACTED,
            )
            session.add(paper)
            session.flush()
            paper_ids.append(paper.id)

    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=empty_postgresql_database_url,
        redis_url="redis://127.0.0.1:6379/0",
        session_secret="catalog-api-session-secret-more-than-thirty-two-characters",
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
        assert admin_id is not None
        assert reviewer_id is not None
        yield CatalogFixture(
            client,
            tuple(paper_ids),
            admin_id,
            reviewer_id,
            auth_session_factory,
        )


def _login(client: TestClient, role: UserRole) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": f"catalog.{role.value}", "password": PASSWORD},
    )
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


def test_admin_lists_all_papers_with_paginated_safe_source_metadata(
    catalog_client: CatalogFixture,
) -> None:
    client = catalog_client.client
    _login(client, UserRole.ADMIN)

    response = client.get("/api/v2/admin/papers")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 20
    assert payload["limit"] == 100
    assert payload["offset"] == 0
    assert len(payload["items"]) == 20
    assert [item["paper_key"] for item in payload["items"]] == [
        f"LT-JMC-2024-67-05-{index:03d}" for index in range(1, 21)
    ]
    first = payload["items"][0]
    assert set(first) == {
        "id",
        "paper_key",
        "title",
        "journal",
        "publication_year",
        "volume",
        "issue",
        "doi",
        "catalog_state",
        "source",
        "review",
    }
    assert set(first["source"]) == {
        "id",
        "asset_id",
        "source_root_key",
        "source_key",
        "sha256",
        "byte_size",
        "page_count",
        "integrity_state",
    }
    assert first["source"]["source_root_key"] == "source_pdfs"
    assert first["source"]["source_key"] == "volume67 issue5/paper-01.pdf"
    assert "/srv/private" not in response.text
    assert "must-never-be-returned" not in response.text
    assert "credential" not in response.text.casefold()
    assert first["review"] is None


def test_admin_catalog_includes_review_progress_and_submission_state(
    catalog_client: CatalogFixture,
) -> None:
    from app.workspaces.models import (
        PaperSection,
        PaperSectionReview,
        PaperSectionState,
        PaperWorkspace,
        ReviewTask,
        ReviewTaskState,
        WorkspaceState,
    )

    with catalog_client.session_factory.begin() as session:
        task = ReviewTask(
            paper_id=catalog_client.paper_ids[0],
            assigned_reviewer_id=catalog_client.reviewer_id,
            created_by_id=catalog_client.admin_id,
            status=ReviewTaskState.CHANGES_REQUESTED,
            version=3,
        )
        session.add(task)
        session.flush()
        workspace = PaperWorkspace(
            paper_id=task.paper_id,
            review_task_id=task.id,
            state=WorkspaceState.EDITING,
            version=9,
        )
        session.add(workspace)
        session.flush()
        session.add_all([
            PaperSectionReview(
                paper_id=task.paper_id,
                workspace_id=workspace.id,
                section_key=section,
                state=(
                    PaperSectionState.COMPLETED
                    if index < 3
                    else PaperSectionState.NOT_REPORTED
                    if index == 3
                    else PaperSectionState.PENDING
                ),
                note=None,
            )
            for index, section in enumerate(PaperSection)
        ])
        task_id = task.id
        workspace_id = workspace.id

    client = catalog_client.client
    _login(client, UserRole.ADMIN)
    response = client.get(
        "/api/v2/admin/papers",
        params={"search": "Pilot paper 1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 11
    first = next(
        item for item in payload["items"]
        if item["id"] == str(catalog_client.paper_ids[0])
    )
    assert first["review"] == {
        "review_task_id": str(task_id),
        "workspace_id": str(workspace_id),
        "assigned_reviewer_id": str(catalog_client.reviewer_id),
        "assignee_display_name": "Catalog Reviewer",
        "task_status": "changes_requested",
        "workspace_state": "editing",
        "sections_resolved": 4,
        "sections_total": 6,
        "submission_state": "changes_requested",
    }


def test_admin_catalog_list_supports_stable_offset_pagination(
    catalog_client: CatalogFixture,
) -> None:
    client = catalog_client.client
    _login(client, UserRole.ADMIN)

    response = client.get("/api/v2/admin/papers", params={"limit": 3, "offset": 4})

    assert response.status_code == 200
    assert response.json()["total"] == 20
    assert response.json()["limit"] == 3
    assert response.json()["offset"] == 4
    assert [item["paper_key"] for item in response.json()["items"]] == [
        "LT-JMC-2024-67-05-005",
        "LT-JMC-2024-67-05-006",
        "LT-JMC-2024-67-05-007",
    ]


def test_admin_reads_one_paper_without_physical_source_data(
    catalog_client: CatalogFixture,
) -> None:
    client = catalog_client.client
    _login(client, UserRole.ADMIN)

    response = client.get(f"/api/v2/admin/papers/{catalog_client.paper_ids[7]}")

    assert response.status_code == 200
    assert response.json()["id"] == str(catalog_client.paper_ids[7])
    assert response.json()["paper_key"] == "LT-JMC-2024-67-05-008"
    assert response.json()["source"]["source_key"] == (
        "volume67 issue5/paper-08.pdf"
    )
    assert "/srv/private" not in response.text
    assert "must-never-be-returned" not in response.text


@pytest.mark.parametrize("role", [UserRole.REVIEWER, UserRole.VISITOR])
def test_non_admin_roles_cannot_read_the_admin_catalog(
    catalog_client: CatalogFixture,
    role: UserRole,
) -> None:
    client = catalog_client.client
    _login(client, role)

    listing = client.get("/api/v2/admin/papers")
    detail = client.get(f"/api/v2/admin/papers/{catalog_client.paper_ids[0]}")

    assert listing.status_code == 403
    assert detail.status_code == 403


def test_catalog_requires_authentication_and_conceals_missing_papers(
    catalog_client: CatalogFixture,
) -> None:
    client = catalog_client.client

    assert client.get("/api/v2/admin/papers").status_code == 401
    _login(client, UserRole.ADMIN)
    missing = client.get(f"/api/v2/admin/papers/{uuid4()}")

    assert missing.status_code == 404
    assert missing.json()["message"] == "Resource not found"
