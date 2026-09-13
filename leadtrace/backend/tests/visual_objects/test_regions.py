from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.visual_objects.regions import (
    RegionBounds,
    RegionService,
    RegionValidationError,
    normalize_bounds,
)
from app.papers.models import Paper
from app.reviews.models import Changeset
from app.security.policies import WorkflowState
from app.users.models import UserRole
from app.users.service import UserService
from app.visual_objects.models import VisualRegion


def test_normalize_bounds_accepts_positive_normalized_rectangle() -> None:
    bounds = normalize_bounds(0.1, 0.2, 0.8, 0.9)

    assert bounds == RegionBounds(x0=0.1, y0=0.2, x1=0.8, y1=0.9)


@pytest.mark.parametrize(
    "values",
    [
        (-0.1, 0.2, 0.8, 0.9),
        (0.1, 0.2, 1.1, 0.9),
        (0.1, 0.2, 0.1, 0.9),
        (0.1, 0.9, 0.8, 0.2),
    ],
)
def test_normalize_bounds_rejects_invalid_rectangle(values: tuple[float, ...]) -> None:
    with pytest.raises(RegionValidationError):
        normalize_bounds(*values)


def test_region_snapshot_contains_stable_identity_and_revision_coordinates() -> None:
    from app.visual_objects.regions import build_region_snapshot

    region_id = uuid4()
    snapshot = build_region_snapshot(
        region_key="fig-1a",
        page_number=3,
        bounds=normalize_bounds(0.05, 0.1, 0.4, 0.7),
        rotation=90,
        region_id=region_id,
    )

    assert snapshot["region_key"] == "fig-1a"
    assert snapshot["region_id"] == str(region_id)
    assert snapshot["page_number"] == 3
    assert snapshot["bounds"] == {"x0": 0.05, "y0": 0.1, "x1": 0.4, "y1": 0.7}
    assert snapshot["rotation"] == 90


def test_region_service_uses_expected_version_for_concurrent_updates() -> None:
    from app.visual_objects.regions import RegionService, RegionVersionConflict

    service = RegionService()
    assert service.check_expected_version(1, expected_version=1) is None
    with pytest.raises(RegionVersionConflict):
        service.check_expected_version(2, expected_version=1)


def test_region_identity_must_belong_to_requested_paper(
    auth_session_factory: sessionmaker[Session],
) -> None:
    service = RegionService()
    with auth_session_factory.begin() as session:
        UserService().create_user(
            session,
            username=f"region-security-{uuid4().hex[:8]}",
            display_name="Region security reviewer",
            role=UserRole.REVIEWER,
            initial_password="Region security password 2026!",
        )
        paper_a = Paper(paper_key=f"region-paper-a-{uuid4().hex[:8]}")
        paper_b = Paper(paper_key=f"region-paper-b-{uuid4().hex[:8]}")
        session.add_all([paper_a, paper_b])
        session.flush()
        region = VisualRegion(
            paper_id=paper_b.id,
            region_key="paper-b-region",
            page_number=1,
        )
        session.add(region)
        session.flush()

        with pytest.raises(RegionValidationError, match="another Paper"):
            service.ensure_region_belongs_to_paper(
                session,
                region_id=region.id,
                paper_id=paper_a.id,
            )


def test_changes_requested_regions_require_an_explicit_revised_draft() -> None:
    class FakeSession:
        def scalar(self, *_args: object, **_kwargs: object) -> Changeset:
            return Changeset(
                id=uuid4(),
                paper_id=uuid4(),
                review_task_id=uuid4(),
                owner_id=uuid4(),
                base_release_id=uuid4(),
                title="Needs revision",
                reason="reviewer feedback",
                workflow_state=WorkflowState.CHANGES_REQUESTED,
                version=3,
            )

    with pytest.raises(RegionValidationError, match="editable draft"):
        RegionService._editable_changeset(FakeSession(), uuid4(), 3)
