from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import BinaryIO
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.assets.models import Asset, AssetIntegrityState
from app.assets.storage import AssetMimeMismatchError, AssetPathError, LocalAssetStore
from app.catalog.models import PaperSource, PaperSourceIntegrityState
from app.compounds.models import Compound
from app.jobs.execution import render_pdf_crop
from app.jobs.service import (
    PDF_RENDERER_VERSION,
    CropRequest,
    CropService,
    CropValidationError,
    cleanup_transaction_created_files,
    transaction_created_files,
)
from app.papers.models import Paper
from app.security.policies import Principal
from app.structure_images.models import CropStatus, StructureSourceImage
from app.structure_images.schemas import NormalizedBBox
from app.workspaces.history import LockedWorkspace, MutationChange
from app.workspaces.models import PaperWorkspace
from app.workspaces.service import WorkspaceNotFoundError, WorkspaceService


class StructureSourceImageValidationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        integrity_failure: tuple[UUID, UUID, AssetIntegrityState] | None = None,
    ) -> None:
        super().__init__(message)
        self.integrity_failure = integrity_failure


class StructureSourceImageDuplicateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StructureSourceImageMutation:
    workspace: PaperWorkspace
    source_image: StructureSourceImage


@dataclass(frozen=True, slots=True)
class StructureSourceImageList:
    workspace: PaperWorkspace
    compound_id: UUID
    source_images: list[StructureSourceImage]


def source_image_snapshot(source_image: StructureSourceImage) -> dict[str, object]:
    return {
        "id": str(source_image.id),
        "paper_id": str(source_image.paper_id),
        "workspace_id": str(source_image.workspace_id),
        "compound_id": str(source_image.compound_id),
        "source_sha256": source_image.source_sha256,
        "page_number": source_image.page_number,
        "bbox": {
            "x0": float(source_image.x0),
            "y0": float(source_image.y0),
            "x1": float(source_image.x1),
            "y1": float(source_image.y1),
        },
        "source_context": source_image.source_context,
        "label": source_image.label,
        "reviewer_note": source_image.reviewer_note,
        "crop_status": source_image.crop_status.value,
        "crop_asset_id": (
            str(source_image.crop_asset_id) if source_image.crop_asset_id else None
        ),
        "created_by_kind": source_image.created_by_kind.value,
    }


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def crop_request_for_source_image(
    source_image: StructureSourceImage,
) -> CropRequest:
    return CropRequest(
        source_pdf_sha256=source_image.source_sha256,
        page_number=source_image.page_number,
        x0=float(source_image.x0),
        y0=float(source_image.y0),
        x1=float(source_image.x1),
        y1=float(source_image.y1),
        rotation=0,
        padding=0,
        dpi=144,
        renderer_version=PDF_RENDERER_VERSION,
    )


class StructureSourceImageService:
    def __init__(
        self,
        managed_root: Path,
        *,
        source_roots: dict[str, Path] | None = None,
        workspace_service: WorkspaceService | None = None,
    ) -> None:
        self.managed_root = managed_root
        self.source_roots = source_roots
        self.workspace_service = workspace_service or WorkspaceService()

    def _store(self) -> LocalAssetStore:
        return LocalAssetStore(self.managed_root, source_roots=self.source_roots)

    @staticmethod
    def _workspace_id_for_compound(session: Session, compound_id: UUID) -> UUID:
        workspace_id = session.scalar(
            select(Compound.workspace_id).where(Compound.id == compound_id)
        )
        if workspace_id is None:
            raise WorkspaceNotFoundError("Resource not found")
        return workspace_id

    @staticmethod
    def _workspace_id_for_image(session: Session, source_image_id: UUID) -> UUID:
        workspace_id = session.scalar(
            select(StructureSourceImage.workspace_id).where(
                StructureSourceImage.id == source_image_id
            )
        )
        if workspace_id is None:
            raise WorkspaceNotFoundError("Resource not found")
        return workspace_id

    def _source_asset(
        self,
        session: Session,
        *,
        paper_id: UUID,
        source_sha256: str,
        page_number: int,
    ) -> tuple[Asset, BinaryIO]:
        row = session.execute(
            select(PaperSource, Asset)
            .join(Paper, Paper.source_id == PaperSource.id)
            .join(Asset, Asset.id == PaperSource.asset_id)
            .where(Paper.id == paper_id)
        ).one_or_none()
        if row is None:
            raise StructureSourceImageValidationError("Paper Source is unavailable")
        source, asset = row
        if source.sha256 != source_sha256 or asset.sha256 != source_sha256:
            raise StructureSourceImageValidationError(
                "Source SHA-256 does not match this Paper"
            )
        if page_number > source.page_count:
            raise StructureSourceImageValidationError(
                "page_number is outside the Paper Source"
            )
        if (
            source.integrity_state is not PaperSourceIntegrityState.VERIFIED
            or asset.integrity_state is not AssetIntegrityState.VERIFIED
            or asset.mime_type != "application/pdf"
        ):
            raise StructureSourceImageValidationError("Paper Source is unavailable")
        try:
            inspected, snapshot = self._store().open_snapshot(
                asset.storage_key,
                validate_extension=False,
                validate_content=False,
            )
        except (AssetPathError, AssetMimeMismatchError, FileNotFoundError, OSError):
            raise StructureSourceImageValidationError(
                "Paper Source is unavailable",
                integrity_failure=(asset.id, source.id, AssetIntegrityState.MISSING),
            ) from None
        if (
            inspected.sha256 != source.sha256
            or inspected.byte_size != source.byte_size
            or inspected.mime_type != "application/pdf"
        ):
            snapshot.close()
            raise StructureSourceImageValidationError(
                "Paper Source failed integrity verification",
                integrity_failure=(asset.id, source.id, AssetIntegrityState.CORRUPT),
            )
        return asset, snapshot

    @staticmethod
    def _duplicate_exists(
        session: Session,
        source_image: StructureSourceImage,
        *,
        exclude_id: UUID | None = None,
    ) -> bool:
        statement = select(StructureSourceImage.id).where(
            StructureSourceImage.compound_id == source_image.compound_id,
            StructureSourceImage.source_sha256 == source_image.source_sha256,
            StructureSourceImage.page_number == source_image.page_number,
            StructureSourceImage.x0 == source_image.x0,
            StructureSourceImage.y0 == source_image.y0,
            StructureSourceImage.x1 == source_image.x1,
            StructureSourceImage.y1 == source_image.y1,
        )
        if exclude_id is not None:
            statement = statement.where(StructureSourceImage.id != exclude_id)
        return session.scalar(statement.limit(1)) is not None

    def _render(
        self,
        session: Session,
        *,
        source_image: StructureSourceImage,
        source_asset: Asset,
        source_snapshot: BinaryIO,
        actor_id: UUID,
    ) -> None:
        request = crop_request_for_source_image(source_image)
        existing_created_files = transaction_created_files(session)
        try:
            content = render_pdf_crop(source_snapshot, request)
        except CropValidationError:
            source_image.crop_status = CropStatus.FAILED
            source_image.crop_asset_id = None
            return
        try:
            with session.begin_nested():
                result = CropService(
                    self.managed_root,
                    source_roots=self.source_roots,
                ).materialize_persisted(
                    session,
                    request,
                    renderer=lambda _: content,
                    source_asset_id=source_asset.id,
                    created_by_id=actor_id,
                    preferred_asset_id=source_image.crop_asset_id,
                )
                crop_asset = session.get(Asset, result.asset_id)
                if crop_asset is None:
                    raise CropValidationError(
                        "Materialized crop asset is unavailable"
                    )
                crop_asset.derivation_metadata = {
                    **crop_asset.derivation_metadata,
                    "visibility_scope": "structure_source_image",
                }
        except (
            AssetMimeMismatchError,
            AssetPathError,
            CropValidationError,
            OSError,
            SQLAlchemyError,
        ):
            cleanup_transaction_created_files(
                session,
                transaction_created_files(session) - existing_created_files,
            )
            source_image.crop_status = CropStatus.FAILED
            source_image.crop_asset_id = None
            return
        source_image.crop_status = CropStatus.READY
        source_image.crop_asset_id = result.asset_id

    def render_source_image_crop(
        self,
        session: Session,
        *,
        source_image: StructureSourceImage,
        actor_id: UUID,
    ) -> StructureSourceImage:
        """Materialize a crop for an already-persisted authoritative locator."""

        asset, source_snapshot = self._source_asset(
            session,
            paper_id=source_image.paper_id,
            source_sha256=source_image.source_sha256,
            page_number=source_image.page_number,
        )
        with source_snapshot:
            source_image.crop_status = CropStatus.PENDING
            source_image.crop_asset_id = None
            self._render(
                session,
                source_image=source_image,
                source_asset=asset,
                source_snapshot=source_snapshot,
                actor_id=actor_id,
            )
        return source_image

    def list_source_images(
        self,
        session: Session,
        *,
        compound_id: UUID,
        actor: Principal,
    ) -> StructureSourceImageList:
        workspace_id = self._workspace_id_for_compound(session, compound_id)
        aggregate = self.workspace_service.get_workspace(
            session, workspace_id=workspace_id, actor=actor
        )
        images = list(
            session.scalars(
                select(StructureSourceImage)
                .where(StructureSourceImage.compound_id == compound_id)
                .order_by(
                    StructureSourceImage.page_number,
                    StructureSourceImage.y0,
                    StructureSourceImage.x0,
                    StructureSourceImage.id,
                )
            )
        )
        return StructureSourceImageList(aggregate.workspace, compound_id, images)

    def get_source_image(
        self,
        session: Session,
        *,
        source_image_id: UUID,
        actor: Principal,
    ) -> StructureSourceImageMutation:
        workspace_id = self._workspace_id_for_image(session, source_image_id)
        aggregate = self.workspace_service.get_workspace(
            session, workspace_id=workspace_id, actor=actor
        )
        source_image = session.get(StructureSourceImage, source_image_id)
        if source_image is None:
            raise WorkspaceNotFoundError("Resource not found")
        return StructureSourceImageMutation(aggregate.workspace, source_image)

    def create_source_image(
        self,
        session: Session,
        *,
        compound_id: UUID,
        expected_version: int,
        actor: Principal,
        source_sha256: str,
        page_number: int,
        bbox: NormalizedBBox,
        source_context: str | None,
        label: str | None,
        reviewer_note: str | None,
    ) -> StructureSourceImageMutation:
        workspace_id = self._workspace_id_for_compound(session, compound_id)
        created: dict[str, StructureSourceImage] = {}

        def mutation(context: LockedWorkspace) -> MutationChange:
            compound = session.scalar(
                select(Compound).where(
                    Compound.id == compound_id,
                    Compound.workspace_id == context.workspace.id,
                )
            )
            if compound is None:
                raise WorkspaceNotFoundError("Resource not found")
            asset, source_snapshot = self._source_asset(
                session,
                paper_id=compound.paper_id,
                source_sha256=source_sha256,
                page_number=page_number,
            )
            with source_snapshot:
                source_image = StructureSourceImage(
                    paper_id=compound.paper_id,
                    workspace_id=compound.workspace_id,
                    compound_id=compound.id,
                    source_sha256=source_sha256,
                    page_number=page_number,
                    x0=bbox.x0,
                    y0=bbox.y0,
                    x1=bbox.x1,
                    y1=bbox.y1,
                    source_context=_clean_optional(source_context),
                    label=_clean_optional(label),
                    reviewer_note=_clean_optional(reviewer_note),
                    crop_status=CropStatus.PENDING,
                    crop_asset_id=None,
                )
                if self._duplicate_exists(session, source_image):
                    raise StructureSourceImageDuplicateError
                session.add(source_image)
                session.flush()  # Persist the authoritative locator before rendering.
                self._render(
                    session,
                    source_image=source_image,
                    source_asset=asset,
                    source_snapshot=source_snapshot,
                    actor_id=actor.user_id,
                )
            created["source_image"] = source_image
            return MutationChange(
                entity_type="structure_source_image",
                entity_id=source_image.id,
                action="structure_source_image.create",
                before_value=None,
                after_value=source_image_snapshot(source_image),
            )

        result = self.workspace_service.mutate(
            session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            actor=actor,
            mutation=mutation,
        )
        return StructureSourceImageMutation(result.workspace, created["source_image"])

    def update_source_image(
        self,
        session: Session,
        *,
        source_image_id: UUID,
        expected_version: int,
        actor: Principal,
        updates: dict[str, object],
    ) -> StructureSourceImageMutation:
        workspace_id = self._workspace_id_for_image(session, source_image_id)
        updated: dict[str, StructureSourceImage] = {}

        def mutation(context: LockedWorkspace) -> MutationChange:
            source_image = session.scalar(
                select(StructureSourceImage)
                .where(
                    StructureSourceImage.id == source_image_id,
                    StructureSourceImage.workspace_id == context.workspace.id,
                )
                .with_for_update()
            )
            if source_image is None:
                raise WorkspaceNotFoundError("Resource not found")
            before = source_image_snapshot(source_image)
            locator_changed = False
            if "source_sha256" in updates:
                source_image.source_sha256 = str(updates["source_sha256"])
                locator_changed = True
            if "page_number" in updates:
                source_image.page_number = int(updates["page_number"])
                locator_changed = True
            if "bbox" in updates:
                bbox = updates["bbox"]
                assert isinstance(bbox, NormalizedBBox)
                source_image.x0, source_image.y0 = bbox.x0, bbox.y0
                source_image.x1, source_image.y1 = bbox.x1, bbox.y1
                locator_changed = True
            for field in ("source_context", "label", "reviewer_note"):
                if field in updates:
                    setattr(source_image, field, _clean_optional(updates[field]))
            if self._duplicate_exists(
                session, source_image, exclude_id=source_image.id
            ):
                raise StructureSourceImageDuplicateError
            if locator_changed:
                asset, source_snapshot = self._source_asset(
                    session,
                    paper_id=source_image.paper_id,
                    source_sha256=source_image.source_sha256,
                    page_number=source_image.page_number,
                )
                with source_snapshot:
                    source_image.crop_status = CropStatus.PENDING
                    source_image.crop_asset_id = None
                    session.flush()
                    self._render(
                        session,
                        source_image=source_image,
                        source_asset=asset,
                        source_snapshot=source_snapshot,
                        actor_id=actor.user_id,
                    )
            after = source_image_snapshot(source_image)
            updated["source_image"] = source_image
            return MutationChange(
                entity_type="structure_source_image",
                entity_id=source_image.id,
                action="structure_source_image.update",
                before_value=before,
                after_value=after,
            )

        result = self.workspace_service.mutate(
            session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            actor=actor,
            mutation=mutation,
        )
        return StructureSourceImageMutation(result.workspace, updated["source_image"])

    def retry_crop(
        self,
        session: Session,
        *,
        source_image_id: UUID,
        expected_version: int,
        actor: Principal,
    ) -> StructureSourceImageMutation:
        workspace_id = self._workspace_id_for_image(session, source_image_id)
        retried: dict[str, StructureSourceImage] = {}

        def mutation(context: LockedWorkspace) -> MutationChange:
            source_image = session.scalar(
                select(StructureSourceImage)
                .where(
                    StructureSourceImage.id == source_image_id,
                    StructureSourceImage.workspace_id == context.workspace.id,
                )
                .with_for_update()
            )
            if source_image is None:
                raise WorkspaceNotFoundError("Resource not found")
            before = source_image_snapshot(source_image)
            asset, source_snapshot = self._source_asset(
                session,
                paper_id=source_image.paper_id,
                source_sha256=source_image.source_sha256,
                page_number=source_image.page_number,
            )
            with source_snapshot:
                self._render(
                    session,
                    source_image=source_image,
                    source_asset=asset,
                    source_snapshot=source_snapshot,
                    actor_id=actor.user_id,
                )
            after = source_image_snapshot(source_image)
            retried["source_image"] = source_image
            return MutationChange(
                entity_type="structure_source_image",
                entity_id=source_image.id,
                action="structure_source_image.retry",
                before_value=before,
                after_value=after,
            )

        result = self.workspace_service.mutate(
            session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            actor=actor,
            mutation=mutation,
        )
        return StructureSourceImageMutation(result.workspace, retried["source_image"])

    def delete_source_image(
        self,
        session: Session,
        *,
        source_image_id: UUID,
        expected_version: int,
        actor: Principal,
    ) -> PaperWorkspace:
        workspace_id = self._workspace_id_for_image(session, source_image_id)

        def mutation(context: LockedWorkspace) -> MutationChange:
            source_image = session.scalar(
                select(StructureSourceImage)
                .where(
                    StructureSourceImage.id == source_image_id,
                    StructureSourceImage.workspace_id == context.workspace.id,
                )
                .with_for_update()
            )
            if source_image is None:
                raise WorkspaceNotFoundError("Resource not found")
            before = source_image_snapshot(source_image)
            session.delete(source_image)
            return MutationChange(
                entity_type="structure_source_image",
                entity_id=source_image.id,
                action="structure_source_image.delete",
                before_value=before,
                after_value=None,
            )

        return self.workspace_service.mutate(
            session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            actor=actor,
            mutation=mutation,
        ).workspace


__all__ = [
    "StructureSourceImageDuplicateError",
    "StructureSourceImageList",
    "StructureSourceImageMutation",
    "StructureSourceImageService",
    "StructureSourceImageValidationError",
    "source_image_snapshot",
]
