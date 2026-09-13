from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.activities.models import Activity
from app.assets.models import Asset
from app.assets.storage import LocalAssetStore
from app.compounds.models import Compound
from app.evidence.models import Evidence
from app.imports.approval import ImportCandidateApprovalService
from app.imports.models import ImportBatch, ImportReleaseCandidate
from app.imports.service import BaselineImporter
from app.lineages.models import Lineage, LineageEdge
from app.papers.models import Paper
from app.releases.aggregate import overview_metrics_from_counts
from app.releases.manifest import get_release_artifact_manifest
from app.releases.models import Release, ReleaseItem, ReleaseOperation
from app.releases.service import (
    BaselineValidationError,
    ReleaseConflict,
    publish_approved_baseline,
)
from app.revisions.models import ObjectKind, ObjectRevision
from app.security.policies import WorkflowState
from app.structures.models import Structure
from app.users.models import UserRole
from app.users.service import UserService
from app.visual_objects.models import VisualObject, VisualRegion
PASSWORD = "Baseline publish test password 2026!"
pytest_plugins = ("tests.imports.conftest",)


OVERVIEW_KEYS = {
    "corpus",
    "lineage",
    "relation",
    "structure",
    "pair",
    "human_review",
}
DOMAIN_KEY_FIELDS = {
    ObjectKind.PAPER: (Paper, "paper_key"),
    ObjectKind.COMPOUND: (Compound, "local_identity"),
    ObjectKind.STRUCTURE: (Structure, "structure_key"),
    ObjectKind.EVIDENCE: (Evidence, "evidence_key"),
    ObjectKind.ACTIVITY: (Activity, "activity_key"),
    ObjectKind.LINEAGE: (Lineage, "lineage_key"),
    ObjectKind.LINEAGE_EDGE: (LineageEdge, "edge_key"),
    ObjectKind.VISUAL_REGION: (VisualRegion, "region_key"),
    ObjectKind.VISUAL_OBJECT: (VisualObject, "object_key"),
}


def _asset_store(tmp_path: Path, fixture: dict[str, object]) -> LocalAssetStore:
    workspace = fixture["workspace"]
    assert isinstance(workspace, Path)
    return LocalAssetStore(
        tmp_path / "managed",
        source_roots={"baseline": workspace},
    )


def _import_candidate(
    session,
    tmp_path: Path,
    fixture: dict[str, object],
):
    source_root = fixture["source_root"]
    manifest_path = fixture["manifest_path"]
    expected = fixture["expected"]
    assert isinstance(source_root, Path)
    assert isinstance(manifest_path, Path)
    assert isinstance(expected, dict)
    imported = BaselineImporter(
        source_root,
        managed_asset_root=tmp_path / "managed",
        expected=expected,
        source_manifest_path=manifest_path,
    ).apply(session)
    admin = UserService().create_user(
        session,
        username=f"baseline-publisher-{uuid4().hex[:8]}",
        display_name="Baseline Publisher",
        role=UserRole.ADMIN,
        initial_password=PASSWORD,
    )
    admin.must_change_password = False
    candidate = session.get(
        ImportReleaseCandidate,
        imported.release_candidate_id,
    )
    assert candidate is not None
    return admin, candidate


def _approve(session, admin, candidate) -> None:
    ImportCandidateApprovalService().decide(
        session,
        candidate_id=candidate.id,
        actor_id=admin.id,
        action="approve",
        reason="The imported baseline manifest and integrity report were reviewed.",
    )


def test_overview_metrics_from_fixed_baseline_counts() -> None:
    metrics = overview_metrics_from_counts(
        {
            "corpus_papers": 672,
            "lineage_papers": 138,
            "lineage_edges": 4144,
            "structure_confirmed": 4011,
            "compound_entities": 4301,
            "pair_ready_edges": 1730,
        }
    )

    assert metrics == {
        "corpus": {"numerator": 672, "denominator": 672, "unit": "papers"},
        "lineage": {"numerator": 138, "denominator": 672, "unit": "papers"},
        "relation": {"numerator": 4144, "denominator": 4144, "unit": "edges"},
        "structure": {
            "numerator": 4011,
            "denominator": 4301,
            "unit": "compounds",
        },
        "pair": {"numerator": 1730, "denominator": 4144, "unit": "edges"},
        "human_review": {
            "numerator": 0,
            "denominator": 672,
            "unit": "papers",
        },
    }


def test_publish_approved_baseline_creates_complete_valid_current_release(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        admin, candidate = _import_candidate(session, tmp_path, baseline_fixture)
        _approve(session, admin, candidate)
        batch = session.get(ImportBatch, candidate.import_batch_id)
        assert batch is not None

        result = publish_approved_baseline(
            session,
            candidate_id=candidate.id,
            actor_id=admin.id,
            title="LeadTrace baseline",
            notes="Initial reviewed corpus publication",
            idempotency_key="baseline-success",
            asset_store=_asset_store(tmp_path, baseline_fixture),
        )

        assert result.idempotent is False
        assert result.validation.valid is True
        assert result.replaced_release_id is None
        assert result.release.source_candidate_id == candidate.id
        assert result.release.release_key == f"baseline-{candidate.id}"
        assert result.release.is_current is True
        assert result.release.manifest_finalized is True
        assert candidate.status == "published"
        assert candidate.is_current is True

        items = list(
            session.scalars(
                select(ReleaseItem)
                .where(ReleaseItem.release_id == result.release.id)
                .order_by(ReleaseItem.manifest_order)
            )
        )
        assert len(items) == candidate.manifest["revision_count"] == 10
        assert [item.manifest_order for item in items] == list(range(1, 11))
        expected_kind_order = {
            kind: index for index, kind in enumerate(ObjectKind)
        }
        paper_keys = {
            paper.id: paper.paper_key for paper in session.scalars(select(Paper))
        }
        actual_order = []
        for item in items:
            model, key_field = DOMAIN_KEY_FIELDS[item.object_kind]
            record = session.get(model, item.object_id)
            assert record is not None
            actual_order.append(
                (
                    paper_keys[item.paper_id],
                    expected_kind_order[item.object_kind],
                    str(getattr(record, key_field)),
                    str(item.object_id),
                )
            )
        assert actual_order == sorted(actual_order)

        revisions = list(
            session.scalars(
                select(ObjectRevision).order_by(ObjectRevision.object_id)
            )
        )
        assert len(revisions) == 10
        assert all(
            revision.workflow_state is WorkflowState.PUBLISHED
            and revision.is_current_published
            for revision in revisions
        )

        expected_metrics = overview_metrics_from_counts(batch.counts)
        assert {
            key: result.release.metrics[key] for key in OVERVIEW_KEYS
        } == expected_metrics
        assert result.release.metrics["baseline"] == {
            "candidate_id": str(candidate.id),
            "batch_id": str(batch.id),
            "source_fingerprint": batch.source_fingerprint,
            "counts": batch.counts,
            "integrity": batch.integrity,
            "asset_linkage": batch.asset_linkage,
            "item_count": 10,
        }

        artifact = get_release_artifact_manifest(session, result.release.id)
        assert artifact is not None
        assert artifact.snapshot["baseline_import"]["candidate_id"] == str(
            candidate.id
        )
        assert set(artifact.snapshot["baseline_import"]["asset_ids"]) == {
            str(value) for value in session.scalars(select(Asset.id))
        }

        operation = session.scalar(select(ReleaseOperation))
        assert operation is not None
        assert operation.operation_type == "baseline_publish"
        assert operation.replaced_release_id is None
        assert operation.result_release_id == result.release.id


@pytest.mark.parametrize("decision", [None, "reject"])
def test_publish_baseline_requires_approved_candidate(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory,
    decision: str | None,
) -> None:
    with auth_session_factory.begin() as session:
        admin, candidate = _import_candidate(session, tmp_path, baseline_fixture)
        if decision is not None:
            ImportCandidateApprovalService().decide(
                session,
                candidate_id=candidate.id,
                actor_id=admin.id,
                action="reject",
                reason="Reject this imported candidate.",
            )

        with pytest.raises(ReleaseConflict, match="approved"):
            publish_approved_baseline(
                session,
                candidate_id=candidate.id,
                actor_id=admin.id,
                idempotency_key="baseline-not-approved",
                asset_store=_asset_store(tmp_path, baseline_fixture),
            )


@pytest.mark.parametrize("role", [UserRole.VISITOR, UserRole.REVIEWER])
def test_publish_baseline_requires_enabled_admin(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory,
    role: UserRole,
) -> None:
    with auth_session_factory.begin() as session:
        admin, candidate = _import_candidate(session, tmp_path, baseline_fixture)
        _approve(session, admin, candidate)
        actor = UserService().create_user(
            session,
            username=f"baseline-{role.value}-{uuid4().hex[:8]}",
            display_name="Unauthorized publisher",
            role=role,
            initial_password=PASSWORD,
        )
        actor.must_change_password = False

        with pytest.raises(ReleaseConflict, match="enabled Admin"):
            publish_approved_baseline(
                session,
                candidate_id=candidate.id,
                actor_id=actor.id,
                idempotency_key="baseline-forbidden",
                asset_store=_asset_store(tmp_path, baseline_fixture),
            )


def test_publish_baseline_rejects_disabled_admin(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        admin, candidate = _import_candidate(session, tmp_path, baseline_fixture)
        _approve(session, admin, candidate)
        admin.is_enabled = False

        with pytest.raises(ReleaseConflict, match="enabled Admin"):
            publish_approved_baseline(
                session,
                candidate_id=candidate.id,
                actor_id=admin.id,
                idempotency_key="baseline-disabled-admin",
                asset_store=_asset_store(tmp_path, baseline_fixture),
            )


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("incomplete_batch", ReleaseConflict),
        ("changed_manifest", ReleaseConflict),
        ("wrong_counts", ReleaseConflict),
        ("missing_revision", BaselineValidationError),
    ],
)
def test_publish_baseline_rechecks_imported_candidate_invariants(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory,
    mutation: str,
    expected_error: type[Exception],
) -> None:
    with auth_session_factory.begin() as session:
        admin, candidate = _import_candidate(session, tmp_path, baseline_fixture)
        _approve(session, admin, candidate)
        batch = session.get(ImportBatch, candidate.import_batch_id)
        assert batch is not None
        if mutation == "incomplete_batch":
            batch.status = "staging"
        elif mutation == "changed_manifest":
            candidate.manifest = {**candidate.manifest, "revision_count": 11}
        elif mutation == "wrong_counts":
            batch.counts = {**batch.counts, "corpus_papers": 2}
        else:
            session.add(Paper(paper_key="paper-without-baseline-revision", doi=None))
        session.flush()

        with pytest.raises(expected_error):
            publish_approved_baseline(
                session,
                candidate_id=candidate.id,
                actor_id=admin.id,
                idempotency_key=f"baseline-{mutation}",
                asset_store=_asset_store(tmp_path, baseline_fixture),
            )


def test_publish_baseline_refuses_any_existing_release(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        admin, candidate = _import_candidate(session, tmp_path, baseline_fixture)
        _approve(session, admin, candidate)
        session.add(
            Release(
                release_key="existing-release",
                title="Existing release",
                notes="",
                metrics={},
                published_by_id=admin.id,
                published_at=candidate.created_at,
                is_current=False,
                manifest_finalized=False,
            )
        )
        session.flush()

        with pytest.raises(ReleaseConflict, match="already exists"):
            publish_approved_baseline(
                session,
                candidate_id=candidate.id,
                actor_id=admin.id,
                idempotency_key="baseline-existing-release",
                asset_store=_asset_store(tmp_path, baseline_fixture),
            )


def test_publish_baseline_validates_imported_asset_bytes(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        admin, candidate = _import_candidate(session, tmp_path, baseline_fixture)
        _approve(session, admin, candidate)
        crop = baseline_fixture["crop"]
        assert isinstance(crop, Path)
        crop.unlink()

        with pytest.raises(ValueError, match="asset"):
            publish_approved_baseline(
                session,
                candidate_id=candidate.id,
                actor_id=admin.id,
                idempotency_key="baseline-missing-asset",
                asset_store=_asset_store(tmp_path, baseline_fixture),
            )


def test_publish_baseline_exact_retry_is_idempotent_and_key_reuse_conflicts(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory,
) -> None:
    with auth_session_factory.begin() as session:
        admin, candidate = _import_candidate(session, tmp_path, baseline_fixture)
        _approve(session, admin, candidate)
        arguments = {
            "candidate_id": candidate.id,
            "actor_id": admin.id,
            "title": "LeadTrace baseline",
            "notes": "Reviewed initial corpus",
            "idempotency_key": "baseline-idempotent",
            "asset_store": _asset_store(tmp_path, baseline_fixture),
        }
        first = publish_approved_baseline(session, **arguments)
        first_release_id = first.release.id
        first_operation_id = first.operation_id
        first_validation = first.validation.as_dict()

    crop = baseline_fixture["crop"]
    assert isinstance(crop, Path)
    crop.unlink()

    with auth_session_factory.begin() as session:
        retried = publish_approved_baseline(session, **arguments)

        assert retried.idempotent is True
        assert retried.release.id == first_release_id
        assert retried.operation_id == first_operation_id
        assert retried.validation.as_dict() == first_validation
        assert session.scalar(select(func.count()).select_from(Release)) == 1

        with pytest.raises(ReleaseConflict, match="Idempotency key"):
            publish_approved_baseline(
                session,
                **{**arguments, "title": "Different publication request"},
            )


@pytest.mark.parametrize("fail_stage", ["final_transaction", "before_pointer_switch"])
def test_publish_baseline_failure_rolls_back_every_state_change(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory,
    fail_stage: str,
) -> None:
    with auth_session_factory.begin() as session:
        admin, candidate = _import_candidate(session, tmp_path, baseline_fixture)
        _approve(session, admin, candidate)
        candidate_id = candidate.id
        admin_id = admin.id

    with pytest.raises(RuntimeError, match="Injected failure"):
        with auth_session_factory.begin() as session:
            publish_approved_baseline(
                session,
                candidate_id=candidate_id,
                actor_id=admin_id,
                idempotency_key=f"baseline-failure-{fail_stage}",
                fail_stage=fail_stage,
                asset_store=_asset_store(tmp_path, baseline_fixture),
            )

    with auth_session_factory() as session:
        candidate = session.get(ImportReleaseCandidate, candidate_id)
        assert candidate is not None
        assert candidate.status == "approved"
        assert candidate.is_current is False
        assert session.scalar(select(func.count()).select_from(Release)) == 0
        assert session.scalar(
            select(func.count()).select_from(ReleaseOperation)
        ) == 0
        revisions = list(session.scalars(select(ObjectRevision)))
        assert all(
            revision.workflow_state is WorkflowState.APPROVED
            and not revision.is_current_published
            for revision in revisions
        )
