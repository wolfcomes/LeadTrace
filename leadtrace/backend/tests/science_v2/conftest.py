from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.assets.models import (
    Asset,
    AssetAccessLevel,
    AssetCategory,
    AssetIntegrityState,
)
from app.catalog.models import PaperSource, PaperSourceIntegrityState
from app.papers.models import Paper, PaperCatalogState
from app.users.models import User, UserRole
from app.users.service import UserService
from app.workspaces.models import PaperWorkspace, ReviewTask, WorkspaceState


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
