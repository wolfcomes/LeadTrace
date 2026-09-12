from __future__ import annotations

import pytest
from datetime import UTC, datetime
from uuid import uuid4
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.visual_objects.bindings import (
    BindingConflict,
    BindingService,
    ObjectRelationType,
    validate_relation_type,
)
from app.assets.models import Asset, AssetAccessLevel, AssetCategory, AssetIntegrityState
from app.compounds.models import Compound
from app.lineages.models import LineageEdge
from app.papers.models import Paper
from app.releases.models import Release
from app.reviews.models import Changeset, ReviewTask, ReviewTaskStatus
from app.security.policies import WorkflowState
from app.users.models import UserRole
from app.users.service import UserService
from app.visual_objects.models import VisualObject, VisualObjectRelation, VisualRegion
from app.visual_objects.relationships import RelationshipService


def test_visual_relation_types_never_include_lineage_edges() -> None:
    assert validate_relation_type("shares_scaffold_with") is ObjectRelationType.SHARES_SCAFFOLD_WITH
    with pytest.raises(BindingConflict):
        validate_relation_type("lineage_edge")


def test_many_to_many_bindings_allow_reuse_but_reject_exact_duplicates(
    auth_session_factory: sessionmaker[Session],
) -> None:
    with auth_session_factory.begin() as session:
        users = UserService()
        reviewer = users.create_user(
            session,
            username=f"binding-reviewer-{uuid4().hex[:8]}",
            display_name="Binding reviewer",
            role=UserRole.REVIEWER,
            initial_password="Binding password 2026!",
        )
        admin = users.create_user(
            session,
            username=f"binding-admin-{uuid4().hex[:8]}",
            display_name="Binding admin",
            role=UserRole.ADMIN,
            initial_password="Binding password 2026!",
        )
        paper = Paper(paper_key=f"binding-paper-{uuid4().hex[:8]}")
        session.add(paper)
        session.flush()
        release = Release(
            release_key=f"binding-release-{uuid4().hex[:8]}",
            title="Binding release",
            notes="",
            metrics={},
            published_by_id=admin.id,
            published_at=datetime.now(UTC),
            is_current=False,
            manifest_finalized=False,
        )
        session.add(release)
        session.flush()
        task = ReviewTask(
            paper_id=paper.id,
            assigned_reviewer_id=reviewer.id,
            created_by_id=admin.id,
            status=ReviewTaskStatus.IN_PROGRESS,
            version=1,
        )
        session.add(task)
        session.flush()
        changeset = Changeset(
            review_task_id=task.id,
            paper_id=paper.id,
            owner_id=reviewer.id,
            base_release_id=release.id,
            title="Binding changes",
            reason="Test bindings",
            workflow_state=WorkflowState.DRAFT,
            version=1,
        )
        session.add(changeset)
        region = VisualRegion(paper_id=paper.id, region_key="region-1", page_number=1)
        first = VisualObject(paper_id=paper.id, object_key="object-1", object_type="r_group")
        second = VisualObject(paper_id=paper.id, object_key="object-2", object_type="linker")
        compound = Compound(
            paper_id=paper.id,
            local_identity="26a",
            display_label="26a",
            normalized_label="26a",
        )
        asset = Asset(
            storage_key="managed/objects/binding.png",
            original_filename="binding.png",
            sha256="a" * 64,
            byte_size=4,
            mime_type="image/png",
            category=AssetCategory.EVIDENCE_CROP,
            access_level=AssetAccessLevel.REVIEWER,
            integrity_state=AssetIntegrityState.VERIFIED,
            derivation_metadata={},
            source_metadata={},
        )
        session.add_all([region, first, second, compound, asset])
        session.flush()
        service = BindingService()
        service.bind_region(
            session,
            object_id=first.id,
            region_id=region.id,
            changeset_id=changeset.id,
            expected_version=1,
        )
        with pytest.raises(BindingConflict, match="already bound"):
            service.bind_region(
                session,
                object_id=first.id,
                region_id=region.id,
                changeset_id=changeset.id,
                expected_version=2,
            )
        service.bind_region(
            session,
            object_id=second.id,
            region_id=region.id,
            changeset_id=changeset.id,
            expected_version=2,
        )
        service.bind_asset(
            session,
            object_id=first.id,
            asset_id=asset.id,
            changeset_id=changeset.id,
            expected_version=3,
            is_primary=True,
        )
        service.bind_asset(
            session,
            object_id=second.id,
            asset_id=asset.id,
            changeset_id=changeset.id,
            expected_version=4,
        )
        service.bind_compound(
            session,
            object_id=first.id,
            compound_id=compound.id,
            label="26a",
            changeset_id=changeset.id,
            expected_version=5,
            is_primary=True,
        )
        service.bind_compound(
            session,
            object_id=second.id,
            compound_id=compound.id,
            label="26a",
            changeset_id=changeset.id,
            expected_version=6,
        )
        relation = RelationshipService().create_relation(
            session,
            source_object_id=first.id,
            target_object_id=second.id,
            relation_type=ObjectRelationType.SHARES_SCAFFOLD_WITH,
        )
        assert relation.relation_type == ObjectRelationType.SHARES_SCAFFOLD_WITH.value
        assert session.scalar(select(func.count()).select_from(VisualObjectRelation)) == 1
        assert session.scalar(select(func.count()).select_from(LineageEdge)) == 0
