from __future__ import annotations

import base64
import binascii
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assets.models import Asset
from app.molecule_proposals.models import (
    MoleculeProposal,
    MoleculeProposalDisposition,
)
from app.papers.models import Paper
from app.releases.manifest import (
    draft_binding_delta_for_changeset,
    get_release_artifact_manifest,
    merge_binding_snapshots,
)
from app.releases.models import Release, ReleaseItem
from app.releases.service import get_current_release
from app.revisions.models import ObjectKind, ObjectRevision
from app.reviews.attestations import PaperReviewScopeService
from app.reviews.completeness import QueueState, assess_object
from app.reviews.models import (
    Changeset,
    ChangesetItem,
    PaperReviewAttestation,
    PaperReviewScope,
    ReviewTask,
)
from app.structures.models import Structure
from app.visual_objects.models import VisualObject, VisualRegion


class WorkspaceNotFound(LookupError):
    """The changeset or one of its scoped resources is not visible."""


class WorkspaceConflict(RuntimeError):
    """The workspace changed while its version-consistent projection was built."""


class WorkspaceQueryError(ValueError):
    """A queue filter or pagination cursor is invalid."""


_QUEUE_PRIORITY = {state.value: index for index, state in enumerate(QueueState)}


def _safe_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for nested_key, nested_value in value.items():
            name = str(nested_key)
            normalized = name.casefold()
            if (
                normalized
                in {"storage_key", "source_pdf", "crop_path", "source_crop_path"}
                or normalized.endswith("_path")
                or normalized.endswith("_filepath")
            ):
                continue
            result[name] = _safe_value(nested_value)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_safe_value(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    return value


def asset_payload(asset: Asset | None) -> dict[str, object] | None:
    if asset is None:
        return None
    return {
        "id": str(asset.id),
        "url": f"/api/v1/assets/{asset.id}/content",
        "original_filename": asset.original_filename,
        "sha256": asset.sha256,
        "byte_size": asset.byte_size,
        "mime_type": asset.mime_type,
        "width": asset.width,
        "height": asset.height,
        "page_count": asset.page_count,
        "category": asset.category.value,
        "access_level": asset.access_level.value,
    }


@dataclass(frozen=True, slots=True)
class _ScopedItem:
    item: ReleaseItem
    revision: ObjectRevision


def _revision_for_item(
    session: Session,
    *,
    changeset_items: Mapping[UUID, ChangesetItem],
    item: ReleaseItem,
) -> ObjectRevision:
    change = changeset_items.get(item.object_id)
    revision_id = (
        change.proposed_revision_id
        if change is not None and change.proposed_revision_id is not None
        else item.revision_id
    )
    revision = session.get(ObjectRevision, revision_id)
    if revision is None or revision.object_id != item.object_id:
        raise WorkspaceConflict("Workspace revision is missing or crossed its object")
    return revision


def _scoped_items(
    session: Session,
    *,
    changeset: Changeset,
    release: Release,
) -> list[_ScopedItem]:
    changeset_items = {
        item.object_id: item
        for item in session.scalars(
            select(ChangesetItem)
            .where(ChangesetItem.changeset_id == changeset.id)
            .order_by(ChangesetItem.sequence, ChangesetItem.id)
        )
    }
    release_items = list(
        session.scalars(
            select(ReleaseItem)
            .where(
                ReleaseItem.release_id == release.id,
                ReleaseItem.paper_id == changeset.paper_id,
            )
            .order_by(ReleaseItem.manifest_order, ReleaseItem.id)
        )
    )
    by_object = {item.object_id: item for item in release_items}
    rows: list[_ScopedItem] = []
    for item in release_items:
        rows.append(
            _ScopedItem(
                item=item,
                revision=_revision_for_item(
                    session,
                    changeset_items=changeset_items,
                    item=item,
                ),
            )
        )
    for item in changeset_items.values():
        if item.object_id in by_object or item.proposed_revision_id is None:
            continue
        revision = session.get(ObjectRevision, item.proposed_revision_id)
        if revision is None:
            raise WorkspaceConflict("Changeset proposed revision is missing")
        rows.append(
            _ScopedItem(
                item=ReleaseItem(
                    release_id=release.id,
                    object_id=item.object_id,
                    revision_id=revision.id,
                    paper_id=item.paper_id,
                    object_kind=ObjectKind(item.object_kind),
                    manifest_order=10**9 + item.sequence,
                ),
                revision=revision,
            )
        )
    return rows


def _proposal_review(
    proposal: MoleculeProposal,
    revision: ObjectRevision,
) -> dict[str, object]:
    snapshot = revision.snapshot
    review = snapshot.get("review") if isinstance(snapshot, Mapping) else None
    raw_values = snapshot.get("raw_values") if isinstance(snapshot, Mapping) else None
    normalized_values = (
        snapshot.get("normalized_values") if isinstance(snapshot, Mapping) else None
    )
    return {
        "id": str(proposal.id),
        "paper_id": str(proposal.paper_id),
        "visual_object_id": str(proposal.visual_object_id),
        "proposal_key": proposal.proposal_key,
        "model_run_key": proposal.model_run_key,
        "revision_id": str(revision.id),
        "disposition": str(
            revision.proposal_disposition
            or MoleculeProposalDisposition.PENDING.value
        ),
        "machine": {
            "raw_values": _safe_value(
                raw_values if isinstance(raw_values, Mapping) else {}
            ),
            "normalized_values": _safe_value(
                normalized_values if isinstance(normalized_values, Mapping) else {}
            ),
        },
        "review": _safe_value(review if isinstance(review, Mapping) else {}),
    }


def _object_queue_state(
    *,
    revision: ObjectRevision,
    proposal_revision: ObjectRevision | None,
    source_ready: bool,
    structure_ready: bool,
) -> tuple[QueueState, bool, tuple[str, ...]]:
    blockers = revision.snapshot.get("review_blockers", [])
    blockers = blockers if isinstance(blockers, list) else []
    if proposal_revision is None:
        state = assess_object(
            object_kind=ObjectKind.VISUAL_OBJECT.value,
            review_blockers=blockers,
            requires_ocsr=True,
            proposal_dispositions=[],
            source_ready=source_ready,
            structure_ready=structure_ready,
        )
    else:
        disposition = proposal_revision.proposal_disposition or "pending"
        review = proposal_revision.snapshot.get("review")
        review = review if isinstance(review, Mapping) else {}
        resulting_structure_id = review.get("resulting_structure_id")
        state = assess_object(
            object_kind=ObjectKind.VISUAL_OBJECT.value,
            review_blockers=blockers,
            requires_ocsr=True,
            proposal_dispositions=[str(disposition)],
            source_ready=source_ready,
            structure_ready=structure_ready and bool(resulting_structure_id),
        )
    return state.state, state.blocking, state.reasons


def _proposal_source_ready(
    session: Session,
    *,
    proposal: MoleculeProposal | None,
    region: VisualRegion | None,
    paper_id: UUID,
) -> bool:
    if (
        proposal is None
        or proposal.paper_id != paper_id
        or proposal.crop_asset_id is None
        or proposal.source_region_id is None
        or region is None
        or region.id != proposal.source_region_id
        or region.paper_id != paper_id
        or region.asset_id is None
    ):
        return False
    return (
        session.get(Asset, proposal.crop_asset_id) is not None
        and session.get(Asset, region.asset_id) is not None
    )


def _proposal_structure_ready(
    session: Session,
    *,
    revision: ObjectRevision | None,
    paper_id: UUID,
) -> bool:
    if revision is None:
        return False
    disposition = str(revision.proposal_disposition or "pending")
    if disposition in {
        MoleculeProposalDisposition.REJECTED.value,
        MoleculeProposalDisposition.NOT_APPLICABLE.value,
    }:
        return True
    review = revision.snapshot.get("review")
    review = review if isinstance(review, Mapping) else {}
    normalized = revision.snapshot.get("normalized_values")
    normalized = normalized if isinstance(normalized, Mapping) else {}
    value = review.get("resulting_structure_id") or normalized.get(
        "resulting_structure_id"
    )
    if not value:
        return False
    try:
        structure = session.get(Structure, UUID(str(value)))
    except (TypeError, ValueError):
        return False
    return structure is not None and structure.paper_id == paper_id


def _minimum_confidence(revision: ObjectRevision | None) -> float:
    if revision is None:
        return 1.0
    normalized = revision.snapshot.get("normalized_values")
    value = (
        normalized.get("min_token_confidence")
        if isinstance(normalized, Mapping)
        else None
    )
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return 1.0
    return parsed if 0 <= parsed <= 1 else 1.0


def _encode_cursor(values: Sequence[object]) -> str:
    encoded = json.dumps(list(values), separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> tuple[object, ...]:
    try:
        padding = "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(value + padding)
        parsed = json.loads(decoded)
    except (
        binascii.Error,
        ValueError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as error:
        raise WorkspaceQueryError("Queue cursor is invalid") from error
    if not isinstance(parsed, list) or len(parsed) != 7:
        raise WorkspaceQueryError("Queue cursor is invalid")
    if (
        not isinstance(parsed[0], int)
        or not isinstance(parsed[1], (int, float))
        or not isinstance(parsed[2], int)
        or not all(isinstance(item, str) for item in parsed[3:])
    ):
        raise WorkspaceQueryError("Queue cursor is invalid")
    return tuple(parsed)


def _progress_for_items(
    scoped: Sequence[_ScopedItem],
) -> dict[str, object]:
    states: list[QueueState] = []
    for row in scoped:
        if row.item.object_kind is ObjectKind.VISUAL_OBJECT:
            blockers = row.revision.snapshot.get("review_blockers", [])
            blockers = blockers if isinstance(blockers, list) else []
            state = assess_object(
                object_kind=ObjectKind.VISUAL_OBJECT.value,
                review_blockers=blockers,
                requires_ocsr=False,
                proposal_dispositions=[],
                source_ready=True,
                structure_ready=True,
            ).state
        elif row.item.object_kind is ObjectKind.MOLECULE_PROPOSAL:
            disposition = row.revision.proposal_disposition or "pending"
            state = assess_object(
                object_kind=ObjectKind.MOLECULE_PROPOSAL.value,
                requires_ocsr=True,
                proposal_dispositions=[str(disposition)],
                source_ready=True,
                structure_ready=False,
            ).state
        else:
            state = QueueState.COMPLETE
        states.append(state)
    by_kind: dict[str, dict[str, int]] = {}
    for row, state in zip(scoped, states, strict=True):
        counters = by_kind.setdefault(
            row.item.object_kind.value,
            {"total": 0, "resolved": 0, "blockers": 0},
        )
        counters["total"] += 1
        if state is QueueState.COMPLETE:
            counters["resolved"] += 1
        else:
            counters["blockers"] += 1
    progress = {
        "scope_count": len(states),
        "resolved_count": sum(state is QueueState.COMPLETE for state in states),
        "blocker_count": sum(state is not QueueState.COMPLETE for state in states),
        "by_kind": by_kind,
    }
    return progress


def _scope_progress_payload(
    scope: PaperReviewScope,
    states: Sequence[object],
) -> dict[str, object]:
    scope_items = scope.snapshot.get("items")
    if not isinstance(scope_items, list) or len(scope_items) != len(states):
        raise WorkspaceConflict("Workspace review scope progress is inconsistent")
    by_kind: dict[str, dict[str, int]] = {}
    resolved_count = 0
    blocker_count = 0
    for row, state in zip(scope_items, states, strict=True):
        if not isinstance(row, Mapping):
            raise WorkspaceConflict("Workspace review scope item is invalid")
        kind = str(row.get("object_kind") or "")
        counters = by_kind.setdefault(
            kind,
            {"total": 0, "resolved": 0, "blockers": 0},
        )
        counters["total"] += 1
        if getattr(state, "resolved", False):
            counters["resolved"] += 1
            resolved_count += 1
        if getattr(state, "blocking", False):
            counters["blockers"] += 1
            blocker_count += 1
    return {
        "scope_count": len(states),
        "resolved_count": resolved_count,
        "blocker_count": blocker_count,
        "by_kind": by_kind,
    }


def _merged_bindings(
    session: Session,
    *,
    release_id: UUID,
    changeset: Changeset | None,
) -> dict[str, list[dict[str, object]]]:
    manifest = get_release_artifact_manifest(session, release_id)
    frozen = manifest.snapshot.get("bindings") if manifest is not None else None
    base = frozen if isinstance(frozen, Mapping) else {}
    if changeset is None:
        return {
            name: [dict(row) for row in base.get(name, []) if isinstance(row, Mapping)]
            for name in (
                "visual_object_regions",
                "visual_object_assets",
                "visual_object_compounds",
                "visual_object_relations",
            )
        }
    try:
        return merge_binding_snapshots(
            base,
            draft_binding_delta_for_changeset(session, changeset.id),
        )
    except ValueError as error:
        raise WorkspaceConflict(
            f"Workspace binding delta is invalid: {error}"
        ) from error


def _bindings_for_object(
    bindings: Mapping[str, list[dict[str, object]]],
    visual_object_id: UUID,
) -> dict[str, list[dict[str, object]]]:
    identifier = str(visual_object_id)
    return {
        "regions": [
            dict(row)
            for row in bindings.get("visual_object_regions", [])
            if str(row.get("visual_object_id")) == identifier
        ],
        "assets": [
            dict(row)
            for row in bindings.get("visual_object_assets", [])
            if str(row.get("visual_object_id")) == identifier
        ],
        "compounds": [
            dict(row)
            for row in bindings.get("visual_object_compounds", [])
            if str(row.get("visual_object_id")) == identifier
        ],
        "relations": [
            dict(row)
            for row in bindings.get("visual_object_relations", [])
            if str(row.get("source_object_id")) == identifier
            or str(row.get("target_object_id")) == identifier
        ],
    }


def build_workspace(
    session: Session,
    *,
    changeset_id: UUID,
    actor_id: UUID,
    is_admin: bool,
) -> dict[str, object]:
    changeset = session.get(Changeset, changeset_id)
    if changeset is None:
        raise WorkspaceNotFound("Changeset not found")
    if not is_admin and changeset.owner_id != actor_id:
        raise WorkspaceNotFound("Changeset not found")
    task = session.get(ReviewTask, changeset.review_task_id)
    if task is None or task.paper_id != changeset.paper_id:
        raise WorkspaceConflict("Workspace review task is invalid")
    release = session.get(Release, changeset.base_release_id)
    if release is None or not release.manifest_finalized:
        raise WorkspaceNotFound("Base release not found")
    if not is_admin and task.assigned_reviewer_id != actor_id:
        raise WorkspaceNotFound("Changeset not found")
    paper = session.get(Paper, changeset.paper_id)
    if paper is None:
        raise WorkspaceConflict("Workspace Paper is missing")
    scope = PaperReviewScopeService.ensure_scope(
        session,
        changeset=changeset,
        actor_id=actor_id,
    )
    scoped = _scoped_items(session, changeset=changeset, release=release)
    proposals: dict[UUID, tuple[MoleculeProposal, ObjectRevision]] = {}
    for row in scoped:
        if row.item.object_kind is not ObjectKind.MOLECULE_PROPOSAL:
            continue
        proposal = session.get(MoleculeProposal, row.item.object_id)
        if proposal is not None and proposal.paper_id == changeset.paper_id:
            proposals[proposal.id] = (proposal, row.revision)
    proposals_by_object = {
        proposal.visual_object_id: (proposal, revision)
        for proposal, revision in proposals.values()
    }
    review_progress = PaperReviewScopeService.progress(
        session,
        changeset=changeset,
        scope=scope,
    )
    progress = _scope_progress_payload(scope, review_progress.states)

    regions: list[dict[str, object]] = []
    region_by_id: dict[UUID, dict[str, object]] = {}
    visual_objects: list[dict[str, object]] = []
    structures: list[dict[str, object]] = []
    assets: dict[UUID, dict[str, object]] = {}
    source_locators: list[dict[str, object]] = []
    region_for_object: dict[UUID, VisualRegion] = {}
    bindings = _merged_bindings(
        session,
        release_id=release.id,
        changeset=changeset,
    )
    for binding in bindings["visual_object_regions"]:
        try:
            visual_id = UUID(str(binding["visual_object_id"]))
            region_id = UUID(str(binding["region_id"]))
        except (KeyError, TypeError, ValueError) as error:
            raise WorkspaceConflict("Workspace Region binding is invalid") from error
        region = session.get(VisualRegion, region_id)
        visual = session.get(VisualObject, visual_id)
        if (
            region is None
            or visual is None
            or region.paper_id != changeset.paper_id
            or visual.paper_id != changeset.paper_id
        ):
            raise WorkspaceConflict("Workspace Region binding crosses Paper scope")
        region_for_object[visual.id] = region
    for row in scoped:
        if row.item.object_kind is ObjectKind.VISUAL_REGION:
            region = session.get(VisualRegion, row.item.object_id)
            if region is None or region.paper_id != changeset.paper_id:
                continue
            bounds = {
                "x0": row.revision.region_x0,
                "y0": row.revision.region_y0,
                "x1": row.revision.region_x1,
                "y1": row.revision.region_y1,
            }
            asset = session.get(Asset, region.asset_id) if region.asset_id else None
            payload = {
                "id": str(region.id),
                "region_key": region.region_key,
                "revision_id": str(row.revision.id),
                "page_number": region.page_number,
                "bounds": bounds,
                "rotation": row.revision.region_rotation or 0,
                "asset_id": str(region.asset_id) if region.asset_id else None,
                "asset": asset_payload(asset),
                "is_tombstone": bool(row.revision.is_tombstone),
            }
            regions.append(payload)
            region_by_id[region.id] = payload
            if asset is not None:
                assets[asset.id] = asset_payload(asset) or {}
        elif row.item.object_kind is ObjectKind.VISUAL_OBJECT:
            visual = session.get(VisualObject, row.item.object_id)
            if visual is None or visual.paper_id != changeset.paper_id:
                continue
            region = region_for_object.get(visual.id)
            proposal_row = proposals_by_object.get(visual.id)
            proposal = proposal_row[0] if proposal_row is not None else None
            proposal_revision = proposal_row[1] if proposal_row is not None else None
            queue_state, queue_blocking, _ = _object_queue_state(
                revision=row.revision,
                proposal_revision=proposal_revision,
                source_ready=_proposal_source_ready(
                    session,
                    proposal=proposal,
                    region=region,
                    paper_id=changeset.paper_id,
                ),
                structure_ready=_proposal_structure_ready(
                    session,
                    revision=proposal_revision,
                    paper_id=changeset.paper_id,
                ),
            )
            object_bindings = _bindings_for_object(bindings, visual.id)
            for binding in object_bindings["assets"]:
                asset_id = binding.get("asset_id")
                asset = session.get(Asset, UUID(str(asset_id))) if asset_id else None
                binding["asset"] = asset_payload(asset)
                if asset is not None:
                    assets[asset.id] = asset_payload(asset) or {}
            visual_objects.append(
                {
                    "id": str(visual.id),
                    "object_key": visual.object_key,
                    "object_type": str(visual.object_type),
                    "revision_id": str(row.revision.id),
                    "snapshot": _safe_value(row.revision.snapshot),
                    "queue_state": queue_state.value,
                    "blocking": queue_blocking,
                    "region_id": str(region.id) if region is not None else None,
                    "bindings": _safe_value(object_bindings),
                }
            )
        elif row.item.object_kind is ObjectKind.STRUCTURE:
            structure = session.get(Structure, row.item.object_id)
            if structure is None or structure.paper_id != changeset.paper_id:
                continue
            structures.append(
                {
                    "id": str(structure.id),
                    "compound_id": str(structure.compound_id),
                    "structure_key": structure.structure_key,
                    "revision_id": str(row.revision.id),
                    "state": (
                        row.revision.structure_state.value
                        if row.revision.structure_state
                        else None
                    ),
                    "canonical_smiles": row.revision.canonical_smiles,
                    "snapshot": _safe_value(row.revision.snapshot),
                }
            )

    proposal_payload: list[dict[str, object]] = []
    for proposal, revision in sorted(
        proposals.values(),
        key=lambda value: (value[0].proposal_key, value[0].model_run_key),
    ):
        payload = _proposal_review(proposal, revision)
        crop = (
            session.get(Asset, proposal.crop_asset_id)
            if proposal.crop_asset_id
            else None
        )
        payload["crop_asset"] = asset_payload(crop)
        payload["source_region_id"] = (
            str(proposal.source_region_id) if proposal.source_region_id else None
        )
        proposal_payload.append(payload)
        if crop is not None:
            assets[crop.id] = asset_payload(crop) or {}
        if (
            proposal.source_region_id is not None
            and proposal.source_region_id in region_by_id
        ):
            region_payload = region_by_id[proposal.source_region_id]
            source_locators.append(
                {
                    "visual_object_id": str(proposal.visual_object_id),
                    "region_id": str(proposal.source_region_id),
                    "page_number": region_payload["page_number"],
                    "bounds": region_payload["bounds"],
                    "source_asset_id": region_payload["asset_id"],
                    "crop_asset_id": str(crop.id) if crop is not None else None,
                }
            )
    pages: dict[int, dict[str, int]] = {}
    for region in regions:
        page = int(region["page_number"])
        pages.setdefault(
            page,
            {
                "region_count": 0,
                "visual_object_count": 0,
                "proposal_count": 0,
                "blocker_count": 0,
            },
        )
        pages[page]["region_count"] += 1
    for visual in visual_objects:
        region_id = visual.get("region_id")
        region = region_by_id.get(UUID(str(region_id))) if region_id else None
        if region is None:
            continue
        page = int(region["page_number"])
        pages.setdefault(
            page,
            {
                "region_count": 0,
                "visual_object_count": 0,
                "proposal_count": 0,
                "blocker_count": 0,
            },
        )
        pages[page]["visual_object_count"] += 1
        if visual["blocking"]:
            pages[page]["blocker_count"] += 1
    for proposal in proposal_payload:
        region_id = proposal.get("source_region_id")
        region = region_by_id.get(UUID(str(region_id))) if region_id else None
        if region is not None:
            page_counts = pages[int(region["page_number"])]
            page_counts["proposal_count"] += 1
    paper_revision = next(
        (
            row.revision
            for row in scoped
            if row.item.object_kind is ObjectKind.PAPER
        ),
        None,
    )
    normalized = (
        paper_revision.snapshot.get("normalized_values") if paper_revision else {}
    )
    normalized = normalized if isinstance(normalized, Mapping) else {}
    attestation = session.scalar(
        select(PaperReviewAttestation)
        .where(
            PaperReviewAttestation.changeset_id == changeset.id,
            PaperReviewAttestation.changeset_version == changeset.version,
        )
        .order_by(PaperReviewAttestation.created_at.desc())
        .limit(1)
    )
    ending_version = session.scalar(
        select(Changeset.version).where(Changeset.id == changeset.id)
    )
    if ending_version != changeset.version:
        raise WorkspaceConflict("Workspace changed while it was being assembled")
    return {
        "workspace_version": changeset.version,
        "changeset": {
            "id": str(changeset.id),
            "review_task_id": str(changeset.review_task_id),
            "paper_id": str(changeset.paper_id),
            "owner_id": str(changeset.owner_id),
            "base_release_id": str(changeset.base_release_id),
            "workflow_state": changeset.workflow_state.value,
            "version": changeset.version,
            "title": changeset.title,
            "reason": changeset.reason,
        },
        "paper": {
            "id": str(changeset.paper_id),
            "paper_key": paper.paper_key,
            "title": normalized.get("title_guess"),
            "base_release_id": str(changeset.base_release_id),
        },
        "progress": progress,
        "document": {
            "url": (
                f"/api/v1/papers/{changeset.paper_id}/source-pdf"
                f"?kind=article&release_id={changeset.base_release_id}"
            ),
            "release_id": str(changeset.base_release_id),
        },
        "pages": [
            {"page_number": page, **values}
            for page, values in sorted(pages.items())
        ],
        "regions": sorted(regions, key=lambda row: (row["page_number"], row["id"])),
        "visual_objects": sorted(visual_objects, key=lambda row: str(row["id"])),
        "molecule_proposals": proposal_payload,
        "structures": sorted(structures, key=lambda row: str(row["id"])),
        "evidence": [],
        "assets": [assets[key] for key in sorted(assets, key=str)],
        "source_locators": sorted(
            source_locators,
            key=lambda row: (row["page_number"], row["visual_object_id"]),
        ),
        "attestation": (
            {
                "id": str(attestation.id),
                "changeset_version": attestation.changeset_version,
                "scope_hash": attestation.scope_hash,
                "item_count": attestation.item_count,
                "resolved_count": attestation.resolved_count,
                "blocker_count": attestation.blocker_count,
                "statement": attestation.statement,
            }
            if attestation is not None
            else None
        ),
        "scope": {
            "id": str(scope.id),
            "scope_hash": scope.scope_hash,
            "item_count": scope.item_count,
        },
    }


def list_molecule_object_queue(
    session: Session,
    *,
    actor_id: UUID,
    is_admin: bool,
    status: str | None = None,
    paper_id: UUID | None = None,
    page: int | None = None,
    object_type: str | None = None,
    has_blocker: bool | None = None,
    cursor: str | None = None,
    limit: int = 20,
) -> dict[str, object]:
    current_release = get_current_release(session)
    task_rows = list(
        session.scalars(
            select(ReviewTask)
            .where(
                ReviewTask.assigned_reviewer_id == actor_id
                if not is_admin
                else ReviewTask.id.is_not(None)
            )
            .order_by(ReviewTask.priority.desc(), ReviewTask.id)
        )
    )
    if paper_id is not None:
        task_rows = [task for task in task_rows if task.paper_id == paper_id]
    rows: list[dict[str, object]] = []
    status_counts: Counter[str] = Counter()
    for task in task_rows:
        paper = session.get(Paper, task.paper_id)
        if paper is None:
            continue
        changeset = session.scalar(
            select(Changeset).where(Changeset.review_task_id == task.id).limit(1)
        )
        release = (
            session.get(Release, changeset.base_release_id)
            if changeset is not None
            else current_release
        )
        if release is None or not release.manifest_finalized:
            continue
        paper_items = list(
            session.scalars(
                select(ReleaseItem).where(
                    ReleaseItem.release_id == release.id,
                    ReleaseItem.paper_id == task.paper_id,
                )
            )
        )
        release_items = [
            item
            for item in paper_items
            if item.object_kind is ObjectKind.VISUAL_OBJECT
        ]
        if changeset is not None:
            scoped = _scoped_items(session, changeset=changeset, release=release)
        else:
            scoped = []
            for item in paper_items:
                revision = session.get(ObjectRevision, item.revision_id)
                if revision is not None:
                    scoped.append(_ScopedItem(item=item, revision=revision))
        revisions_by_object = {row.item.object_id: row.revision for row in scoped}
        proposal_rows = list(
            session.scalars(
                select(MoleculeProposal).where(
                    MoleculeProposal.paper_id == task.paper_id,
                    MoleculeProposal.id.in_(revisions_by_object),
                )
            )
        )
        proposals_by_object = {
            proposal.visual_object_id: proposal for proposal in proposal_rows
        }
        proposal_revisions = {
            proposal.id: revisions_by_object.get(proposal.id)
            for proposal in proposal_rows
        }
        scope = (
            session.scalar(
                select(PaperReviewScope).where(
                    PaperReviewScope.changeset_id == changeset.id
                )
            )
            if changeset is not None
            else None
        )
        if scope is not None and changeset is not None:
            review_progress = PaperReviewScopeService.progress(
                session,
                changeset=changeset,
                scope=scope,
            )
            paper_progress = _scope_progress_payload(scope, review_progress.states)
        else:
            paper_progress = _progress_for_items(scoped)
        bindings = _merged_bindings(
            session,
            release_id=release.id,
            changeset=changeset,
        )
        for release_item in release_items:
            visual = session.get(VisualObject, release_item.object_id)
            base_revision = session.get(ObjectRevision, release_item.revision_id)
            if visual is None or base_revision is None:
                continue
            object_bindings = _bindings_for_object(bindings, visual.id)
            region_binding = next(iter(object_bindings["regions"]), None)
            region_id = region_binding.get("region_id") if region_binding else None
            region = (
                session.get(VisualRegion, UUID(str(region_id)))
                if region_id
                else None
            )
            if region is None or region.page_number != 1:
                continue
            proposal = proposals_by_object.get(visual.id)
            proposal_revision = (
                proposal_revisions.get(proposal.id) if proposal else None
            )
            object_revision = revisions_by_object.get(visual.id, base_revision)
            assert object_revision is not None
            state, blocking, reasons = _object_queue_state(
                revision=object_revision,
                proposal_revision=proposal_revision,
                source_ready=_proposal_source_ready(
                    session,
                    proposal=proposal,
                    region=region,
                    paper_id=task.paper_id,
                ),
                structure_ready=_proposal_structure_ready(
                    session,
                    revision=proposal_revision,
                    paper_id=task.paper_id,
                ),
            )
            status_counts[state.value] += 1
            if status is not None and state.value != status:
                continue
            if object_type is not None and str(visual.object_type) != object_type:
                continue
            if page is not None and region.page_number != page:
                continue
            if has_blocker is not None and blocking is not has_blocker:
                continue
            crop = None
            if proposal is not None and proposal.crop_asset_id is not None:
                crop = asset_payload(session.get(Asset, proposal.crop_asset_id))
            rows.append(
                {
                    "paper_id": str(task.paper_id),
                    "paper_key": paper.paper_key,
                    "base_release_id": str(release.id),
                    "review_task_id": str(task.id),
                    "changeset_id": str(changeset.id) if changeset is not None else None,
                    "changeset_version": changeset.version if changeset is not None else None,
                    "visual_object": {
                        "id": str(visual.id),
                        "object_key": visual.object_key,
                        "object_type": str(visual.object_type),
                        "region_id": str(region.id),
                    },
                    "proposal": (
                        {
                            "id": str(proposal.id),
                            "proposal_key": proposal.proposal_key,
                            "disposition": (
                                str(
                                    proposal_revision.proposal_disposition
                                    or "pending"
                                )
                                if proposal_revision
                                else "pending"
                            ),
                            "revision_id": (
                                str(proposal_revision.id)
                                if proposal_revision
                                else None
                            ),
                        }
                        if proposal is not None
                        else None
                    ),
                    "crop_asset": crop,
                    "page": region.page_number,
                    "state": state.value,
                    "blocking": blocking,
                    "reasons": list(reasons),
                    "paper_progress": {
                        "scope_count": paper_progress["scope_count"],
                        "resolved_count": paper_progress["resolved_count"],
                        "blocker_count": paper_progress["blocker_count"],
                    },
                    "deep_link": {
                        "view": "ocsr",
                        "page": region.page_number,
                        "object": str(visual.id),
                        "proposal": str(proposal.id) if proposal is not None else None,
                    },
                    "priority": task.priority,
                    "_sort_key": [
                        _QUEUE_PRIORITY[state.value],
                        _minimum_confidence(proposal_revision),
                        -task.priority,
                        paper.paper_key,
                        str(region.page_number).zfill(8),
                        visual.object_key,
                        str(visual.id),
                    ],
                }
            )
    rows.sort(key=lambda row: tuple(row["_sort_key"]))
    if cursor:
        decoded_cursor = _decode_cursor(cursor)
        rows = [row for row in rows if tuple(row["_sort_key"]) > decoded_cursor]
    visible = rows[:limit]
    next_cursor = (
        _encode_cursor(visible[-1]["_sort_key"])
        if len(rows) > limit and visible
        else None
    )
    for row in visible:
        row.pop("_sort_key", None)
    return {
        "items": visible,
        "next_cursor": next_cursor,
        "status_counts": {
            state.value: status_counts.get(state.value, 0) for state in QueueState
        },
        "pagination": {"limit": limit, "returned": len(visible)},
    }
