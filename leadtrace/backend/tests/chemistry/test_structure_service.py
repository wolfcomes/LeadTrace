from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.assets.models import (
    Asset,
    AssetAccessLevel,
    AssetCategory,
    AssetIntegrityState,
)
from app.assets.service import AssetService
from app.assets.storage import LocalAssetStore
from app.chemistry.drawing import DrawingOptions, render_structure_png
from app.jobs.tasks.structures import run_structure_drawing_job
from app.structures.service import StructureDrawingService
from app.users.models import UserRole
from app.users.service import UserService


def test_drawing_service_reuses_one_verified_immutable_asset(
    tmp_path: Path,
    auth_session_factory: sessionmaker[Session],
) -> None:
    with auth_session_factory.begin() as session:
        reviewer = UserService().create_user(
            session,
            username=f"structure-drawing-{uuid4().hex[:8]}",
            display_name="Structure drawing reviewer",
            role=UserRole.REVIEWER,
            initial_password="Structure drawing password 2026!",
        )
        service = StructureDrawingService(tmp_path)

        first = service.draw(
            session,
            smiles="c1ccccc1",
            created_by_id=reviewer.id,
        )
        canonical_equivalent = service.draw(
            session,
            smiles="C1=CC=CC=C1",
            created_by_id=reviewer.id,
        )
        resized = service.draw(
            session,
            smiles="c1ccccc1",
            options=DrawingOptions(width=601, height=420),
            created_by_id=reviewer.id,
        )

        assert first.asset.id == canonical_equivalent.asset.id
        assert resized.asset.id != first.asset.id
        assert first.reused is False
        assert canonical_equivalent.reused is True
        assert resized.reused is False
        asset = session.get(Asset, first.asset.id)
        assert asset is not None
        assert asset.category is AssetCategory.RDKIT_STRUCTURE
        assert asset.integrity_state is AssetIntegrityState.VERIFIED
        assert asset.mime_type == "image/png"
        assert asset.derivation_metadata["drawing_key"]
        content = (
            tmp_path / asset.storage_key.removeprefix("managed/")
        ).read_bytes()
        assert content.startswith(b"\x89PNG")


def test_background_drawing_job_keeps_the_shared_drawing_contract(
    tmp_path: Path,
    auth_session_factory: sessionmaker[Session],
) -> None:
    with auth_session_factory.begin() as session:
        result = run_structure_drawing_job(
            session,
            managed_root=tmp_path,
            smiles="C1=CC=CC=C1",
        )

        assert result.asset.category is AssetCategory.RDKIT_STRUCTURE
        assert result.path.read_bytes().startswith(b"\x89PNG")
        assert result.drawing_key
        assert result.reused is False


def test_drawing_does_not_reclassify_an_identical_non_structure_asset(
    tmp_path: Path,
    auth_session_factory: sessionmaker[Session],
) -> None:
    content = render_structure_png("CCO")
    store = LocalAssetStore(tmp_path)
    stored = store.put_bytes(content, suffix=".png")
    with auth_session_factory.begin() as session:
        crop, created = AssetService().register_inspected(
            session,
            storage_key=stored.storage_key,
            inspected=store.inspect(stored.storage_key),
            category=AssetCategory.EVIDENCE_CROP,
            access_level=AssetAccessLevel.REVIEWER,
            integrity_state=AssetIntegrityState.VERIFIED,
        )
        assert created is True

        result = StructureDrawingService(tmp_path).draw(
            session,
            smiles="CCO",
        )

        assert result.asset.id != crop.id
        assert result.asset.category is AssetCategory.RDKIT_STRUCTURE
        assert result.asset.access_level is AssetAccessLevel.ADMIN
        assert result.asset.storage_key != crop.storage_key
        assert crop.category is AssetCategory.EVIDENCE_CROP
        assert crop.access_level is AssetAccessLevel.REVIEWER
        assert crop.derivation_metadata == {}


def test_drawing_rejects_tampered_cached_png_and_restores_requested_structure(
    tmp_path: Path,
    auth_session_factory: sessionmaker[Session],
) -> None:
    expected_content = render_structure_png("CCO")
    replacement_content = render_structure_png("CCN")
    assert replacement_content != expected_content

    with auth_session_factory.begin() as session:
        service = StructureDrawingService(tmp_path)
        first = service.draw(session, smiles="CCO")
        first.path.write_bytes(replacement_content)

        redrawn = service.draw(session, smiles="CCO")

        assert redrawn.reused is False
        assert redrawn.path.read_bytes() == expected_content
        assert redrawn.path.read_bytes() != replacement_content
        assert redrawn.asset.integrity_state is AssetIntegrityState.VERIFIED
        inspected = LocalAssetStore(tmp_path).inspect(redrawn.asset.storage_key)
        assert inspected.sha256 == redrawn.asset.sha256
        assert inspected.byte_size == redrawn.asset.byte_size
