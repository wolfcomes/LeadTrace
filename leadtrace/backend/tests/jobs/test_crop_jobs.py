from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image
import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.assets.models import (
    Asset,
    AssetAccessLevel,
    AssetCategory,
    AssetIntegrityState,
)
from app.jobs.service import CropRequest, CropService, CropValidationError
from app.users.models import UserRole
from app.users.service import UserService


def _png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (8, 8), "white").save(output, format="PNG")
    return output.getvalue()


def _source_asset(storage_key: str, sha256: str) -> Asset:
    return Asset(
        storage_key=storage_key,
        original_filename=Path(storage_key).name,
        sha256=sha256,
        byte_size=100,
        mime_type="application/pdf",
        category=AssetCategory.ARTICLE_PDF,
        access_level=AssetAccessLevel.REVIEWER,
        integrity_state=AssetIntegrityState.VERIFIED,
        derivation_metadata={},
        source_metadata={},
    )


def test_crop_request_hash_is_deterministic_and_parameter_sensitive() -> None:
    request = CropRequest(
        source_pdf_sha256="a" * 64,
        page_number=2,
        x0=0.1,
        y0=0.2,
        x1=0.8,
        y1=0.9,
        rotation=90,
        padding=12,
        dpi=300,
        renderer_version="pdfium-1",
    )

    assert request.input_hash() == request.input_hash()
    assert request.input_hash() != request.model_copy(padding=13).input_hash()


def test_crop_service_reuses_registered_asset_for_same_request(tmp_path: Path) -> None:
    service = CropService(tmp_path)
    request = CropRequest(
        source_pdf_sha256="b" * 64,
        page_number=1,
        x0=0.0,
        y0=0.0,
        x1=1.0,
        y1=1.0,
        rotation=0,
        padding=0,
        dpi=200,
        renderer_version="test-renderer",
    )
    first = service.run(request, renderer=lambda _: b"PNG")
    second = service.run(request, renderer=lambda _: b"different")

    assert first.asset_key == second.asset_key
    assert first.reused is False
    assert second.reused is True
    assert first.path.read_bytes() == b"PNG"


def test_failed_crop_does_not_leave_registered_asset(tmp_path: Path) -> None:
    service = CropService(tmp_path)
    request = CropRequest(
        source_pdf_sha256="c" * 64,
        page_number=1,
        x0=0.1,
        y0=0.1,
        x1=0.2,
        y1=0.2,
        rotation=0,
        padding=0,
        dpi=200,
        renderer_version="test-renderer",
    )

    def fail(_: CropRequest) -> bytes:
        raise RuntimeError("renderer failed")

    try:
        service.run(request, renderer=fail)
    except RuntimeError:
        pass

    assert service.find(request) is None


def test_distinct_crop_requests_do_not_reclassify_one_content_asset(
    tmp_path: Path,
    auth_session_factory: sessionmaker[Session],
) -> None:
    service = CropService(tmp_path)
    first_request = CropRequest(
        source_pdf_sha256="d" * 64,
        page_number=1,
        x0=0.1,
        y0=0.1,
        x1=0.4,
        y1=0.4,
        rotation=0,
        padding=0,
        dpi=144,
        renderer_version="test-renderer",
    )
    second_request = first_request.model_copy(x0=0.2, x1=0.5)
    content = _png_bytes()

    with auth_session_factory.begin() as session:
        first = service.materialize_persisted(
            session,
            first_request,
            renderer=lambda _: content,
        )
        second = service.materialize_persisted(
            session,
            second_request,
            renderer=lambda _: content,
        )
        first_asset = session.get(Asset, first.asset_id)
        second_asset = session.get(Asset, second.asset_id)

        assert first.asset_id != second.asset_id
        assert first_asset is not None and second_asset is not None
        assert first_asset.storage_key != second_asset.storage_key
        assert first_asset.derivation_metadata["crop_input_hash"] == (
            first_request.input_hash()
        )
        assert second_asset.derivation_metadata["crop_input_hash"] == (
            second_request.input_hash()
        )


def test_identical_crop_request_keeps_source_asset_provenance_isolated(
    tmp_path: Path,
    auth_session_factory: sessionmaker[Session],
) -> None:
    service = CropService(tmp_path)
    request = CropRequest(
        source_pdf_sha256="e" * 64,
        page_number=1,
        x0=0.1,
        y0=0.1,
        x1=0.4,
        y1=0.4,
        rotation=0,
        padding=0,
        dpi=144,
        renderer_version="test-renderer",
    )
    content = _png_bytes()

    with auth_session_factory.begin() as session:
        first_source = _source_asset(
            "source/source_pdfs/first.pdf",
            request.source_pdf_sha256,
        )
        second_source = _source_asset(
            "source/source_pdfs/second.pdf",
            request.source_pdf_sha256,
        )
        session.add_all([first_source, second_source])
        session.flush()

        first = service.materialize_persisted(
            session,
            request,
            renderer=lambda _: content,
            source_asset_id=first_source.id,
        )
        second = service.materialize_persisted(
            session,
            request,
            renderer=lambda _: content,
            source_asset_id=second_source.id,
        )
        first_asset = session.get(Asset, first.asset_id)
        second_asset = session.get(Asset, second.asset_id)

        assert first.asset_id != second.asset_id
        assert first_asset is not None and second_asset is not None
        assert first_asset.storage_key != second_asset.storage_key
        assert first_asset.source_asset_id == first_source.id
        assert second_asset.source_asset_id == second_source.id


def test_enqueue_scopes_job_identity_to_source_asset(
    tmp_path: Path,
    auth_session_factory: sessionmaker[Session],
) -> None:
    service = CropService(tmp_path)
    request = CropRequest(
        source_pdf_sha256="f" * 64,
        page_number=1,
        x0=0.1,
        y0=0.1,
        x1=0.4,
        y1=0.4,
        rotation=0,
        padding=0,
        dpi=144,
        renderer_version="test-renderer",
    )

    with auth_session_factory.begin() as session:
        actor = UserService().create_user(
            session,
            username="crop.provenance.admin",
            display_name="Crop Provenance Admin",
            role=UserRole.ADMIN,
            initial_password="Crop provenance password 2026!",
        )
        first_source = _source_asset(
            "source/source_pdfs/enqueue-first.pdf",
            request.source_pdf_sha256,
        )
        second_source = _source_asset(
            "source/source_pdfs/enqueue-second.pdf",
            request.source_pdf_sha256,
        )
        session.add_all([first_source, second_source])
        session.flush()

        first = service.enqueue(
            session,
            request,
            source_asset_id=first_source.id,
            created_by_id=actor.id,
        )
        second = service.enqueue(
            session,
            request,
            source_asset_id=second_source.id,
            created_by_id=actor.id,
        )

        assert first.id != second.id
        assert first.source_asset_id == first_source.id
        assert second.source_asset_id == second_source.id


def test_run_persisted_scopes_completed_asset_to_source_asset(
    tmp_path: Path,
    auth_session_factory: sessionmaker[Session],
) -> None:
    service = CropService(tmp_path)
    request = CropRequest(
        source_pdf_sha256="9" * 64,
        page_number=1,
        x0=0.1,
        y0=0.1,
        x1=0.4,
        y1=0.4,
        rotation=0,
        padding=0,
        dpi=144,
        renderer_version="test-renderer",
    )
    content = _png_bytes()

    with auth_session_factory.begin() as session:
        first_source = _source_asset(
            "source/source_pdfs/persisted-first.pdf",
            request.source_pdf_sha256,
        )
        second_source = _source_asset(
            "source/source_pdfs/persisted-second.pdf",
            request.source_pdf_sha256,
        )
        session.add_all([first_source, second_source])
        session.flush()

        first = service.run_persisted(
            session,
            request,
            renderer=lambda _: content,
            source_asset_id=first_source.id,
        )
        second = service.run_persisted(
            session,
            request,
            renderer=lambda _: content,
            source_asset_id=second_source.id,
        )
        first_asset = session.get(Asset, first.asset_id)
        second_asset = session.get(Asset, second.asset_id)

        assert first.asset_id != second.asset_id
        assert first_asset is not None and second_asset is not None
        assert first_asset.source_asset_id == first_source.id
        assert second_asset.source_asset_id == second_source.id


def test_run_persisted_rejects_completed_asset_with_wrong_source_provenance(
    tmp_path: Path,
    auth_session_factory: sessionmaker[Session],
) -> None:
    service = CropService(tmp_path)
    request = CropRequest(
        source_pdf_sha256="8" * 64,
        page_number=1,
        x0=0.1,
        y0=0.1,
        x1=0.4,
        y1=0.4,
        rotation=0,
        padding=0,
        dpi=144,
        renderer_version="test-renderer",
    )

    with auth_session_factory.begin() as session:
        expected_source = _source_asset(
            "source/source_pdfs/expected.pdf",
            request.source_pdf_sha256,
        )
        wrong_source = _source_asset(
            "source/source_pdfs/wrong.pdf",
            request.source_pdf_sha256,
        )
        session.add_all([expected_source, wrong_source])
        session.flush()
        result = service.run_persisted(
            session,
            request,
            renderer=lambda _: _png_bytes(),
            source_asset_id=expected_source.id,
        )
        asset = session.get(Asset, result.asset_id)
        assert asset is not None
        asset.source_asset_id = wrong_source.id
        session.flush()

        with pytest.raises(CropValidationError, match="provenance"):
            service.run_persisted(
                session,
                request,
                renderer=lambda _: _png_bytes(),
                source_asset_id=expected_source.id,
            )
