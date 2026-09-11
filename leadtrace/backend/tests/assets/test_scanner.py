from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path

from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.assets.models import Asset, AssetIntegrityState, AssetScanCheckpoint
from app.assets.scanner import SourceScanner
from app.assets.service import AssetService
from app.assets.storage import LocalAssetStore


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (8, 8), color="white").save(buffer, format="PNG")
    return buffer.getvalue()


def _snapshot(root: Path) -> dict[str, tuple[int, int, bytes]]:
    return {
        path.relative_to(root).as_posix(): (
            path.stat().st_size,
            path.stat().st_mtime_ns,
            path.read_bytes(),
        )
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


def test_scanner_is_resumable_unicode_safe_and_source_read_only(
    tmp_path: Path,
    auth_session_factory: sessionmaker[Session],
) -> None:
    source = tmp_path / "只读 source (baseline)"
    (source / "论文").mkdir(parents=True)
    (source / "evidence" / "crops").mkdir(parents=True)
    (source / "论文" / "Article (一).pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    (source / "论文" / "Article (二).pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    image_bytes = _png_bytes()
    (source / "evidence" / "crops" / "结构 26a′.png").write_bytes(image_bytes)
    (source / "evidence" / "crops" / "结构 duplicate.png").write_bytes(
        image_bytes
    )
    (source / "论文" / "spoofed.pdf").write_bytes(image_bytes)
    report_path = tmp_path / "reports" / "scan.json"
    before = _snapshot(source)
    store = LocalAssetStore(
        tmp_path / "managed",
        source_roots={"baseline": source},
    )
    scanner = SourceScanner(store)

    with auth_session_factory.begin() as session:
        first = scanner.scan(
            session,
            source_root_key="baseline",
            source_root=source,
            report_path=report_path,
        )
    with auth_session_factory.begin() as session:
        second = scanner.scan(
            session,
            source_root_key="baseline",
            source_root=source,
            report_path=report_path,
        )

    assert _snapshot(source) == before
    assert first.discovered == 5
    assert first.registered == 4
    assert first.quarantined == 1
    assert first.duplicates == 2
    assert second.skipped == 5
    assert json.loads(report_path.read_text(encoding="utf-8"))["source_root_key"] == (
        "baseline"
    )
    with auth_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Asset)) == 5
        assert (
            session.scalar(select(func.count()).select_from(AssetScanCheckpoint)) == 5
        )
        quarantined = session.scalar(
            select(Asset).where(
                Asset.integrity_state == AssetIntegrityState.QUARANTINED
            )
        )
        assert quarantined is not None
        assert quarantined.storage_key.endswith("spoofed.pdf")


def test_scanner_rejects_a_source_symlink_escape(
    tmp_path: Path,
    auth_session_factory: sessionmaker[Session],
) -> None:
    source = tmp_path / "source"
    outside = tmp_path / "outside"
    source.mkdir()
    outside.mkdir()
    (outside / "paper.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    (source / "escape.pdf").symlink_to(outside / "paper.pdf")
    scanner = SourceScanner(
        LocalAssetStore(
            tmp_path / "managed",
            source_roots={"baseline": source},
        )
    )

    with auth_session_factory.begin() as session:
        report = scanner.scan(
            session,
            source_root_key="baseline",
            source_root=source,
        )

    assert report.discovered == 1
    assert report.rejected == 1
    assert report.registered == 0
    assert report.items[0].reason == "path_escape"


def test_integrity_verification_marks_changed_source_corrupt(
    tmp_path: Path,
    auth_session_factory: sessionmaker[Session],
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    paper = source / "paper.pdf"
    paper.write_bytes(b"%PDF-1.4\nfirst\n%%EOF\n")
    store = LocalAssetStore(
        tmp_path / "managed",
        source_roots={"baseline": source},
    )
    scanner = SourceScanner(store)

    with auth_session_factory.begin() as session:
        scanner.scan(session, source_root_key="baseline", source_root=source)
        asset_id = session.scalar(select(Asset.id))
    paper.write_bytes(b"%PDF-1.4\nchanged\n%%EOF\n")
    with auth_session_factory.begin() as session:
        assert AssetService().verify_integrity(session, asset_id, store) is False
    with auth_session_factory() as session:
        asset = session.get(Asset, asset_id)
        assert asset is not None
        assert asset.integrity_state is AssetIntegrityState.CORRUPT
