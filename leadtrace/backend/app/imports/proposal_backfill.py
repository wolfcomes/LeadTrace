from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assets.models import Asset
from app.assets.storage import LocalAssetStore
from app.audit.service import AuditService, canonical_content_hash
from app.imports.models import (
    ImportAssetLink,
    ImportBatch,
    ImportReleaseCandidate,
    ImportStagingRecord,
)
from app.imports.reconcile import (
    DEFAULT_EXPECTED_AGGREGATE,
    DEFAULT_SOURCE_MANIFEST,
    ReconciliationReport,
    load_baseline_source,
    reconcile_loaded_baseline,
    source_fingerprint_from_files,
    source_snapshot_is_unchanged,
)
from app.imports.service import (
    BaselineImporter,
    import_search_text,
    safe_import_snapshot,
)
from app.molecule_proposals.models import (
    MoleculeProposal,
    MoleculeProposalDisposition,
)
from app.papers.models import Paper
from app.releases.manifest import (
    build_release_artifact_snapshot,
    capture_release_artifact_manifest,
)
from app.releases.models import Release, ReleaseItem, ReleaseOperation
from app.releases.service import (
    assert_release_valid,
    get_current_release,
    lock_release_pointer,
)
from app.releases.validation import ReleaseValidationResult, validate_release
from app.revisions.models import ObjectKind, ObjectRevision
from app.revisions.service import RevisionService
from app.security.policies import WorkflowState
from app.users.models import User, UserRole
from app.visual_objects.models import (
    VisualObject,
    VisualObjectAssetBinding,
    VisualObjectRegionBinding,
    VisualRegion,
)
from app.visual_objects.regions import build_region_snapshot


class MachineEvidenceBackfillError(ValueError):
    """Raised when an evidence-only backfill cannot be safely applied."""


@dataclass(frozen=True, slots=True)
class MachineEvidenceBackfillResult:
    release: Release
    validation: ReleaseValidationResult
    idempotent: bool
    operation_id: UUID | None = None
    added_proposals: int = 0
    added_regions: int = 0


def _require_admin(session: Session, actor_id: UUID) -> User:
    actor = session.get(User, actor_id)
    if actor is None or not actor.is_enabled or actor.role is not UserRole.ADMIN:
        raise MachineEvidenceBackfillError("An enabled Admin is required")
    return actor


def _request_hash(
    *,
    source_fingerprint: str,
    title: str,
    notes: str,
) -> str:
    return canonical_content_hash(
        {
            "source_fingerprint": source_fingerprint,
            "title": title,
            "notes": notes,
        }
    )


def _operation_count(operation: ReleaseOperation, field: str) -> int:
    value = operation.delta.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MachineEvidenceBackfillError(
            "Idempotent backfill result has invalid evidence counts"
        )
    return value


def _asset_for(
    assets: Mapping[str, Asset],
    report: ReconciliationReport,
    *,
    record_type: str,
    original_id: str,
    link_role: str,
) -> Asset | None:
    linkage = getattr(report, "asset_linkage", None)
    references = getattr(linkage, "resolved", ())
    for reference in references:
        if (
            reference.record_type == record_type
            and reference.original_id == original_id
            and reference.link_role == link_role
        ):
            return assets.get(reference.manifest_path)
    return None


def _ensure_staged_record(session: Session, batch_id: UUID, record: object) -> bool:
    original_id = getattr(record, "original_id")
    record_type = getattr(record, "record_type")
    existing = session.scalar(
        select(ImportStagingRecord).where(
            ImportStagingRecord.import_batch_id == batch_id,
            ImportStagingRecord.record_type == record_type,
            ImportStagingRecord.original_id == original_id,
        )
    )
    if existing is not None:
        return False
    session.add(
        ImportStagingRecord(
            id=uuid4(),
            import_batch_id=batch_id,
            record_type=record_type,
            original_id=original_id,
            source_file=getattr(record, "source_file"),
            source_row_locator=getattr(record, "source_row_locator"),
            source_hash=getattr(record, "source_hash"),
            raw_values=dict(getattr(record, "raw_values")),
            normalized_values=dict(getattr(record, "normalized_values")),
        )
    )
    return True


def _ensure_asset_link(
    session: Session,
    *,
    batch_id: UUID,
    record_type: str,
    original_id: str,
    link_role: str,
    asset: Asset | None,
    source_reference: str | None,
) -> bool:
    if asset is None or source_reference is None:
        return False
    existing = session.scalar(
        select(ImportAssetLink).where(
            ImportAssetLink.import_batch_id == batch_id,
            ImportAssetLink.record_type == record_type,
            ImportAssetLink.original_id == original_id,
            ImportAssetLink.link_role == link_role,
            ImportAssetLink.asset_id == asset.id,
        )
    )
    if existing is None:
        session.add(
            ImportAssetLink(
                id=uuid4(),
                import_batch_id=batch_id,
                record_type=record_type,
                original_id=original_id,
                asset_id=asset.id,
                link_role=link_role,
                source_reference=source_reference,
            )
        )
        return True
    return False


def _source_reference(
    report: ReconciliationReport,
    *,
    record_type: str,
    original_id: str,
    link_role: str,
) -> str | None:
    linkage = getattr(report, "asset_linkage", None)
    for reference in getattr(linkage, "resolved", ()):
        if (
            reference.record_type == record_type
            and reference.original_id == original_id
            and reference.link_role == link_role
        ):
            return reference.manifest_path
    return None


def _machine_revision(
    session: Session,
    object_id: UUID,
) -> ObjectRevision | None:
    """Return the original changeset-free machine revision, never a Reviewer draft."""

    return session.scalar(
        select(ObjectRevision)
        .where(
            ObjectRevision.object_id == object_id,
            ObjectRevision.changeset_id.is_(None),
            ObjectRevision.workflow_state.in_(
                (WorkflowState.APPROVED, WorkflowState.PUBLISHED)
            ),
        )
        .order_by(ObjectRevision.revision_number, ObjectRevision.id)
        .limit(1)
    )


def _prepare_machine_revision_for_publication(revision: ObjectRevision) -> None:
    if revision.workflow_state is WorkflowState.APPROVED:
        revision.workflow_state = WorkflowState.PUBLISHED
        revision.is_current_published = True
        return
    if (
        revision.workflow_state is not WorkflowState.PUBLISHED
        or not revision.is_current_published
    ):
        raise MachineEvidenceBackfillError(
            "Machine evidence revision is not eligible for publication"
        )


def backfill_machine_evidence(
    session: Session,
    *,
    source_root: Path,
    managed_asset_root: Path,
    actor_id: UUID,
    source_fingerprint: str,
    idempotency_key: str,
    source_manifest_path: Path = DEFAULT_SOURCE_MANIFEST,
    expected: dict[str, object] | None = None,
    expected_path: Path | None = DEFAULT_EXPECTED_AGGREGATE,
    title: str | None = None,
    notes: str = "",
    asset_store: LocalAssetStore | None = None,
    audit_ip_address: str = "local-operation",
    audit_request_id: str | None = None,
) -> MachineEvidenceBackfillResult:
    """Append missing machine evidence to the current baseline in a successor Release.

    Existing Release manifests, revisions, and active changesets are never edited.
    """

    lock_release_pointer(session)
    actor = _require_admin(session, actor_id)
    operation_key = idempotency_key.strip()
    if not operation_key or len(operation_key) > 200:
        raise MachineEvidenceBackfillError(
            "idempotency_key must contain 1 to 200 characters"
        )
    clean_title = (title or "Machine evidence backfill").strip()
    clean_notes = notes.strip()
    if not clean_title or len(clean_title) > 255:
        raise MachineEvidenceBackfillError("title must contain 1 to 255 characters")
    if len(clean_notes) > 4000:
        raise MachineEvidenceBackfillError(
            "notes must contain at most 4000 characters"
        )

    current = get_current_release(session)
    request_hash = _request_hash(
        source_fingerprint=source_fingerprint,
        title=clean_title,
        notes=clean_notes,
    )
    existing_operation = session.scalar(
        select(ReleaseOperation)
        .where(
            ReleaseOperation.actor_id == actor.id,
            ReleaseOperation.operation_type == "machine_evidence",
            ReleaseOperation.idempotency_key == operation_key,
        )
        .with_for_update()
    )
    if existing_operation is not None:
        if existing_operation.request_hash != request_hash:
            raise MachineEvidenceBackfillError(
                "Idempotency key was already used for another backfill"
            )
        existing_release = session.get(
            Release,
            existing_operation.result_release_id,
        )
        if existing_release is None:
            raise MachineEvidenceBackfillError(
                "Idempotent backfill result is unavailable"
            )
        validation = validate_release(
            session,
            existing_release.id,
            asset_store=asset_store,
        )
        assert_release_valid(validation)
        return MachineEvidenceBackfillResult(
            release=existing_release,
            validation=validation,
            idempotent=True,
            operation_id=existing_operation.id,
            added_proposals=_operation_count(
                existing_operation,
                "added_proposals",
            ),
            added_regions=_operation_count(existing_operation, "added_regions"),
        )

    baseline = current.metrics.get("baseline")
    if not isinstance(baseline, Mapping):
        raise MachineEvidenceBackfillError("Current Release is not tied to a baseline import")
    baseline_fingerprint = baseline.get("source_fingerprint")
    if baseline_fingerprint != source_fingerprint:
        raise MachineEvidenceBackfillError(
            "Source fingerprint is not tied to the current baseline"
        )
    if current.source_candidate_id is None:
        raise MachineEvidenceBackfillError("Current Release has no baseline candidate")
    candidate = session.get(ImportReleaseCandidate, current.source_candidate_id)
    batch = session.get(ImportBatch, candidate.import_batch_id) if candidate else None
    if candidate is None or batch is None or batch.source_fingerprint != source_fingerprint:
        raise MachineEvidenceBackfillError(
            "Source fingerprint is not tied to the current baseline import"
        )

    staged_rows = list(
        session.execute(
            select(
                ImportStagingRecord.record_type,
                ImportStagingRecord.source_file,
                ImportStagingRecord.source_hash,
            ).where(ImportStagingRecord.import_batch_id == batch.id)
        )
    )
    staged_source_files = {
        source_file: source_hash for _, source_file, source_hash in staged_rows
    }
    legacy_source_files = {
        source_file: source_hash
        for record_type, source_file, source_hash in staged_rows
        if record_type != "molecule_proposal"
    }
    staged_fingerprints = {
        source_fingerprint_from_files(source_files, source_manifest_path)
        for source_files in (staged_source_files, legacy_source_files)
    }
    if source_fingerprint not in staged_fingerprints:
        raise MachineEvidenceBackfillError(
            "Source fingerprint is not tied to the staged baseline files"
        )

    data = load_baseline_source(source_root)
    report = reconcile_loaded_baseline(
        source_root,
        data,
        expected=expected,
        expected_path=expected_path,
        source_manifest_path=source_manifest_path,
    )
    if not report.matches_expected or any(report.integrity.values()):
        raise MachineEvidenceBackfillError("Source reconcile failed")
    evidence_source_fingerprint = report.source_fingerprint

    importer = BaselineImporter(
        source_root,
        managed_asset_root=managed_asset_root,
        expected=expected,
        expected_path=expected_path,
        source_manifest_path=source_manifest_path,
    )
    assets = importer.register_assets(session, batch.id, report)
    system_actor = importer.system_actor(session)
    current_items = list(
        session.scalars(
            select(ReleaseItem)
            .where(ReleaseItem.release_id == current.id)
            .order_by(ReleaseItem.manifest_order, ReleaseItem.id)
        )
    )
    current_paper_ids = {
        item.object_id
        for item in current_items
        if item.object_kind is ObjectKind.PAPER
    }
    current_visual_ids = {
        item.object_id
        for item in current_items
        if item.object_kind is ObjectKind.VISUAL_OBJECT
    }
    papers = {
        paper.paper_key: paper
        for paper in session.scalars(
            select(Paper).where(Paper.id.in_(current_paper_ids))
        )
    }
    visuals = {
        (visual.paper_id, visual.object_key): visual
        for visual in session.scalars(
            select(VisualObject).where(VisualObject.id.in_(current_visual_ids))
        )
    }
    page_dimensions: dict[tuple[UUID, int], tuple[float, float]] = {}
    source_store = importer.manifest_workspace_root()
    pdf_store = LocalAssetStore(
        managed_asset_root,
        source_roots={"baseline": source_store},
    )
    existing_regions = {
        (region.paper_id, region.region_key): region
        for region in session.scalars(select(VisualRegion))
    }
    region_by_visual: dict[UUID, VisualRegion] = {}
    regions_to_publish: dict[UUID, VisualRegion] = {}
    region_revisions: dict[UUID, ObjectRevision] = {}
    new_regions = 0
    new_proposals = 0
    evidence_changed = False

    for record in data.visual_objects:
        paper_key = record.normalized_values.get("paper_id")
        paper = papers.get(str(paper_key))
        visual = visuals.get((paper.id, record.original_id)) if paper else None
        if paper is None or visual is None:
            raise MachineEvidenceBackfillError(
                f"Visual object {record.original_id!r} is not present in the baseline Release"
            )
        source_asset = _asset_for(
            assets,
            report,
            record_type="visual_object",
            original_id=record.original_id,
            link_role="visual_source_pdf",
        )
        crop_asset = _asset_for(
            assets,
            report,
            record_type="visual_object",
            original_id=record.original_id,
            link_role="visual_crop",
        )
        source_ref = _source_reference(
            report,
            record_type="visual_object",
            original_id=record.original_id,
            link_role="visual_source_pdf",
        )
        crop_ref = _source_reference(
            report,
            record_type="visual_object",
            original_id=record.original_id,
            link_role="visual_crop",
        )
        evidence_changed |= _ensure_asset_link(
            session,
            batch_id=batch.id,
            record_type="visual_object",
            original_id=record.original_id,
            link_role="visual_source_pdf",
            asset=source_asset,
            source_reference=source_ref,
        )
        evidence_changed |= _ensure_asset_link(
            session,
            batch_id=batch.id,
            record_type="visual_object",
            original_id=record.original_id,
            link_role="visual_crop",
            asset=crop_asset,
            source_reference=crop_ref,
        )
        region_key = f"{record.original_id}:source"
        region = existing_regions.get((paper.id, region_key))
        if region is None and source_asset is not None:
            try:
                page_number, bounds = importer.source_region_bounds(
                    record,
                    source_asset=source_asset,
                    source_store=pdf_store,
                    page_dimensions=page_dimensions,
                )
            except (OSError, RuntimeError, ValueError):
                page_number = None
                bounds = None
            if page_number is not None and bounds is not None:
                region = VisualRegion(
                    id=uuid4(),
                    paper_id=paper.id,
                    region_key=region_key,
                    asset_id=source_asset.id,
                    page_number=page_number,
                )
                session.add(region)
                session.flush()
                snapshot = build_region_snapshot(
                    region_key=region.region_key,
                    page_number=page_number,
                    bounds=bounds,
                    rotation=0,
                    region_id=region.id,
                )
                snapshot["provenance"] = {
                    "candidate_id": record.normalized_values.get("candidate_id"),
                    "object_id": record.original_id,
                }
                region_revisions[region.id] = RevisionService().create_revision(
                    session,
                    object_identity=region,
                    actor_id=system_actor.id,
                    reason="Backfill authoritative source Region",
                    snapshot=snapshot,
                    workflow_state=WorkflowState.APPROVED,
                    region_bounds=(bounds.x0, bounds.y0, bounds.x1, bounds.y1),
                    region_rotation=0,
                )
                existing_regions[(paper.id, region_key)] = region
                new_regions += 1
                evidence_changed = True
        if region is not None:
            region_revision = region_revisions.get(region.id)
            if region_revision is None:
                region_revision = _machine_revision(session, region.id)
                if region_revision is None:
                    raise MachineEvidenceBackfillError(
                        "Existing source Region has no eligible machine revision"
                    )
                region_revisions[region.id] = region_revision
            region_by_visual[visual.id] = region
            regions_to_publish[region.id] = region
            binding = session.scalar(
                select(VisualObjectRegionBinding).where(
                    VisualObjectRegionBinding.visual_object_id == visual.id,
                    VisualObjectRegionBinding.region_id == region.id,
                    VisualObjectRegionBinding.changeset_id.is_(None),
                )
            )
            if binding is None:
                session.add(
                    VisualObjectRegionBinding(
                        id=uuid4(),
                        visual_object_id=visual.id,
                        region_id=region.id,
                        changeset_id=None,
                        operation="add",
                        logical_key=f"region:{visual.id}:{region.id}",
                        role="source",
                        note="Machine evidence backfill",
                    )
                )
                evidence_changed = True
        if crop_asset is not None:
            binding = session.scalar(
                select(VisualObjectAssetBinding).where(
                    VisualObjectAssetBinding.visual_object_id == visual.id,
                    VisualObjectAssetBinding.asset_id == crop_asset.id,
                    VisualObjectAssetBinding.changeset_id.is_(None),
                )
            )
            if binding is None:
                session.add(
                    VisualObjectAssetBinding(
                        id=uuid4(),
                        visual_object_id=visual.id,
                        asset_id=crop_asset.id,
                        changeset_id=None,
                        operation="add",
                        logical_key=f"asset:{visual.id}:{crop_asset.id}",
                        role="crop",
                        is_primary=True,
                    )
                )
                evidence_changed = True

    session.flush()
    proposals_to_publish: list[tuple[MoleculeProposal, ObjectRevision]] = []
    for record in data.molecule_proposals:
        paper_key = record.normalized_values.get("paper_id")
        object_key = record.normalized_values.get("object_id")
        paper = papers.get(str(paper_key))
        visual = visuals.get((paper.id, str(object_key))) if paper else None
        if paper is None or visual is None:
            raise MachineEvidenceBackfillError(
                f"Molecule proposal {record.original_id!r} references an unknown baseline object"
            )
        proposal_key = record.normalized_values.get("proposal_key")
        model_run_key = record.normalized_values.get("model_run_key")
        if not isinstance(proposal_key, str) or not isinstance(model_run_key, str):
            raise MachineEvidenceBackfillError(
                f"Molecule proposal {record.original_id!r} has an invalid identity"
            )
        existing = session.scalar(
            select(MoleculeProposal).where(
                MoleculeProposal.paper_id == paper.id,
                MoleculeProposal.visual_object_id == visual.id,
                MoleculeProposal.proposal_key == proposal_key,
                MoleculeProposal.model_run_key == model_run_key,
            )
        )
        if existing is not None:
            existing_revision = _machine_revision(session, existing.id)
            if existing_revision is None:
                raise MachineEvidenceBackfillError(
                    "Existing molecule proposal has no eligible machine revision"
                )
            proposals_to_publish.append((existing, existing_revision))
            continue
        crop_asset = _asset_for(
            assets,
            report,
            record_type="molecule_proposal",
            original_id=record.original_id,
            link_role="proposal_crop",
        )
        crop_ref = _source_reference(
            report,
            record_type="molecule_proposal",
            original_id=record.original_id,
            link_role="proposal_crop",
        )
        evidence_changed |= _ensure_asset_link(
            session,
            batch_id=batch.id,
            record_type="molecule_proposal",
            original_id=record.original_id,
            link_role="proposal_crop",
            asset=crop_asset,
            source_reference=crop_ref,
        )
        region = region_by_visual.get(visual.id)
        proposal = MoleculeProposal(
            id=uuid4(),
            paper_id=paper.id,
            visual_object_id=visual.id,
            proposal_key=proposal_key,
            model_run_key=model_run_key,
            crop_asset_id=crop_asset.id if crop_asset else None,
            source_region_id=region.id if region else None,
        )
        session.add(proposal)
        session.flush()
        snapshot = safe_import_snapshot(record, proposal)
        revision = RevisionService().create_revision(
            session,
            object_identity=proposal,
            actor_id=system_actor.id,
            reason="Backfill immutable machine OCSR evidence",
            snapshot=snapshot,
            workflow_state=WorkflowState.APPROVED,
            search_text=import_search_text(record),
            proposal_disposition=MoleculeProposalDisposition.PENDING.value,
        )
        evidence_changed |= _ensure_staged_record(session, batch.id, record)
        proposals_to_publish.append((proposal, revision))
        new_proposals += 1
        evidence_changed = True

    session.flush()
    next_order = max((item.manifest_order for item in current_items), default=0)
    release_items: list[tuple[UUID, UUID, UUID, ObjectKind, int]] = [
        (item.object_id, item.revision_id, item.paper_id, item.object_kind, item.manifest_order)
        for item in current_items
    ]
    current_object_ids = {item.object_id for item in current_items}
    for region in sorted(regions_to_publish.values(), key=lambda value: str(value.id)):
        revision = region_revisions.get(region.id)
        if revision is None or region.id in current_object_ids:
            continue
        _prepare_machine_revision_for_publication(revision)
        next_order += 1
        release_items.append(
            (
                region.id,
                revision.id,
                region.paper_id,
                ObjectKind.VISUAL_REGION,
                next_order,
            )
        )
        current_object_ids.add(region.id)
        evidence_changed = True
    for proposal, revision in sorted(proposals_to_publish, key=lambda value: str(value[0].id)):
        if proposal.id in current_object_ids:
            continue
        _prepare_machine_revision_for_publication(revision)
        next_order += 1
        release_items.append(
            (
                proposal.id,
                revision.id,
                proposal.paper_id,
                ObjectKind.MOLECULE_PROPOSAL,
                next_order,
            )
        )
        current_object_ids.add(proposal.id)
        evidence_changed = True

    if not evidence_changed:
        raise MachineEvidenceBackfillError(
            "Current Release already contains all available machine evidence"
        )
    if not source_snapshot_is_unchanged(
        source_root,
        data,
        source_manifest_path,
        evidence_source_fingerprint,
    ):
        raise MachineEvidenceBackfillError(
            "Baseline source facts changed during backfill"
        )

    release_metrics = dict(current.metrics)
    baseline_metrics = dict(baseline)
    baseline_metrics["item_count"] = len(release_items)
    release_metrics["baseline"] = baseline_metrics
    new_release = Release(
        release_key=f"machine-evidence-{current.id}-{uuid4().hex[:8]}",
        title=clean_title,
        notes=clean_notes,
        metrics=release_metrics,
        source_candidate_id=current.source_candidate_id,
        published_by_id=actor.id,
        published_at=datetime.now(UTC),
        is_current=False,
        manifest_finalized=False,
    )
    session.add(new_release)
    session.flush()
    session.add_all(
        [
            ReleaseItem(
                release_id=new_release.id,
                object_id=object_id,
                revision_id=revision_id,
                paper_id=paper_id,
                object_kind=kind,
                manifest_order=order,
            )
            for object_id, revision_id, paper_id, kind, order in release_items
        ]
    )
    session.flush()
    snapshot = build_release_artifact_snapshot(session, new_release.id)
    capture_release_artifact_manifest(session, new_release.id, snapshot=snapshot)
    new_release.manifest_finalized = True
    session.flush()
    validation = validate_release(session, new_release.id, asset_store=asset_store)
    assert_release_valid(validation)
    current.is_current = False
    session.flush([current])
    new_release.is_current = True
    session.flush([new_release])
    operation_id = uuid4()
    operation = ReleaseOperation(
        id=operation_id,
        operation_type="machine_evidence",
        actor_id=actor.id,
        idempotency_key=operation_key,
        request_hash=request_hash,
        target_release_id=current.id,
        replaced_release_id=current.id,
        result_release_id=new_release.id,
        reason=clean_notes or "Append machine evidence to the current baseline",
        delta={
            "added_proposals": new_proposals,
            "added_regions": new_regions,
            "active_changesets_rebased": 0,
            "source_fingerprint": source_fingerprint,
            "baseline_source_fingerprint": source_fingerprint,
            "evidence_source_fingerprint": evidence_source_fingerprint,
        },
    )
    session.add(operation)
    session.flush()
    after = {
        "release_id": str(new_release.id),
        "release_key": new_release.release_key,
        "replaced_release_id": str(current.id),
        "added_proposals": new_proposals,
        "added_regions": new_regions,
    }
    AuditService().append_event(
        session,
        actor_id=actor.id,
        action="release.machine_evidence_backfilled",
        target_type="release",
        target_id=new_release.id,
        paper_id=None,
        changeset_id=None,
        release_id=new_release.id,
        ip_address=audit_ip_address,
        request_id=audit_request_id or f"machine-evidence-{operation_id}",
        result="success",
        reason=clean_notes or "Appended machine evidence to the current baseline",
        before_hash=canonical_content_hash({"release_id": str(current.id)}),
        after_hash=canonical_content_hash(after),
        details={"after": after},
    )
    return MachineEvidenceBackfillResult(
        release=new_release,
        validation=validation,
        idempotent=False,
        operation_id=operation_id,
        added_proposals=new_proposals,
        added_regions=new_regions,
    )


__all__ = [
    "MachineEvidenceBackfillError",
    "MachineEvidenceBackfillResult",
    "backfill_machine_evidence",
]
