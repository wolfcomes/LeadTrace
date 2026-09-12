from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.assets import models as _asset_models  # noqa: F401
from app.revisions.models import ObjectRevision
from app.revisions.service import RevisionService, canonical_snapshot_hash
from app.reviews.models import Changeset, ChangesetItem
from app.security.policies import WorkflowState
from app.visual_objects.models import VisualRegion


class RegionValidationError(ValueError):
    """Raised when a region cannot be represented on a PDF page."""


class RegionVersionConflict(RuntimeError):
    """Raised when the draft version changed since the editor loaded it."""

    def __init__(self, expected_version: int, current_version: int) -> None:
        self.expected_version = expected_version
        self.current_version = current_version
        super().__init__(
            f"Region draft changed concurrently: expected {expected_version}, "
            f"current {current_version}"
        )


@dataclass(frozen=True, slots=True)
class RegionBounds:
    x0: float
    y0: float
    x1: float
    y1: float

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


def normalize_bounds(x0: float, y0: float, x1: float, y1: float) -> RegionBounds:
    values = (x0, y0, x1, y1)
    if any(not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in values):
        raise RegionValidationError("Region coordinates must be finite numbers")
    clean = tuple(float(value) for value in values)
    if any(value < 0 or value > 1 for value in clean):
        raise RegionValidationError("Region coordinates must be between 0 and 1")
    if clean[0] >= clean[2] or clean[1] >= clean[3]:
        raise RegionValidationError("Region must have a positive width and height")
    return RegionBounds(*clean)


def _page_number(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RegionValidationError("page_number must be a positive integer")
    return value


def _rotation(value: int) -> int:
    if isinstance(value, bool) or value not in {0, 90, 180, 270}:
        raise RegionValidationError("rotation must be 0, 90, 180, or 270")
    return value


def build_region_snapshot(
    *,
    region_key: str,
    page_number: int,
    bounds: RegionBounds,
    rotation: int = 0,
    region_id: UUID | None = None,
) -> dict[str, object]:
    clean_key = region_key.strip()
    if not clean_key:
        raise RegionValidationError("region_key is required")
    return {
        "region_id": str(region_id) if region_id is not None else None,
        "region_key": clean_key,
        "page_number": _page_number(page_number),
        "bounds": bounds.as_dict(),
        "rotation": _rotation(rotation),
    }


def _bounds_from_revision(revision: ObjectRevision | None) -> RegionBounds | None:
    if revision is None:
        return None
    values = (
        revision.region_x0,
        revision.region_y0,
        revision.region_x1,
        revision.region_y1,
    )
    if any(value is None for value in values):
        return None
    return RegionBounds(*(float(value) for value in values))


def _snapshot_hash(session: Session, snapshot: dict[str, object]) -> str:
    try:
        value = session.scalar(
            select(func.leadtrace_jsonb_sha256(cast(snapshot, JSONB)))
        )
    except Exception:
        value = None
    return str(value or canonical_snapshot_hash(snapshot))


class RegionService:
    """Append-only region editing facade shared by the API and worker code."""

    @staticmethod
    def check_expected_version(current_version: int, *, expected_version: int) -> None:
        if expected_version != current_version:
            raise RegionVersionConflict(expected_version, current_version)

    @staticmethod
    def _latest_revision(session: Session, region_id: UUID, *, for_update: bool = False) -> ObjectRevision | None:
        statement = (
            select(ObjectRevision)
            .where(ObjectRevision.object_id == region_id)
            .order_by(ObjectRevision.revision_number.desc())
            .limit(1)
        )
        if for_update:
            statement = statement.with_for_update()
        return session.scalar(statement)

    @staticmethod
    def ensure_region_belongs_to_paper(
        session: Session,
        *,
        region_id: UUID,
        paper_id: UUID,
    ) -> VisualRegion:
        region = session.scalar(select(VisualRegion).where(VisualRegion.id == region_id))
        if region is None:
            raise RegionValidationError("Region not found")
        if region.paper_id != paper_id:
            raise RegionValidationError("Region belongs to another Paper")
        return region

    @staticmethod
    def _editable_changeset(
        session: Session,
        changeset_id: UUID,
        expected_version: int,
    ) -> Changeset:
        changeset = session.scalar(
            select(Changeset).where(Changeset.id == changeset_id).with_for_update()
        )
        if changeset is None:
            raise RegionValidationError("Changeset not found")
        RegionService.check_expected_version(
            changeset.version, expected_version=expected_version
        )
        if changeset.workflow_state not in {
            WorkflowState.DRAFT,
            WorkflowState.REVISED_DRAFT,
            WorkflowState.CHANGES_REQUESTED,
        }:
            raise RegionValidationError("Only editable draft changesets can contain regions")
        return changeset

    @staticmethod
    def _ensure_changeset_item(
        session: Session,
        *,
        changeset: Changeset,
        region: VisualRegion,
        snapshot: dict[str, object],
        base_revision_id: UUID | None,
    ) -> ChangesetItem:
        item = session.scalar(
            select(ChangesetItem)
            .where(
                ChangesetItem.changeset_id == changeset.id,
                ChangesetItem.object_id == region.id,
            )
            .with_for_update()
        )
        content_hash = _snapshot_hash(session, snapshot)
        if item is None:
            latest_sequence = session.scalar(
                select(func.max(ChangesetItem.sequence)).where(
                    ChangesetItem.changeset_id == changeset.id
                )
            )
            item = ChangesetItem(
                changeset_id=changeset.id,
                paper_id=changeset.paper_id,
                object_id=region.id,
                object_kind="visual_region",
                base_revision_id=base_revision_id,
                proposed_snapshot=snapshot,
                content_hash=content_hash,
                sequence=int(latest_sequence or 0) + 1,
            )
            session.add(item)
            session.flush()
        else:
            item.proposed_snapshot = snapshot
            item.content_hash = content_hash
            item.base_revision_id = item.base_revision_id or base_revision_id
        return item

    def create_region(
        self,
        session: Session,
        *,
        paper_id: UUID,
        actor_id: UUID,
        region_key: str,
        page_number: int,
        bounds: RegionBounds | None = None,
        x0: float | None = None,
        y0: float | None = None,
        x1: float | None = None,
        y1: float | None = None,
        rotation: int = 0,
        changeset_id: UUID | None = None,
        expected_version: int | None = None,
        asset_id: UUID | None = None,
    ) -> VisualRegion:
        page_number = _page_number(page_number)
        rotation = _rotation(rotation)
        if bounds is None:
            if any(value is None for value in (x0, y0, x1, y1)):
                raise RegionValidationError("Region bounds are required")
            bounds = normalize_bounds(float(x0), float(y0), float(x1), float(y1))
        clean_key = region_key.strip()
        if not clean_key:
            raise RegionValidationError("region_key is required")
        if session.scalar(
            select(VisualRegion.id).where(
                VisualRegion.paper_id == paper_id,
                VisualRegion.region_key == clean_key,
            )
        ) is not None:
            raise RegionValidationError("region_key already exists for this Paper")
        region = VisualRegion(paper_id=paper_id, region_key=clean_key, asset_id=asset_id, page_number=page_number)
        session.add(region)
        session.flush()
        snapshot = build_region_snapshot(
            region_key=clean_key,
            page_number=page_number,
            bounds=bounds,
            rotation=rotation,
            region_id=region.id,
        )
        changeset = None
        item = None
        if changeset_id is not None:
            if expected_version is None:
                raise RegionValidationError("expected_version is required with changeset_id")
            changeset = self._editable_changeset(session, changeset_id, expected_version)
            if changeset.paper_id != paper_id:
                raise RegionValidationError("Changeset belongs to another Paper")
            item = self._ensure_changeset_item(
                session,
                changeset=changeset,
                region=region,
                snapshot=snapshot,
                base_revision_id=None,
            )
        revision = RevisionService().create_revision(
            session,
            object_identity=region,
            actor_id=actor_id,
            reason="Create visual region",
            snapshot=snapshot,
            predecessor=None,
            changeset_id=changeset.id if changeset is not None else None,
            workflow_state=changeset.workflow_state if changeset is not None else WorkflowState.DRAFT,
            region_bounds=(bounds.x0, bounds.y0, bounds.x1, bounds.y1),
            region_rotation=rotation,
        )
        if item is not None:
            item.proposed_revision_id = revision.id
            changeset.version += 1
        session.flush()
        return region

    def update_region(
        self,
        session: Session,
        *,
        region_id: UUID,
        actor_id: UUID,
        bounds: RegionBounds | None = None,
        x0: float | None = None,
        y0: float | None = None,
        x1: float | None = None,
        y1: float | None = None,
        page_number: int | None = None,
        rotation: int | None = None,
        changeset_id: UUID | None = None,
        expected_version: int | None = None,
        reason: str = "Update visual region",
    ) -> ObjectRevision:
        region = session.scalar(
            select(VisualRegion).where(VisualRegion.id == region_id).with_for_update()
        )
        if region is None:
            raise RegionValidationError("Region not found")
        latest = self._latest_revision(session, region_id, for_update=True)
        if latest is None:
            raise RegionValidationError("Region has no revision")
        current_bounds = _bounds_from_revision(latest)
        if bounds is None and any(value is not None for value in (x0, y0, x1, y1)):
            if any(value is None for value in (x0, y0, x1, y1)):
                raise RegionValidationError("Region bounds are required")
            bounds = normalize_bounds(float(x0), float(y0), float(x1), float(y1))
        next_bounds = bounds or current_bounds
        if next_bounds is None:
            raise RegionValidationError("Region bounds are required")
        next_page = _page_number(page_number if page_number is not None else region.page_number)
        next_rotation = _rotation(rotation if rotation is not None else int(latest.region_rotation or 0))
        changeset = None
        item = None
        if changeset_id is not None:
            if expected_version is None:
                raise RegionValidationError("expected_version is required with changeset_id")
            changeset = self._editable_changeset(session, changeset_id, expected_version)
            if changeset.paper_id != region.paper_id:
                raise RegionValidationError("Changeset belongs to another Paper")
            item = self._ensure_changeset_item(
                session,
                changeset=changeset,
                region=region,
                snapshot=latest.snapshot,
                base_revision_id=latest.id,
            )
        snapshot = build_region_snapshot(
            region_key=region.region_key,
            page_number=next_page,
            bounds=next_bounds,
            rotation=next_rotation,
            region_id=region.id,
        )
        revision = RevisionService().create_revision(
            session,
            object_identity=region,
            actor_id=actor_id,
            reason=reason,
            snapshot=snapshot,
            predecessor=latest,
            changeset_id=changeset.id if changeset is not None else None,
            workflow_state=changeset.workflow_state if changeset is not None else WorkflowState.DRAFT,
            region_bounds=(next_bounds.x0, next_bounds.y0, next_bounds.x1, next_bounds.y1),
            region_rotation=next_rotation,
            is_tombstone=latest.is_tombstone,
        )
        region.page_number = next_page
        if item is not None:
            item.proposed_snapshot = snapshot
            item.content_hash = _snapshot_hash(session, snapshot)
            item.proposed_revision_id = revision.id
            changeset.version += 1
        session.flush()
        return revision

    def move_region(self, session: Session, **kwargs: Any) -> ObjectRevision:
        """Record a move as a new immutable revision."""
        kwargs.setdefault("reason", "Move visual region")
        return self.update_region(session, **kwargs)

    def resize_region(self, session: Session, **kwargs: Any) -> ObjectRevision:
        """Record a resize as a new immutable revision."""
        kwargs.setdefault("reason", "Resize visual region")
        return self.update_region(session, **kwargs)

    def duplicate_region(
        self,
        session: Session,
        *,
        region_id: UUID,
        actor_id: UUID,
        region_key: str,
        changeset_id: UUID,
        expected_version: int,
    ) -> VisualRegion:
        source = session.scalar(select(VisualRegion).where(VisualRegion.id == region_id))
        if source is None:
            raise RegionValidationError("Region not found")
        latest = self._latest_revision(session, region_id)
        bounds = _bounds_from_revision(latest)
        if latest is None or bounds is None:
            raise RegionValidationError("Region has no revision")
        return self.create_region(
            session,
            paper_id=source.paper_id,
            actor_id=actor_id,
            region_key=region_key,
            page_number=source.page_number,
            bounds=bounds,
            rotation=int(latest.region_rotation or 0),
            changeset_id=changeset_id,
            expected_version=expected_version,
            asset_id=source.asset_id,
        )

    def split_region(
        self,
        session: Session,
        *,
        region_id: UUID,
        actor_id: UUID,
        first_key: str,
        second_key: str,
        first_bounds: RegionBounds,
        second_bounds: RegionBounds,
        changeset_id: UUID,
        expected_version: int,
    ) -> tuple[VisualRegion, VisualRegion]:
        source = session.scalar(select(VisualRegion).where(VisualRegion.id == region_id))
        if source is None:
            raise RegionValidationError("Region not found")
        latest = self._latest_revision(session, region_id)
        rotation = int(latest.region_rotation or 0) if latest is not None else 0
        first = self.create_region(
            session,
            paper_id=source.paper_id,
            actor_id=actor_id,
            region_key=first_key,
            page_number=source.page_number,
            bounds=first_bounds,
            rotation=rotation,
            changeset_id=changeset_id,
            expected_version=expected_version,
            asset_id=source.asset_id,
        )
        second = self.create_region(
            session,
            paper_id=source.paper_id,
            actor_id=actor_id,
            region_key=second_key,
            page_number=source.page_number,
            bounds=second_bounds,
            rotation=rotation,
            changeset_id=changeset_id,
            expected_version=expected_version + 1,
            asset_id=source.asset_id,
        )
        self.tombstone_region(
            session,
            region_id=region_id,
            actor_id=actor_id,
            changeset_id=changeset_id,
            expected_version=expected_version + 2,
        )
        return first, second

    def tombstone_region(
        self,
        session: Session,
        *,
        region_id: UUID,
        actor_id: UUID,
        changeset_id: UUID,
        expected_version: int,
    ) -> ObjectRevision:
        return self._set_tombstone(
            session,
            region_id=region_id,
            actor_id=actor_id,
            changeset_id=changeset_id,
            expected_version=expected_version,
            tombstone=True,
        )

    def restore_region(
        self,
        session: Session,
        *,
        region_id: UUID,
        actor_id: UUID,
        changeset_id: UUID,
        expected_version: int,
    ) -> ObjectRevision:
        return self._set_tombstone(
            session,
            region_id=region_id,
            actor_id=actor_id,
            changeset_id=changeset_id,
            expected_version=expected_version,
            tombstone=False,
        )

    def tombstone(self, session: Session, **kwargs: Any) -> ObjectRevision:
        return self.tombstone_region(session, **kwargs)

    def restore(self, session: Session, **kwargs: Any) -> ObjectRevision:
        return self.restore_region(session, **kwargs)

    def _set_tombstone(
        self,
        session: Session,
        *,
        region_id: UUID,
        actor_id: UUID,
        changeset_id: UUID,
        expected_version: int,
        tombstone: bool,
    ) -> ObjectRevision:
        latest = self._latest_revision(session, region_id, for_update=True)
        region = session.get(VisualRegion, region_id)
        if region is None or latest is None:
            raise RegionValidationError("Region not found")
        changeset = self._editable_changeset(session, changeset_id, expected_version)
        if changeset.paper_id != region.paper_id:
            raise RegionValidationError("Changeset belongs to another Paper")
        item = self._ensure_changeset_item(
            session,
            changeset=changeset,
            region=region,
            snapshot=latest.snapshot,
            base_revision_id=latest.id,
        )
        bounds = _bounds_from_revision(latest)
        if bounds is None:
            raise RegionValidationError("Region has no revision bounds")
        snapshot = dict(latest.snapshot)
        snapshot["tombstone"] = tombstone
        revision = RevisionService().create_revision(
            session,
            object_identity=region,
            actor_id=actor_id,
            reason="Restore visual region" if not tombstone else "Tombstone visual region",
            snapshot=snapshot,
            predecessor=latest,
            changeset_id=changeset.id,
            workflow_state=changeset.workflow_state,
            is_tombstone=tombstone,
            region_bounds=(bounds.x0, bounds.y0, bounds.x1, bounds.y1),
            region_rotation=int(latest.region_rotation or 0),
        )
        item.proposed_snapshot = snapshot
        item.content_hash = _snapshot_hash(session, snapshot)
        item.proposed_revision_id = revision.id
        changeset.version += 1
        session.flush()
        return revision

    def list_regions(self, session: Session, paper_id: UUID) -> list[dict[str, Any]]:
        regions = list(
            session.scalars(
                select(VisualRegion)
                .where(VisualRegion.paper_id == paper_id)
                .order_by(VisualRegion.region_key)
            )
        )
        result: list[dict[str, Any]] = []
        for region in regions:
            revision = self._latest_revision(session, region.id)
            result.append(
                {
                    "id": str(region.id),
                    "region_key": region.region_key,
                    "paper_id": str(region.paper_id),
                    "asset_id": str(region.asset_id) if region.asset_id else None,
                    "page_number": region.page_number,
                    "revision_number": revision.revision_number if revision else 0,
                    "revision_id": str(revision.id) if revision else None,
                    "is_tombstone": bool(revision.is_tombstone) if revision else False,
                    "snapshot": revision.snapshot if revision else None,
                }
            )
        return result

    def revisions(self, session: Session, region_id: UUID) -> list[ObjectRevision]:
        return list(
            session.scalars(
                select(ObjectRevision)
                .where(ObjectRevision.object_id == region_id)
                .order_by(ObjectRevision.revision_number)
            )
        )

    def list_revisions(self, session: Session, region_id: UUID) -> list[ObjectRevision]:
        return self.revisions(session, region_id)
