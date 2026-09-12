from __future__ import annotations

from pathlib import Path

from app.jobs.service import CropRequest, CropService


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
