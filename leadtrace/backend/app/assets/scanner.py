from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assets.models import (
    Asset,
    AssetAccessLevel,
    AssetCategory,
    AssetIntegrityState,
    AssetScanCheckpoint,
)
from app.assets.service import AssetService
from app.assets.storage import AssetMimeMismatchError, AssetPathError, LocalAssetStore


def classify_source_asset(source_key: PurePosixPath) -> AssetCategory:
    path = source_key.as_posix().casefold()
    name = source_key.name.casefold()
    suffixes = "".join(source_key.suffixes).casefold()
    suffix = source_key.suffix.casefold()
    if "quarantine/" in path:
        return AssetCategory.QUARANTINE
    if "staging/" in path:
        return AssetCategory.UPLOAD_STAGING
    if "render_cache/" in path or "/render-cache/" in path:
        return AssetCategory.RENDER_CACHE
    if "molecule_pair_structures/" in path or "pair_panel" in name:
        return AssetCategory.PAIR_PANEL
    if "generated_structures/" in path:
        return AssetCategory.RDKIT_STRUCTURE
    if "thumbnails/" in path or "thumbnail" in name:
        return AssetCategory.PAGE_THUMBNAIL
    if "explicit_path_pages/" in path or "page_render" in name:
        return AssetCategory.PAGE_RENDER
    if "08_ocsr_benchmark/crops/" in path or "molecule_ocr_variant" in path:
        return AssetCategory.OCSR_INPUT
    if "ocsr" in name and suffix in {".csv", ".json"}:
        return AssetCategory.OCSR_PROPOSAL
    if "reviewed/" in path or "molecule_objects/" in path:
        return AssetCategory.REVIEWED_CROP
    if "evidence/crops/" in path or "evidence_crop" in name:
        return AssetCategory.EVIDENCE_CROP
    if "exports/" in path or "release-" in name and suffixes.endswith(".tar.gz"):
        return AssetCategory.RELEASE_EXPORT
    if "validation" in name or name.endswith("_summary.json"):
        return AssetCategory.VALIDATION_REPORT
    if "01_manifest/" in path or "manifest" in name:
        return AssetCategory.IMPORT_MANIFEST
    if "external/" in path or name == "source.json":
        return AssetCategory.EXTERNAL_SOURCE
    is_si = any(
        marker in path
        for marker in ("supporting/", "supplement", "_si_", " si ")
    )
    if suffix == ".pdf":
        return AssetCategory.SI_PDF if is_si else AssetCategory.ARTICLE_PDF
    if suffix in {".csv", ".xlsx", ".xls"} and is_si:
        return AssetCategory.SI_TABLE
    if suffix in {".zip", ".tar", ".gz"} and is_si:
        return AssetCategory.SI_ARCHIVE
    raise ValueError(f"Cannot classify source asset: {source_key.as_posix()}")


def _default_access(category: AssetCategory) -> AssetAccessLevel:
    if category in {
        AssetCategory.EVIDENCE_CROP,
        AssetCategory.RDKIT_STRUCTURE,
        AssetCategory.PAIR_PANEL,
    }:
        return AssetAccessLevel.VISITOR
    if category in {
        AssetCategory.ARTICLE_PDF,
        AssetCategory.SI_PDF,
        AssetCategory.SI_TABLE,
        AssetCategory.SI_ARCHIVE,
        AssetCategory.PAGE_RENDER,
        AssetCategory.PAGE_THUMBNAIL,
        AssetCategory.OCSR_INPUT,
        AssetCategory.OCSR_PROPOSAL,
        AssetCategory.REVIEWED_CROP,
    }:
        return AssetAccessLevel.REVIEWER
    return AssetAccessLevel.ADMIN


@dataclass(frozen=True, slots=True)
class ScanItem:
    source_key: str
    status: str
    reason: str | None = None
    asset_id: str | None = None
    sha256: str | None = None


@dataclass(slots=True)
class ScanReport:
    source_root_key: str
    discovered: int = 0
    registered: int = 0
    skipped: int = 0
    quarantined: int = 0
    rejected: int = 0
    duplicates: int = 0
    items: list[ScanItem] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class SourceScanner:
    def __init__(
        self,
        store: LocalAssetStore,
        service: AssetService | None = None,
    ) -> None:
        self.store = store
        self.service = service or AssetService()

    def scan(
        self,
        session: Session,
        *,
        source_root_key: str,
        source_root: Path,
        report_path: Path | None = None,
    ) -> ScanReport:
        configured_root = self.store.source_roots.get(source_root_key)
        root = source_root.resolve()
        if configured_root != root:
            raise AssetPathError("Scanner root does not match configured source root")
        report = ScanReport(source_root_key=source_root_key)
        candidates = sorted(
            (
                path
                for path in root.rglob("*")
                if path.is_file() or path.is_symlink()
            ),
            key=lambda path: unicodedata.normalize(
                "NFC", path.relative_to(root).as_posix()
            ),
        )
        for path in candidates:
            report.discovered += 1
            source_key = path.relative_to(root).as_posix()
            try:
                storage_key = self.store.source_storage_key(
                    source_root_key,
                    source_key,
                )
                inspected = self.store.inspect(storage_key)
            except AssetPathError:
                report.rejected += 1
                report.items.append(
                    ScanItem(source_key=source_key, status="rejected", reason="path_escape")
                )
                continue
            except AssetMimeMismatchError:
                try:
                    inspected = self.store.inspect(
                        storage_key,
                        validate_extension=False,
                        validate_content=False,
                    )
                except FileNotFoundError:
                    self._reject(report, source_key, "missing")
                    continue
                except (AssetPathError, OSError):
                    self._reject(report, source_key, "unreadable")
                    continue
                if self._has_checkpoint(
                    session,
                    source_root_key,
                    source_key,
                    inspected.sha256,
                ):
                    report.skipped += 1
                    report.items.append(
                        ScanItem(source_key=source_key, status="skipped", sha256=inspected.sha256)
                    )
                    continue
                category = self._safe_category(source_key)
                asset, _ = self.service.register_inspected(
                    session,
                    storage_key=storage_key,
                    inspected=inspected,
                    category=category,
                    access_level=AssetAccessLevel.ADMIN,
                    integrity_state=AssetIntegrityState.QUARANTINED,
                    source_metadata={"source_root_key": source_root_key, "reason": "mime_mismatch"},
                )
                self._checkpoint(session, source_root_key, source_key, asset)
                report.quarantined += 1
                report.items.append(
                    ScanItem(
                        source_key=source_key,
                        status="quarantined",
                        reason="mime_mismatch",
                        asset_id=str(asset.id),
                        sha256=asset.sha256,
                    )
                )
                continue
            except FileNotFoundError:
                self._reject(report, source_key, "missing")
                continue
            except OSError:
                self._reject(report, source_key, "unreadable")
                continue
            if self._has_checkpoint(
                session,
                source_root_key,
                source_key,
                inspected.sha256,
            ):
                report.skipped += 1
                report.items.append(
                    ScanItem(source_key=source_key, status="skipped", sha256=inspected.sha256)
                )
                continue
            try:
                category = classify_source_asset(PurePosixPath(source_key))
            except ValueError:
                category = AssetCategory.QUARANTINE
            is_duplicate = session.scalar(
                select(Asset.id).where(
                    Asset.sha256 == inspected.sha256,
                    Asset.integrity_state == AssetIntegrityState.VERIFIED,
                ).limit(1)
            ) is not None
            integrity_state = (
                AssetIntegrityState.QUARANTINED
                if category is AssetCategory.QUARANTINE
                else AssetIntegrityState.VERIFIED
            )
            asset, created = self.service.register_inspected(
                session,
                storage_key=storage_key,
                inspected=inspected,
                category=category,
                access_level=_default_access(category),
                integrity_state=integrity_state,
                source_metadata={"source_root_key": source_root_key},
            )
            self._checkpoint(session, source_root_key, source_key, asset)
            if integrity_state is AssetIntegrityState.QUARANTINED:
                report.quarantined += 1
                status = "quarantined"
                reason = "unclassifiable"
            else:
                report.registered += int(created)
                if is_duplicate:
                    report.duplicates += 1
                status = "registered"
                reason = None
            report.items.append(
                ScanItem(
                    source_key=source_key,
                    status=status,
                    reason=reason,
                    asset_id=str(asset.id),
                    sha256=asset.sha256,
                )
            )
        if report_path is not None:
            self._write_report(report_path, report)
        return report

    @staticmethod
    def _reject(report: ScanReport, source_key: str, reason: str) -> None:
        report.rejected += 1
        report.items.append(
            ScanItem(source_key=source_key, status="rejected", reason=reason)
        )

    @staticmethod
    def _safe_category(source_key: str) -> AssetCategory:
        try:
            return classify_source_asset(PurePosixPath(source_key))
        except ValueError:
            return AssetCategory.QUARANTINE

    @staticmethod
    def _has_checkpoint(
        session: Session,
        source_root_key: str,
        source_key: str,
        sha256: str,
    ) -> bool:
        return session.scalar(
            select(AssetScanCheckpoint.id).where(
                AssetScanCheckpoint.source_root_key == source_root_key,
                AssetScanCheckpoint.source_key == source_key,
                AssetScanCheckpoint.content_sha256 == sha256,
            )
        ) is not None

    @staticmethod
    def _checkpoint(
        session: Session,
        source_root_key: str,
        source_key: str,
        asset: Asset,
    ) -> None:
        session.add(
            AssetScanCheckpoint(
                source_root_key=source_root_key,
                source_key=source_key,
                content_sha256=asset.sha256,
                asset_id=asset.id,
                scanned_at=datetime.now(UTC),
            )
        )
        session.flush()

    @staticmethod
    def _write_report(path: Path, report: ScanReport) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
                json.dump(
                    report.as_dict(),
                    handle,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        finally:
            temporary_path = Path(temporary_name)
            if temporary_path.exists():
                temporary_path.unlink()
