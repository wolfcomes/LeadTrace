from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text

from app.audit.models import AuditEvent
from app.audit.service import canonical_content_hash
from app.imports import proposal_backfill as proposal_backfill_module
from app.imports.models import ImportBatch, ImportStagingRecord
from app.imports.proposal_backfill import (
    MachineEvidenceBackfillError,
    backfill_machine_evidence,
)
from app.imports.reconcile import load_baseline_source
from app.molecule_proposals.models import (
    MoleculeProposal,
    MoleculeProposalDisposition,
)
from app.molecule_proposals.service import MoleculeProposalReviewService
from app.releases.manifest import capture_release_artifact_manifest, get_release_artifact_manifest
from app.releases.models import Release, ReleaseItem, ReleaseOperation
from app.releases.service import publish_approved_baseline
from app.revisions.models import ObjectKind, ObjectRevision
from app.revisions.service import RevisionService
from app.reviews.service import ReviewService
from app.security.policies import WorkflowState
from app.users.models import UserRole
from app.users.service import UserService
from app.visual_objects.models import (
    VisualObject,
    VisualObjectRegionBinding,
    VisualRegion,
)
from app.visual_objects.regions import RegionBounds, build_region_snapshot
from tests.releases.test_baseline_publish import (
    _approve,
    _asset_store,
    _import_candidate,
)


pytest_plugins = ("tests.imports.conftest",)


def _legacy_source_fingerprint(source_root: Path, manifest_path: Path) -> str:
    data = load_baseline_source(source_root)
    source_files = {
        record.source_file: record.source_hash
        for record in data.fingerprint_records
        if record.record_type != "molecule_proposal"
    }
    payload = {
        "fact_files": sorted(source_files.items()),
        "source_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _legacy_release(
    session,
    source: Release,
    *,
    release_key: str | None = None,
    source_fingerprint: str | None = None,
) -> Release:
    source.is_current = False
    session.flush()
    source_items = list(
        session.scalars(
            select(ReleaseItem)
            .where(ReleaseItem.release_id == source.id)
            .order_by(ReleaseItem.manifest_order)
        )
    )
    legacy_items = [
        item
        for item in source_items
        if item.object_kind
        not in {ObjectKind.VISUAL_REGION, ObjectKind.MOLECULE_PROPOSAL}
    ]
    metrics = dict(source.metrics)
    baseline_metrics = dict(metrics["baseline"])
    baseline_metrics["item_count"] = len(legacy_items)
    if source_fingerprint is not None:
        baseline_metrics["source_fingerprint"] = source_fingerprint
    metrics["baseline"] = baseline_metrics
    legacy = Release(
        release_key=release_key or f"legacy-{uuid4().hex[:8]}",
        title="Legacy baseline without machine evidence",
        notes="Test fixture",
        metrics=metrics,
        source_candidate_id=source.source_candidate_id,
        published_by_id=source.published_by_id,
        published_at=source.published_at,
        is_current=True,
        manifest_finalized=False,
    )
    session.add(legacy)
    session.flush()
    for item in legacy_items:
        session.add(
            ReleaseItem(
                release_id=legacy.id,
                object_id=item.object_id,
                revision_id=item.revision_id,
                paper_id=item.paper_id,
                object_kind=item.object_kind,
                manifest_order=item.manifest_order,
            )
        )
    session.flush()
    capture_release_artifact_manifest(session, legacy.id)
    legacy.manifest_finalized = True
    session.flush()
    return legacy


def test_backfill_adds_machine_evidence_in_a_successor_release_only(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory,
) -> None:
    source_root = baseline_fixture["source_root"]
    manifest_path = baseline_fixture["manifest_path"]
    expected = baseline_fixture["expected"]
    assert isinstance(source_root, Path)
    assert isinstance(manifest_path, Path)
    assert isinstance(expected, dict)

    with auth_session_factory.begin() as session:
        admin, candidate = _import_candidate(session, tmp_path, baseline_fixture)
        _approve(session, admin, candidate)
        baseline = publish_approved_baseline(
            session,
            candidate_id=candidate.id,
            actor_id=admin.id,
            title="Baseline",
            idempotency_key="baseline-for-backfill",
            asset_store=_asset_store(tmp_path, baseline_fixture),
        ).release
        legacy = _legacy_release(session, baseline, release_key="l" * 128)
        historical_manifest = get_release_artifact_manifest(session, baseline.id)
        assert historical_manifest is not None
        historical_hash = historical_manifest.content_hash
        human_review = dict(legacy.metrics["human_review"])

        result = backfill_machine_evidence(
            session,
            source_root=source_root,
            managed_asset_root=tmp_path / "managed",
            source_manifest_path=manifest_path,
            expected=expected,
            actor_id=admin.id,
            source_fingerprint=legacy.metrics["baseline"]["source_fingerprint"],
            idempotency_key="machine-evidence-1",
            asset_store=_asset_store(tmp_path, baseline_fixture),
        )

        assert result.idempotent is False
        assert result.release.id != legacy.id
        assert len(result.release.release_key) <= 128
        assert result.release.is_current is True
        assert result.release.metrics["human_review"] == human_review
        assert (
            result.release.metrics["baseline"]["source_fingerprint"]
            == legacy.metrics["baseline"]["source_fingerprint"]
        )
        advisory_locks = session.scalar(
            text(
                "SELECT count(*) FROM pg_locks "
                "WHERE locktype = 'advisory' AND pid = pg_backend_pid() AND granted"
            )
        )
        assert int(advisory_locks or 0) >= 1
        kinds = {
            item.object_kind
            for item in session.scalars(
                select(ReleaseItem).where(ReleaseItem.release_id == result.release.id)
            )
        }
        assert ObjectKind.MOLECULE_PROPOSAL in kinds
        assert ObjectKind.VISUAL_REGION in kinds
        result_item_count = session.scalar(
            select(func.count())
            .select_from(ReleaseItem)
            .where(ReleaseItem.release_id == result.release.id)
        )
        assert result.release.metrics["baseline"]["item_count"] == result_item_count
        current_manifest = get_release_artifact_manifest(session, baseline.id)
        assert current_manifest is not None
        assert current_manifest.content_hash == historical_hash

        repeated = backfill_machine_evidence(
            session,
            source_root=source_root,
            managed_asset_root=tmp_path / "managed",
            source_manifest_path=manifest_path,
            expected=expected,
            actor_id=admin.id,
            source_fingerprint=legacy.metrics["baseline"]["source_fingerprint"],
            idempotency_key="machine-evidence-1",
            asset_store=_asset_store(tmp_path, baseline_fixture),
        )
        assert repeated.idempotent is True
        assert repeated.release.id == result.release.id
        operation = session.scalar(
            select(ReleaseOperation).where(ReleaseOperation.operation_type == "machine_evidence")
        )
        assert operation is not None
        audit_events = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "release.machine_evidence_backfilled"
                )
            )
        )
        assert len(audit_events) == 1
        assert audit_events[0].release_id == result.release.id
        assert audit_events[0].details["after"]["added_proposals"] == result.added_proposals
        release_count = session.scalar(select(func.count()).select_from(Release))
        with pytest.raises(MachineEvidenceBackfillError, match="already contains"):
            backfill_machine_evidence(
                session,
                source_root=source_root,
                managed_asset_root=tmp_path / "managed",
                source_manifest_path=manifest_path,
                expected=expected,
                actor_id=admin.id,
                source_fingerprint=result.release.metrics["baseline"]["source_fingerprint"],
                idempotency_key="machine-evidence-no-op",
                asset_store=_asset_store(tmp_path, baseline_fixture),
            )
        assert session.scalar(select(func.count()).select_from(Release)) == release_count


def test_idempotent_backfill_replays_the_original_evidence_counts(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory,
) -> None:
    source_root = baseline_fixture["source_root"]
    manifest_path = baseline_fixture["manifest_path"]
    expected = baseline_fixture["expected"]
    assert isinstance(source_root, Path)
    assert isinstance(manifest_path, Path)
    assert isinstance(expected, dict)

    with auth_session_factory.begin() as session:
        admin, candidate = _import_candidate(session, tmp_path, baseline_fixture)
        _approve(session, admin, candidate)
        baseline = publish_approved_baseline(
            session,
            candidate_id=candidate.id,
            actor_id=admin.id,
            title="Baseline",
            idempotency_key="baseline-for-count-replay",
            asset_store=_asset_store(tmp_path, baseline_fixture),
        ).release
        legacy = _legacy_release(session, baseline)
        source_fingerprint = legacy.metrics["baseline"]["source_fingerprint"]
        result = backfill_machine_evidence(
            session,
            source_root=source_root,
            managed_asset_root=tmp_path / "managed",
            source_manifest_path=manifest_path,
            expected=expected,
            actor_id=admin.id,
            source_fingerprint=source_fingerprint,
            idempotency_key="machine-evidence-count-source",
            asset_store=_asset_store(tmp_path, baseline_fixture),
        )
        replay_key = "machine-evidence-count-replay"
        replay_operation = ReleaseOperation(
            operation_type="machine_evidence",
            actor_id=admin.id,
            idempotency_key=replay_key,
            request_hash=canonical_content_hash(
                {
                    "source_fingerprint": source_fingerprint,
                    "title": "Machine evidence backfill",
                    "notes": "",
                }
            ),
            target_release_id=legacy.id,
            replaced_release_id=legacy.id,
            result_release_id=result.release.id,
            reason="Count replay fixture",
            delta={"added_proposals": 7, "added_regions": 3},
        )
        session.add(replay_operation)
        session.flush()

        replay = backfill_machine_evidence(
            session,
            source_root=source_root,
            managed_asset_root=tmp_path / "managed",
            source_manifest_path=manifest_path,
            expected=expected,
            actor_id=admin.id,
            source_fingerprint=source_fingerprint,
            idempotency_key=replay_key,
            asset_store=_asset_store(tmp_path, baseline_fixture),
        )

        assert replay.idempotent is True
        assert replay.added_proposals == 7
        assert replay.added_regions == 3


def test_backfill_rejects_a_source_fingerprint_not_bound_to_current_baseline(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory,
) -> None:
    source_root = baseline_fixture["source_root"]
    manifest_path = baseline_fixture["manifest_path"]
    expected = baseline_fixture["expected"]
    assert isinstance(source_root, Path)
    assert isinstance(manifest_path, Path)
    assert isinstance(expected, dict)
    with auth_session_factory.begin() as session:
        admin, candidate = _import_candidate(session, tmp_path, baseline_fixture)
        _approve(session, admin, candidate)
        publish_approved_baseline(
            session,
            candidate_id=candidate.id,
            actor_id=admin.id,
            title="Baseline",
            idempotency_key="baseline-for-backfill-reject",
            asset_store=_asset_store(tmp_path, baseline_fixture),
        )
        with pytest.raises(MachineEvidenceBackfillError, match="fingerprint"):
            backfill_machine_evidence(
                session,
                source_root=source_root,
                managed_asset_root=tmp_path / "managed",
                source_manifest_path=manifest_path,
                expected=expected,
                actor_id=admin.id,
                source_fingerprint="f" * 64,
                idempotency_key="machine-evidence-reject",
                asset_store=_asset_store(tmp_path, baseline_fixture),
            )


def test_backfill_accepts_the_legacy_fingerprint_that_excluded_proposals(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory,
) -> None:
    source_root = baseline_fixture["source_root"]
    manifest_path = baseline_fixture["manifest_path"]
    expected = baseline_fixture["expected"]
    assert isinstance(source_root, Path)
    assert isinstance(manifest_path, Path)
    assert isinstance(expected, dict)
    legacy_fingerprint = _legacy_source_fingerprint(source_root, manifest_path)

    with auth_session_factory.begin() as session:
        admin, candidate = _import_candidate(session, tmp_path, baseline_fixture)
        _approve(session, admin, candidate)
        baseline = publish_approved_baseline(
            session,
            candidate_id=candidate.id,
            actor_id=admin.id,
            title="Baseline",
            idempotency_key="baseline-for-legacy-fingerprint",
            asset_store=_asset_store(tmp_path, baseline_fixture),
        ).release
        legacy = _legacy_release(
            session,
            baseline,
            source_fingerprint=legacy_fingerprint,
        )
        batch = session.get(ImportBatch, candidate.import_batch_id)
        assert batch is not None
        batch.source_fingerprint = legacy_fingerprint
        session.execute(
            delete(ImportStagingRecord).where(
                ImportStagingRecord.import_batch_id == batch.id,
                ImportStagingRecord.record_type == "molecule_proposal",
            )
        )
        session.flush()

        result = backfill_machine_evidence(
            session,
            source_root=source_root,
            managed_asset_root=tmp_path / "managed",
            source_manifest_path=manifest_path,
            expected=expected,
            actor_id=admin.id,
            source_fingerprint=legacy_fingerprint,
            idempotency_key="machine-evidence-legacy-fingerprint",
            asset_store=_asset_store(tmp_path, baseline_fixture),
        )

        assert result.release.is_current is True
        operation = session.get(ReleaseOperation, result.operation_id)
        assert operation is not None
        assert operation.delta["baseline_source_fingerprint"] == legacy_fingerprint
        assert operation.delta["evidence_source_fingerprint"] != legacy_fingerprint

        proposal_record = load_baseline_source(source_root).molecule_proposals[0]
        session.add(
            ImportStagingRecord(
                import_batch_id=batch.id,
                record_type=proposal_record.record_type,
                original_id=proposal_record.original_id,
                source_file=proposal_record.source_file,
                source_row_locator=proposal_record.source_row_locator,
                source_hash=proposal_record.source_hash,
                raw_values=proposal_record.raw_values,
                normalized_values=proposal_record.normalized_values,
            )
        )
        session.flush()
        release_count = session.scalar(select(func.count()).select_from(Release))
        with pytest.raises(MachineEvidenceBackfillError, match="already contains"):
            backfill_machine_evidence(
                session,
                source_root=source_root,
                managed_asset_root=tmp_path / "managed",
                source_manifest_path=manifest_path,
                expected=expected,
                actor_id=admin.id,
                source_fingerprint=legacy_fingerprint,
                idempotency_key="machine-evidence-legacy-fingerprint-no-op",
                asset_store=_asset_store(tmp_path, baseline_fixture),
            )
        assert session.scalar(select(func.count()).select_from(Release)) == release_count


def test_backfill_serializes_the_release_pointer_with_an_advisory_lock(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory,
) -> None:
    source_root = baseline_fixture["source_root"]
    manifest_path = baseline_fixture["manifest_path"]
    expected = baseline_fixture["expected"]
    assert isinstance(source_root, Path)
    assert isinstance(manifest_path, Path)
    assert isinstance(expected, dict)

    with auth_session_factory.begin() as session:
        admin, candidate = _import_candidate(session, tmp_path, baseline_fixture)
        _approve(session, admin, candidate)
        baseline = publish_approved_baseline(
            session,
            candidate_id=candidate.id,
            actor_id=admin.id,
            title="Baseline",
            idempotency_key="baseline-for-backfill-lock",
            asset_store=_asset_store(tmp_path, baseline_fixture),
        ).release
        legacy = _legacy_release(session, baseline)
        actor_id = admin.id
        source_fingerprint = legacy.metrics["baseline"]["source_fingerprint"]

    with auth_session_factory.begin() as session:
        before = session.scalar(
            text(
                "SELECT count(*) FROM pg_locks "
                "WHERE locktype = 'advisory' AND pid = pg_backend_pid() AND granted"
            )
        )
        assert int(before or 0) == 0

        backfill_machine_evidence(
            session,
            source_root=source_root,
            managed_asset_root=tmp_path / "managed",
            source_manifest_path=manifest_path,
            expected=expected,
            actor_id=actor_id,
            source_fingerprint=source_fingerprint,
            idempotency_key="machine-evidence-lock",
            asset_store=_asset_store(tmp_path, baseline_fixture),
        )

        after = session.scalar(
            text(
                "SELECT count(*) FROM pg_locks "
                "WHERE locktype = 'advisory' AND pid = pg_backend_pid() AND granted"
            )
        )
        assert int(after or 0) >= 1


def test_backfill_aborts_if_source_facts_change_after_reconciliation(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = baseline_fixture["source_root"]
    manifest_path = baseline_fixture["manifest_path"]
    expected = baseline_fixture["expected"]
    assert isinstance(source_root, Path)
    assert isinstance(manifest_path, Path)
    assert isinstance(expected, dict)

    with auth_session_factory.begin() as session:
        admin, candidate = _import_candidate(session, tmp_path, baseline_fixture)
        _approve(session, admin, candidate)
        baseline = publish_approved_baseline(
            session,
            candidate_id=candidate.id,
            actor_id=admin.id,
            title="Baseline",
            idempotency_key="baseline-for-backfill-source-race",
            asset_store=_asset_store(tmp_path, baseline_fixture),
        ).release
        legacy = _legacy_release(session, baseline)
        legacy_id = legacy.id
        actor_id = admin.id
        source_fingerprint = legacy.metrics["baseline"]["source_fingerprint"]

    proposal_csv = (
        source_root
        / "09_paper_review"
        / "auto_fill"
        / "first_page_molecule_proposals.csv"
    )
    original_reconcile = proposal_backfill_module.reconcile_loaded_baseline

    def reconcile_then_mutate(*args: object, **kwargs: object):
        report = original_reconcile(*args, **kwargs)
        proposal_csv.write_text(
            proposal_csv.read_text(encoding="utf-8") + "\n",
            encoding="utf-8",
        )
        return report

    monkeypatch.setattr(
        proposal_backfill_module,
        "reconcile_loaded_baseline",
        reconcile_then_mutate,
    )

    with pytest.raises(MachineEvidenceBackfillError, match="changed during backfill"):
        with auth_session_factory.begin() as session:
            backfill_machine_evidence(
                session,
                source_root=source_root,
                managed_asset_root=tmp_path / "managed",
                source_manifest_path=manifest_path,
                expected=expected,
                actor_id=actor_id,
                source_fingerprint=source_fingerprint,
                idempotency_key="machine-evidence-source-race",
                asset_store=_asset_store(tmp_path, baseline_fixture),
            )

    with auth_session_factory() as session:
        current = session.scalar(select(Release).where(Release.is_current.is_(True)))
        operation = session.scalar(
            select(ReleaseOperation).where(
                ReleaseOperation.operation_type == "machine_evidence"
            )
        )
        assert current is not None
        assert current.id == legacy_id
        assert operation is None


def test_backfill_keeps_active_changeset_base_and_excludes_draft_or_unrelated_evidence(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory,
) -> None:
    source_root = baseline_fixture["source_root"]
    manifest_path = baseline_fixture["manifest_path"]
    expected = baseline_fixture["expected"]
    assert isinstance(source_root, Path)
    assert isinstance(manifest_path, Path)
    assert isinstance(expected, dict)

    with auth_session_factory.begin() as session:
        admin, candidate = _import_candidate(session, tmp_path, baseline_fixture)
        _approve(session, admin, candidate)
        baseline = publish_approved_baseline(
            session,
            candidate_id=candidate.id,
            actor_id=admin.id,
            title="Baseline",
            idempotency_key="baseline-for-active-backfill",
            asset_store=_asset_store(tmp_path, baseline_fixture),
        ).release
        legacy = _legacy_release(session, baseline)
        paper_item = session.scalar(
            select(ReleaseItem).where(
                ReleaseItem.release_id == legacy.id,
                ReleaseItem.object_kind == ObjectKind.PAPER,
            )
        )
        proposal = session.scalar(select(MoleculeProposal))
        assert proposal is not None
        machine_revision = session.scalar(
            select(ObjectRevision).where(
                ObjectRevision.object_id == proposal.id,
                ObjectRevision.changeset_id.is_(None),
            )
        )
        assert paper_item is not None
        assert machine_revision is not None

        reviewer = UserService().create_user(
            session,
            username=f"backfill-reviewer-{uuid4().hex[:8]}",
            display_name="Backfill Reviewer",
            role=UserRole.REVIEWER,
            initial_password="Backfill reviewer password 2026!",
        )
        reviewer.must_change_password = False
        reviews = ReviewService()
        task = reviews.create_task(
            session,
            paper_id=paper_item.paper_id,
            assignee_id=reviewer.id,
            created_by_id=admin.id,
        )
        changeset = reviews.create_changeset(
            session,
            paper_id=paper_item.paper_id,
            actor_id=reviewer.id,
            review_task_id=task.id,
            base_release_id=legacy.id,
            title="Active legacy review",
            reason="Prove machine evidence backfill never rebases active work",
        )
        _, draft_revision, _ = MoleculeProposalReviewService().update(
            session,
            paper_id=paper_item.paper_id,
            proposal_id=proposal.id,
            actor_id=reviewer.id,
            changeset_id=changeset.id,
            expected_version=changeset.version,
            disposition=MoleculeProposalDisposition.REJECTED,
            rationale="Keep this Reviewer decision in the active changeset only",
        )

        source_region = session.scalar(select(VisualRegion))
        assert source_region is not None
        unrelated_region = VisualRegion(
            paper_id=paper_item.paper_id,
            region_key=f"reviewer-unrelated-{uuid4().hex[:8]}",
            asset_id=source_region.asset_id,
            page_number=source_region.page_number,
        )
        session.add(unrelated_region)
        session.flush()
        bounds = RegionBounds(x0=0.1, y0=0.1, x1=0.2, y1=0.2)
        RevisionService().create_revision(
            session,
            object_identity=unrelated_region,
            actor_id=admin.id,
            reason="Unrelated Region must not enter the machine backfill",
            snapshot=build_region_snapshot(
                region_key=unrelated_region.region_key,
                page_number=unrelated_region.page_number,
                bounds=bounds,
                rotation=0,
                region_id=unrelated_region.id,
            ),
            workflow_state=WorkflowState.APPROVED,
            region_bounds=(bounds.x0, bounds.y0, bounds.x1, bounds.y1),
            region_rotation=0,
        )
        visual = session.scalar(select(VisualObject))
        assert visual is not None
        session.add(
            VisualObjectRegionBinding(
                visual_object_id=visual.id,
                region_id=unrelated_region.id,
                changeset_id=changeset.id,
                operation="add",
                logical_key=f"region:{visual.id}:{unrelated_region.id}",
                role="reviewer-draft",
                note="Must remain private to the active changeset",
            )
        )
        session.flush()

        result = backfill_machine_evidence(
            session,
            source_root=source_root,
            managed_asset_root=tmp_path / "managed",
            source_manifest_path=manifest_path,
            expected=expected,
            actor_id=admin.id,
            source_fingerprint=legacy.metrics["baseline"]["source_fingerprint"],
            idempotency_key="machine-evidence-active-review",
            asset_store=_asset_store(tmp_path, baseline_fixture),
        )

        session.refresh(changeset)
        session.refresh(draft_revision)
        assert changeset.base_release_id == legacy.id
        assert draft_revision.workflow_state is WorkflowState.DRAFT
        assert draft_revision.is_current_published is False
        proposal_item = session.scalar(
            select(ReleaseItem).where(
                ReleaseItem.release_id == result.release.id,
                ReleaseItem.object_id == proposal.id,
            )
        )
        unrelated_item = session.scalar(
            select(ReleaseItem).where(
                ReleaseItem.release_id == result.release.id,
                ReleaseItem.object_id == unrelated_region.id,
            )
        )
        assert proposal_item is not None
        assert proposal_item.revision_id == machine_revision.id
        assert unrelated_item is None
        successor_manifest = get_release_artifact_manifest(session, result.release.id)
        assert successor_manifest is not None
        successor_bindings = successor_manifest.snapshot["bindings"]
        assert all(
            row["changeset_id"] is None
            for rows in successor_bindings.values()
            for row in rows
        )


@pytest.mark.parametrize(
    ("missing_kind", "expected_message"),
    [
        ("proposal", "no eligible machine revision"),
        ("region", "Region has no eligible machine revision"),
    ],
)
def test_backfill_rejects_existing_evidence_without_a_machine_revision(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory,
    monkeypatch: pytest.MonkeyPatch,
    missing_kind: str,
    expected_message: str,
) -> None:
    source_root = baseline_fixture["source_root"]
    manifest_path = baseline_fixture["manifest_path"]
    expected = baseline_fixture["expected"]
    assert isinstance(source_root, Path)
    assert isinstance(manifest_path, Path)
    assert isinstance(expected, dict)

    with auth_session_factory.begin() as session:
        admin, candidate = _import_candidate(session, tmp_path, baseline_fixture)
        _approve(session, admin, candidate)
        baseline = publish_approved_baseline(
            session,
            candidate_id=candidate.id,
            actor_id=admin.id,
            title="Baseline",
            idempotency_key="baseline-for-missing-machine-revision",
            asset_store=_asset_store(tmp_path, baseline_fixture),
        ).release
        legacy = _legacy_release(session, baseline)
        proposal = session.scalar(select(MoleculeProposal))
        region = session.scalar(select(VisualRegion))
        assert proposal is not None
        assert region is not None
        target_id = proposal.id if missing_kind == "proposal" else region.id
        actor_id = admin.id
        source_fingerprint = legacy.metrics["baseline"]["source_fingerprint"]

    original_machine_revision = proposal_backfill_module._machine_revision

    def missing_proposal_revision(session, object_id):
        if object_id == target_id:
            return None
        return original_machine_revision(session, object_id)

    monkeypatch.setattr(
        proposal_backfill_module,
        "_machine_revision",
        missing_proposal_revision,
    )

    with pytest.raises(
        MachineEvidenceBackfillError,
        match=expected_message,
    ):
        with auth_session_factory.begin() as session:
            backfill_machine_evidence(
                session,
                source_root=source_root,
                managed_asset_root=tmp_path / "managed",
                source_manifest_path=manifest_path,
                expected=expected,
                actor_id=actor_id,
                source_fingerprint=source_fingerprint,
                idempotency_key="machine-evidence-missing-revision",
                asset_store=_asset_store(tmp_path, baseline_fixture),
            )
