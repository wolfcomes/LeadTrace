from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID


LEADTRACE_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = LEADTRACE_ROOT / "backend"
REPOSITORY_ROOT = LEADTRACE_ROOT.parent
for module_root in (REPOSITORY_ROOT, BACKEND_ROOT):
    if str(module_root) not in sys.path:
        sys.path.insert(0, str(module_root))

from leadtrace.ops.backup.asset_chain import resolve_asset_chain  # noqa: E402
from leadtrace.ops.backup.verify_backup import verify_backup  # noqa: E402
from leadtrace.ops.restore.verify_restored_system import (  # noqa: E402
    PAPER_CENTRIC_COUNT_KEYS,
    PAPER_CENTRIC_INTEGRITY_KEYS,
    _safe_database_counts,
)


Status = Literal["PASS", "FAIL"]
RESTORE_COUNT_KEYS = frozenset(PAPER_CENTRIC_COUNT_KEYS)
RESTORE_INTEGRITY_KEYS = frozenset(PAPER_CENTRIC_INTEGRITY_KEYS)
RESTORE_HTTP_CHECKS = frozenset({"papers", "paper_detail", "authorized_pdf", "audit"})
ACCEPTANCE_CHECK_KEYS = frozenset(
    {
        "manual_workflow",
        "ai_prefill_workflow",
        "request_changes_resubmission",
        "not_reported_section",
        "invalid_structure_blocker",
        "missing_evidence_blocker",
        "ai_reviewer_race",
        "visual_desktop",
        "visual_mobile",
        "backup_restore",
    }
)
VISUAL_ACCEPTANCE_CHECK_KEYS = frozenset(
    {
        "rdkit_pixels",
        "ketcher",
        "pdf_pixels",
        "compounds_desktop_layout",
        "lineage",
        "compounds_mobile_layout",
        "admin_desktop_layout",
        "admin_mobile_layout",
    }
)
IMMUTABLE_HISTORY_TRIGGERS = {
    ("change_events", "trg_change_events_append_only"): (
        "O",
        "leadtrace_reject_change_event_mutation",
    ),
    ("paper_submissions", "protect_paper_submission"): (
        "O",
        "leadtrace_protect_paper_submission",
    ),
    ("admin_decisions", "protect_admin_decision"): (
        "O",
        "leadtrace_protect_publication_history",
    ),
    ("published_paper_versions", "protect_published_paper_version"): (
        "O",
        "leadtrace_protect_publication_history",
    ),
}
RACE_SCIENCE_COUNT_KEYS = (
    "activities",
    "compounds",
    "edge_evidence_links",
    "evidence",
    "lineage_edges",
    "lineage_members",
    "lineages",
    "structure_source_images",
    "structures",
)


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    status: Status
    summary: str
    evidence: dict[str, object]

    @property
    def ok(self) -> bool:
        return self.status == "PASS"

    @classmethod
    def passed(
        cls,
        name: str,
        summary: str,
        **evidence: object,
    ) -> "CheckResult":
        return cls(name, "PASS", summary, evidence)

    @classmethod
    def failed(
        cls,
        name: str,
        summary: str,
        **evidence: object,
    ) -> "CheckResult":
        return cls(name, "FAIL", summary, evidence)

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "summary": self.summary,
            "evidence": self.evidence,
        }


Probe = Callable[[Mapping[str, object]], CheckResult]


@dataclass(frozen=True, slots=True)
class PreflightProbes:
    database: Probe
    services: Probe
    permissions: Probe
    source_manifest: Probe


@dataclass(frozen=True, slots=True)
class PreflightReport:
    generated_at: datetime
    checks: tuple[CheckResult, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "generated_at": self.generated_at.isoformat().replace("+00:00", "Z"),
            "status": "PASS" if self.ok else "FAIL",
            "checks": [check.as_dict() for check in self.checks],
        }


def _timestamp(value: object, *, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} timestamp is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} timestamp has no UTC offset")
    return parsed.astimezone(UTC)


def _required_config(
    config: Mapping[str, object],
    key: str,
    expected: type | tuple[type, ...],
) -> object:
    value = config.get(key)
    if not isinstance(value, expected) or (
        isinstance(value, str) and not value.strip()
    ):
        raise ValueError(f"preflight configuration field is required: {key}")
    return value


def _backup_check(
    name: str,
    config: Mapping[str, object],
    *,
    metadata_key: str,
    expected_scope: str,
    now: datetime,
) -> CheckResult:
    try:
        metadata_path = Path(str(_required_config(config, metadata_key, str))).resolve(
            strict=True
        )
        report = verify_backup(metadata_path)
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        completed_at = _timestamp(payload.get("completed_at"), label=name)
        maximum_age = timedelta(
            hours=float(_required_config(config, "max_backup_age_hours", (int, float)))
        )
        destination = payload.get("destination")
        destination_kind = (
            destination.get("kind") if isinstance(destination, dict) else None
        )
        if report.backup_scope != expected_scope:
            raise ValueError("backup scope does not match cutover requirement")
        if (
            completed_at > now + timedelta(minutes=5)
            or now - completed_at > maximum_age
        ):
            raise ValueError("backup is stale or has an invalid completion time")
        if destination_kind not in {"separate_disk", "controlled_network"}:
            raise ValueError("backup destination is not physically independent")
        versions = payload.get("versions", {})
        expected_versions = {
            "application": config.get("application_version"),
            "schema": config.get("schema_revision"),
            "release": config.get("backup_version_marker"),
        }
        if versions != expected_versions:
            raise ValueError("backup versions do not match the cutover target")
        return CheckResult.passed(
            name,
            "Verified recent encrypted backup",
            backup_id=report.backup_id,
            destination_identity=destination.get("identity"),
            completed_at=completed_at.isoformat().replace("+00:00", "Z"),
        )
    except Exception:
        return CheckResult.failed(name, "Backup evidence is missing, invalid, or stale")


def _expected_restore_baseline(
    config: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    expected_key = (
        "restore_expected_aggregate"
        if config.get("restore_expected_aggregate")
        else "expected_aggregate"
    )
    expected_path = Path(
        str(_required_config(config, expected_key, str))
    ).resolve(strict=True)
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    if not isinstance(expected, dict) or expected.get("schema_version") != 2:
        raise ValueError("approved expected aggregate is invalid")
    counts = expected.get("counts")
    integrity = expected.get("integrity_expectations")
    for values, required_keys, label in (
        (counts, RESTORE_COUNT_KEYS, "counts"),
        (integrity, RESTORE_INTEGRITY_KEYS, "integrity"),
    ):
        if (
            not isinstance(values, dict)
            or set(values) != required_keys
            or any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                for value in values.values()
            )
        ):
            raise ValueError(f"approved expected aggregate {label} is invalid")
    assert isinstance(counts, dict)
    assert isinstance(integrity, dict)
    return counts, integrity


def _restore_rto_seconds(config: Mapping[str, object]) -> int:
    value = config.get("restore_rto_seconds")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("preflight configuration field is required: restore_rto_seconds")
    return value


def _validate_restore_report(
    payload: Mapping[str, object],
    *,
    expected_counts: Mapping[str, object],
    expected_integrity: Mapping[str, object],
    expected_rto_seconds: int,
) -> datetime:
    if payload.get("schema_version") != 2:
        raise ValueError("restore report schema is unsupported")
    if payload.get("ok") is not True or payload.get("errors") != []:
        raise ValueError("restore drill did not pass")
    for section_name in ("assets", "baseline", "http"):
        section = payload.get(section_name)
        if not isinstance(section, dict) or section.get("ok") is not True:
            raise ValueError(f"restore report {section_name} check did not pass")

    assets = payload["assets"]
    baseline = payload["baseline"]
    http = payload["http"]
    assert isinstance(assets, dict)
    assert isinstance(baseline, dict)
    assert isinstance(http, dict)
    file_count = assets.get("file_count")
    if (
        isinstance(file_count, bool)
        or not isinstance(file_count, int)
        or file_count < 0
        or assets.get("errors") != []
    ):
        raise ValueError("restore report asset evidence is incomplete")
    counts = baseline.get("counts")
    integrity = baseline.get("integrity")
    for values, required_keys, label in (
        (counts, RESTORE_COUNT_KEYS, "counts"),
        (integrity, RESTORE_INTEGRITY_KEYS, "integrity"),
    ):
        if (
            not isinstance(values, dict)
            or set(values) != required_keys
            or any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                for value in values.values()
            )
        ):
            raise ValueError(f"restore report baseline {label} is incomplete")
    if counts != expected_counts or integrity != expected_integrity:
        raise ValueError("restore report baseline differs from the approved aggregate")
    if baseline.get("schema_version") != 2:
        raise ValueError("restore report baseline schema is unsupported")
    if baseline.get("integrity_ok") is not True or any(
        type(value) is not int or value != 0 for value in integrity.values()
    ):
        raise ValueError("restore report baseline integrity is not clean")
    http_checks = http.get("checks")
    if not isinstance(http_checks, dict) or any(
        http_checks.get(name) is not True for name in RESTORE_HTTP_CHECKS
    ):
        raise ValueError("restore report HTTP evidence is incomplete")

    started_at = _timestamp(payload.get("started_at"), label="restore drill start")
    completed_at = _timestamp(
        payload.get("completed_at"), label="restore drill completion"
    )
    if completed_at < started_at:
        raise ValueError("restore drill completion precedes its start")
    duration = payload.get("duration_seconds")
    measured_duration = int((completed_at - started_at).total_seconds())
    if isinstance(duration, bool) or not isinstance(duration, int) or duration < 0:
        raise ValueError("restore drill duration is invalid")
    if duration != measured_duration:
        raise ValueError("restore drill duration does not match its timestamps")

    rto = payload.get("rto")
    if not isinstance(rto, dict):
        raise ValueError("restore drill RTO evidence is missing")
    target = rto.get("target_seconds")
    met = rto.get("met")
    if isinstance(target, bool) or not isinstance(target, int) or target <= 0:
        raise ValueError("restore drill RTO target is invalid")
    if target != expected_rto_seconds:
        raise ValueError("restore drill RTO target differs from the cutover target")
    if not isinstance(met, bool) or met != (duration <= target):
        raise ValueError("restore drill RTO result is inconsistent")
    if not met:
        raise ValueError("restore drill exceeded its RTO")
    return completed_at


def _restore_check(
    config: Mapping[str, object],
    *,
    now: datetime,
) -> CheckResult:
    try:
        report_path = Path(
            str(_required_config(config, "restore_report", str))
        ).resolve(strict=True)
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("restore report must contain an object")
        expected_counts, expected_integrity = _expected_restore_baseline(config)
        completed_at = _validate_restore_report(
            payload,
            expected_counts=expected_counts,
            expected_integrity=expected_integrity,
            expected_rto_seconds=_restore_rto_seconds(config),
        )
        maximum_age = timedelta(
            days=float(_required_config(config, "max_restore_age_days", (int, float)))
        )
        if (
            completed_at > now + timedelta(minutes=5)
            or now - completed_at > maximum_age
        ):
            return CheckResult.failed(
                "restore_drill", "Restore drill evidence is stale"
            )
        evidence = payload.get("backup_evidence")
        if not isinstance(evidence, dict):
            raise ValueError("restore backup evidence is missing")
        expected_versions = {
            "application": config["application_version"],
            "schema": config["schema_revision"],
            "release": config["backup_version_marker"],
        }
        selected = {
            "database": Path(
                str(_required_config(config, "database_backup_metadata", str))
            ).resolve(strict=True),
            "assets": Path(
                str(_required_config(config, "asset_backup_metadata", str))
            ).resolve(strict=True),
        }
        for key, metadata_path in selected.items():
            verification = verify_backup(metadata_path)
            actual = evidence.get(key)
            if not isinstance(actual, dict):
                raise ValueError("restore backup evidence is incomplete")
            metadata_hash = hashlib.sha256(metadata_path.read_bytes()).hexdigest()
            if (
                actual.get("backup_id") != verification.backup_id
                or actual.get("metadata_sha256") != metadata_hash
                or actual.get("versions") != expected_versions
            ):
                raise ValueError("restore evidence references different backups")
        asset_evidence = evidence["assets"]
        assert isinstance(asset_evidence, dict)
        resolved_chain = resolve_asset_chain(selected["assets"])
        expected_chain = []
        for node in resolved_chain:
            node_payload = json.loads(node.metadata_path.read_text(encoding="utf-8"))
            expected_chain.append(
                {
                    "backup_id": node.backup_id,
                    "metadata_sha256": hashlib.sha256(
                        node.metadata_path.read_bytes()
                    ).hexdigest(),
                    "archive_sha256": node_payload["artifacts"]["asset_archive"][
                        "sha256"
                    ],
                }
            )
        if (
            asset_evidence.get("chain_backup_ids")
            != [node.backup_id for node in resolved_chain]
            or asset_evidence.get("chain") != expected_chain
        ):
            raise ValueError("restore asset chain evidence is invalid")
        return CheckResult.passed(
            "restore_drill",
            "Recent isolated restore drill passed for the selected backups",
            completed_at=completed_at.isoformat().replace("+00:00", "Z"),
        )
    except Exception:
        return CheckResult.failed(
            "restore_drill",
            "Restore drill backup evidence is missing, mismatched, or invalid",
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _required_uuid(values: Mapping[str, object], key: str) -> UUID:
    value = values.get(key)
    if not isinstance(value, str):
        raise ValueError(f"acceptance evidence field is invalid: {key}")
    try:
        return UUID(value)
    except ValueError as error:
        raise ValueError(f"acceptance evidence field is invalid: {key}") from error


def _required_sha256(values: Mapping[str, object], key: str) -> str:
    value = values.get(key)
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"acceptance evidence field is invalid: {key}")
    return value


def _load_acceptance_evidence(
    path: Path,
    *,
    application_commit: str,
    schema_revision: str,
    pilot_manifest_sha256: str,
) -> dict[str, object]:
    payload = json.loads(path.resolve(strict=True).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("acceptance evidence schema is unsupported")
    if payload.get("application_commit") != application_commit:
        raise ValueError("acceptance evidence application commit does not match")
    if payload.get("schema_revision") != schema_revision:
        raise ValueError("acceptance evidence schema revision does not match")
    if payload.get("pilot_manifest_sha256") != pilot_manifest_sha256:
        raise ValueError("acceptance evidence manifest hash does not match")

    checks = payload.get("checks")
    if (
        not isinstance(checks, dict)
        or set(checks) != ACCEPTANCE_CHECK_KEYS
        or any(value != "PASS" for value in checks.values())
    ):
        raise ValueError("acceptance evidence gates are incomplete or did not pass")

    workflows = payload.get("workflows")
    if not isinstance(workflows, dict):
        raise ValueError("acceptance workflow evidence is missing")
    manual = workflows.get("manual")
    ai = workflows.get("ai_prefill")
    if not isinstance(manual, dict) or not isinstance(ai, dict):
        raise ValueError("manual and AI workflow evidence is required")
    manual_paper_id = _required_uuid(manual, "paper_id")
    ai_paper_id = _required_uuid(ai, "paper_id")
    if manual_paper_id == ai_paper_id:
        raise ValueError("manual and AI workflows must use distinct Papers")
    for workflow in (manual, ai):
        _required_uuid(workflow, "submission_id")
        _required_uuid(workflow, "published_version_id")
        submission_hash = _required_sha256(workflow, "submission_content_hash")
        published_hash = _required_sha256(workflow, "published_content_hash")
        if submission_hash != published_hash:
            raise ValueError("submission and publication hashes do not match")
    if ai.get("ai_run_status") != "succeeded":
        raise ValueError("AI workflow did not record a succeeded prefill run")
    _required_uuid(ai, "ai_run_id")
    reviewer_events = ai.get("reviewer_change_event_count")
    if type(reviewer_events) is not int or reviewer_events <= 0:
        raise ValueError("AI workflow has no Reviewer change evidence")
    if ai.get("structure_uuid_stable") is not True:
        raise ValueError("AI Structure identity was not preserved")

    race = payload.get("ai_race")
    if not isinstance(race, dict):
        raise ValueError("AI and Reviewer race evidence is missing")
    race_paper_id = _required_uuid(race, "paper_id")
    _required_uuid(race, "workspace_id")
    _required_uuid(race, "run_id")
    _required_uuid(race, "reviewer_change_event_id")
    race_entity_id = _required_uuid(race, "entity_id")
    expected_after_value = race.get("expected_after_value")
    science_counts = race.get("science_row_counts_after_race")
    if (
        race.get("run_status") != "superseded"
        or race.get("human_value_preserved") is not True
        or race.get("entity_type") != "paper"
        or race_entity_id != race_paper_id
        or race.get("field") != "title"
        or not isinstance(expected_after_value, str)
        or not expected_after_value.strip()
        or not isinstance(science_counts, dict)
        or set(science_counts) != set(RACE_SCIENCE_COUNT_KEYS)
        or any(
            type(value) is not int or value != 0
            for value in science_counts.values()
        )
    ):
        raise ValueError("AI and Reviewer race did not preserve human data")
    artifacts = payload.get("artifact_sha256")
    if not isinstance(artifacts, dict):
        raise ValueError("acceptance artifact hashes are missing")
    _required_sha256(artifacts, "visual_acceptance")
    return payload


def _load_visual_acceptance(
    path: Path,
    *,
    expected_sha256: str,
    application_commit: str,
) -> dict[str, object]:
    report_path = path.resolve(strict=True)
    if _sha256_file(report_path) != expected_sha256:
        raise ValueError("visual acceptance report hash does not match")
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    checks = payload.get("checks") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or payload.get("application_commit") != application_commit
        or payload.get("status") != "PASS"
        or payload.get("source_pdfs_mutated") is not False
        or not isinstance(checks, dict)
        or set(checks) != VISUAL_ACCEPTANCE_CHECK_KEYS
        or payload.get("browser_errors") != []
        or payload.get("failed_responses") != []
    ):
        raise ValueError("visual acceptance report did not pass every required check")

    screenshots = payload.get("screenshots")
    if not isinstance(screenshots, list) or not screenshots:
        raise ValueError("visual acceptance screenshots are missing")
    report_directory = report_path.parent
    for screenshot in screenshots:
        if not isinstance(screenshot, dict):
            raise ValueError("visual acceptance screenshot entry is invalid")
        filename = screenshot.get("file")
        byte_size = screenshot.get("byte_size")
        expected_hash = _required_sha256(screenshot, "sha256")
        if (
            not isinstance(filename, str)
            or not filename.strip()
            or Path(filename).is_absolute()
            or ".." in Path(filename).parts
            or isinstance(byte_size, bool)
            or not isinstance(byte_size, int)
            or byte_size <= 0
        ):
            raise ValueError("visual acceptance screenshot entry is invalid")
        screenshot_path = report_directory / filename
        resolved_screenshot = screenshot_path.resolve(strict=True)
        if (
            not resolved_screenshot.is_relative_to(report_directory)
            or screenshot_path.is_symlink()
            or not resolved_screenshot.is_file()
            or resolved_screenshot.stat().st_size != byte_size
            or _sha256_file(resolved_screenshot) != expected_hash
        ):
            raise ValueError("visual acceptance screenshot bytes do not match")
    return payload


def _acceptance_check(config: Mapping[str, object]) -> CheckResult:
    try:
        manifest_path = Path(
            str(_required_config(config, "pilot_manifest", str))
        ).resolve(strict=True)
        manifest_hash = _sha256_file(manifest_path)
        evidence_path = Path(
            str(_required_config(config, "acceptance_evidence", str))
        )
        evidence = _load_acceptance_evidence(
            evidence_path,
            application_commit=str(
                _required_config(config, "application_commit", str)
            ),
            schema_revision=str(_required_config(config, "schema_revision", str)),
            pilot_manifest_sha256=manifest_hash,
        )
        artifact_hashes = evidence["artifact_sha256"]
        assert isinstance(artifact_hashes, dict)
        _load_visual_acceptance(
            Path(str(_required_config(config, "visual_acceptance_report", str))),
            expected_sha256=_required_sha256(
                artifact_hashes, "visual_acceptance"
            ),
            application_commit=str(
                _required_config(config, "application_commit", str)
            ),
        )
        return CheckResult.passed(
            "acceptance_evidence",
            "Manual, AI-prefilled, race, blocker, visual, and restore gates passed",
            pilot_manifest_sha256=manifest_hash,
        )
    except Exception:
        return CheckResult.failed(
            "acceptance_evidence",
            "Paper-centric pilot acceptance evidence is missing, mismatched, or incomplete",
        )


def run_preflight(
    config: Mapping[str, object],
    *,
    probes: PreflightProbes | None = None,
    now: datetime | None = None,
) -> PreflightReport:
    checked_at = (now or datetime.now(UTC)).astimezone(UTC)
    if config.get("schema_version") != 2:
        raise ValueError("unsupported preflight configuration schema version")
    for key in (
        "application_version",
        "application_commit",
        "schema_revision",
        "backup_version_marker",
    ):
        _required_config(config, key, str)
    active_probes = probes or DEFAULT_PROBES
    checks = (
        _backup_check(
            "database_backup",
            config,
            metadata_key="database_backup_metadata",
            expected_scope="database",
            now=checked_at,
        ),
        _backup_check(
            "asset_backup",
            config,
            metadata_key="asset_backup_metadata",
            expected_scope="assets",
            now=checked_at,
        ),
        _restore_check(config, now=checked_at),
        _acceptance_check(config),
        active_probes.database(config),
        active_probes.services(config),
        active_probes.permissions(config),
        active_probes.source_manifest(config),
    )
    return PreflightReport(checked_at, checks)


def _pilot_manifest(config: Mapping[str, object]) -> tuple[dict[str, object], Path]:
    path = Path(str(_required_config(config, "pilot_manifest", str))).resolve(
        strict=True
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or not isinstance(payload.get("source_root_key"), str)
        or not isinstance(entries, list)
        or len(entries) != 20
    ):
        raise ValueError("pilot manifest must contain exactly 20 entries")
    return payload, path


def _configured_storage(
    config: Mapping[str, object],
) -> tuple[Path, dict[str, Path]]:
    managed_root = Path(str(_required_config(config, "asset_root", str))).resolve(
        strict=True
    )
    if not managed_root.is_dir():
        raise ValueError("asset root is unavailable")
    raw_source_roots = config.get("source_roots")
    if not isinstance(raw_source_roots, dict) or not raw_source_roots:
        raise ValueError("source_roots must be a nonempty object")
    source_roots: dict[str, Path] = {}
    for key, value in raw_source_roots.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("source_roots contains an invalid entry")
        source_root = Path(value).resolve(strict=True)
        if not source_root.is_dir():
            raise ValueError("source root is unavailable")
        source_roots[key] = source_root
    return managed_root, source_roots


def _validate_pilot_catalog(
    session_factory: object,
    config: Mapping[str, object],
) -> dict[str, object]:
    from sqlalchemy import func, select, text

    from app.assets.models import Asset, AssetCategory
    from app.assets.storage import LocalAssetStore
    from app.audit.service import AuditService
    from app.catalog.models import PaperSource
    from app.papers.models import Paper
    from app.structures.models import Structure
    from app.users.models import User, UserRole

    manifest, manifest_path = _pilot_manifest(config)
    entries = manifest["entries"]
    assert isinstance(entries, list)
    source_root_key = str(manifest["source_root_key"])
    managed_root, source_roots = _configured_storage(config)
    if set(source_roots) != {source_root_key}:
        raise ValueError("configured Source roots do not match the pilot manifest")
    store = LocalAssetStore(managed_root, source_roots=source_roots)

    with session_factory() as session:  # type: ignore[operator]
        actual_schema = session.execute(
            select(text("version_num")).select_from(text("alembic_version"))
        ).scalar_one()
        if actual_schema != config.get("schema_revision"):
            raise ValueError("database schema does not match configured target")
        paper_count = int(session.scalar(select(func.count()).select_from(Paper)) or 0)
        source_count = int(
            session.scalar(select(func.count()).select_from(PaperSource)) or 0
        )
        source_asset_count = int(
            session.scalar(
                select(func.count())
                .select_from(Asset)
                .where(Asset.category == AssetCategory.ARTICLE_PDF)
            )
            or 0
        )
        if (paper_count, source_count, source_asset_count) != (20, 20, 20):
            raise ValueError(
                "pilot database must contain exactly 20 Papers, PaperSources, and source Assets"
            )
        enabled_admins = int(
            session.scalar(
                select(func.count())
                .select_from(User)
                .where(User.role == UserRole.ADMIN, User.is_enabled.is_(True))
            )
            or 0
        )
        if enabled_admins != 1:
            raise ValueError("pilot database must contain exactly one enabled Admin")

        triggers = {
            (str(row.table_name), str(row.trigger_name)): (
                str(row.enabled_state),
                str(row.function_name),
            )
            for row in session.execute(
                text(
                    "SELECT c.relname AS table_name, t.tgname AS trigger_name, "
                    "t.tgenabled AS enabled_state, p.proname AS function_name "
                    "FROM pg_trigger t "
                    "JOIN pg_class c ON c.oid = t.tgrelid "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "JOIN pg_proc p ON p.oid = t.tgfoid "
                    "WHERE NOT t.tgisinternal AND n.nspname = 'public'"
                )
            )
        }
        if any(
            triggers.get(identity) != expected
            for identity, expected in IMMUTABLE_HISTORY_TRIGGERS.items()
        ):
            raise ValueError(
                "required immutable-history triggers are missing, disabled, or replaced"
            )

        duplicate_structures = int(
            session.execute(
                select(func.count())
                .select_from(
                    select(Structure.compound_id)
                    .group_by(Structure.compound_id)
                    .having(func.count(Structure.id) > 1)
                    .subquery()
                )
            ).scalar_one()
        )
        if duplicate_structures:
            raise ValueError("a Compound has more than one Structure")

        rows = session.execute(
            select(Paper, PaperSource, Asset)
            .join(PaperSource, PaperSource.id == Paper.source_id)
            .join(Asset, Asset.id == PaperSource.asset_id)
        ).all()
        actual_by_key = {
            (source.source_root_key, source.source_key): (paper, source, asset)
            for paper, source, asset in rows
        }
        expected_by_key: dict[tuple[str, str], Mapping[str, object]] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("pilot manifest entry is invalid")
            source_key = entry.get("source_key")
            sha256 = entry.get("sha256")
            byte_size = entry.get("byte_size")
            if (
                not isinstance(source_key, str)
                or not isinstance(sha256, str)
                or len(sha256) != 64
                or type(byte_size) is not int
                or byte_size <= 0
            ):
                raise ValueError("pilot manifest entry is invalid")
            key = (source_root_key, source_key)
            if key in expected_by_key:
                raise ValueError("pilot manifest contains a duplicate Source path")
            expected_by_key[key] = entry
        if set(actual_by_key) != set(expected_by_key):
            raise ValueError("database does not match the pilot manifest")

        for key, entry in expected_by_key.items():
            _, source, asset = actual_by_key[key]
            expected_storage_key = store.source_storage_key(*key)
            try:
                inspected = store.inspect(expected_storage_key)
            except (OSError, ValueError) as error:
                raise ValueError(
                    "pilot manifest or Source PDF bytes do not match"
                ) from error
            if (
                source.sha256 != entry["sha256"]
                or source.byte_size != entry["byte_size"]
                or asset.sha256 != entry["sha256"]
                or asset.byte_size != entry["byte_size"]
                or asset.storage_key != expected_storage_key
                or inspected.sha256 != entry["sha256"]
                or inspected.byte_size != entry["byte_size"]
                or inspected.mime_type != "application/pdf"
            ):
                raise ValueError("pilot manifest or Source PDF bytes do not match")
        if not AuditService().verify_chain(session).valid:
            raise ValueError("audit chain is invalid")
    return {
        "schema_revision": actual_schema,
        "paper_count": paper_count,
        "paper_source_count": source_count,
        "source_asset_count": source_asset_count,
        "enabled_admin_count": enabled_admins,
        "pilot_manifest_sha256": _sha256_file(manifest_path),
    }


def _validate_acceptance_database(
    session_factory: object,
    evidence: Mapping[str, object],
) -> None:
    from sqlalchemy import func, select

    from app.activities.models import Activity
    from app.ai_prefill.models import AiExtractionRun, AiExtractionRunStatus
    from app.compounds.models import Compound
    from app.evidence.models import EdgeEvidenceLink, Evidence
    from app.lineages.models import Lineage, LineageEdge, LineageMember
    from app.papers.models import Paper
    from app.publications.models import (
        AdminDecision,
        AdminDecisionAction,
        PublishedPaperVersion,
    )
    from app.structure_images.models import StructureSourceImage
    from app.structures.models import Structure
    from app.workspaces.models import ChangeActorKind, ChangeEvent, PaperSubmission

    workflows = evidence["workflows"]
    race = evidence["ai_race"]
    assert isinstance(workflows, dict)
    assert isinstance(race, dict)
    with session_factory() as session:  # type: ignore[operator]
        has_not_reported_section = False
        for name in ("manual", "ai_prefill"):
            workflow = workflows[name]
            assert isinstance(workflow, dict)
            paper_id = _required_uuid(workflow, "paper_id")
            submission_id = _required_uuid(workflow, "submission_id")
            published_id = _required_uuid(workflow, "published_version_id")
            content_hash = _required_sha256(workflow, "submission_content_hash")
            paper = session.get(Paper, paper_id)
            submission = session.get(PaperSubmission, submission_id)
            published = session.get(PublishedPaperVersion, published_id)
            if (
                paper is None
                or submission is None
                or published is None
                or submission.paper_id != paper_id
                or published.paper_id != paper_id
                or published.submission_id != submission_id
                or submission.content_hash != content_hash
                or published.content_hash != content_hash
                or paper.current_published_version_id != published_id
            ):
                raise ValueError("acceptance workflow publication identity is invalid")
            sections = published.snapshot.get("sections")
            if not isinstance(sections, list):
                raise ValueError("published acceptance snapshot sections are invalid")
            has_not_reported_section = has_not_reported_section or any(
                isinstance(section, dict) and section.get("state") == "not_reported"
                for section in sections
            )

        if not has_not_reported_section:
            raise ValueError("published acceptance snapshots lack not_reported")

        ai_workflow = workflows["ai_prefill"]
        assert isinstance(ai_workflow, dict)
        ai_run = session.get(AiExtractionRun, _required_uuid(ai_workflow, "ai_run_id"))
        if (
            ai_run is None
            or ai_run.paper_id != _required_uuid(ai_workflow, "paper_id")
            or ai_run.status is not AiExtractionRunStatus.SUCCEEDED
        ):
            raise ValueError("acceptance AI run is invalid")
        reviewer_event_count = int(
            session.scalar(
                select(func.count())
                .select_from(ChangeEvent)
                .where(
                    ChangeEvent.paper_id == ai_run.paper_id,
                    ChangeEvent.actor_kind == ChangeActorKind.REVIEWER,
                    ChangeEvent.action != "workspace.submit",
                )
            )
            or 0
        )
        if reviewer_event_count != ai_workflow["reviewer_change_event_count"]:
            raise ValueError("Reviewer change-event count does not match evidence")
        stable_structure_edit = session.scalar(
            select(ChangeEvent).where(
                ChangeEvent.paper_id == ai_run.paper_id,
                ChangeEvent.actor_kind == ChangeActorKind.REVIEWER,
                ChangeEvent.entity_type == "structure",
                ChangeEvent.action == "structure.update",
            )
        )
        if stable_structure_edit is None:
            raise ValueError("Reviewer did not edit the AI Structure in place")

        request_changes_count = int(
            session.scalar(
                select(func.count())
                .select_from(AdminDecision)
                .where(AdminDecision.action == AdminDecisionAction.REQUEST_CHANGES)
            )
            or 0
        )
        if request_changes_count < 1:
            raise ValueError("request-changes and resubmission evidence is missing")

        race_paper_id = _required_uuid(race, "paper_id")
        race_workspace_id = _required_uuid(race, "workspace_id")
        race_entity_id = _required_uuid(race, "entity_id")
        race_field = race.get("field")
        expected_after_value = race.get("expected_after_value")
        race_run = session.get(AiExtractionRun, _required_uuid(race, "run_id"))
        race_event = session.get(
            ChangeEvent, _required_uuid(race, "reviewer_change_event_id")
        )
        race_paper = session.get(Paper, race_paper_id)
        if (
            race_run is None
            or race_event is None
            or race_paper is None
            or race_run.paper_id != race_paper_id
            or race_run.status is not AiExtractionRunStatus.SUPERSEDED
            or race_event.paper_id != race_paper_id
            or race_event.workspace_id != race_workspace_id
            or race_event.entity_type != "paper"
            or race_event.entity_id != race_entity_id
            or race_entity_id != race_paper_id
            or race_event.action != "bibliography.update"
            or race_event.actor_kind is not ChangeActorKind.REVIEWER
            or race_field != "title"
            or not isinstance(expected_after_value, str)
            or not isinstance(race_event.after_value, dict)
            or race_event.after_value.get(race_field) != expected_after_value
            or getattr(race_paper, race_field, None) != expected_after_value
        ):
            raise ValueError("AI and Reviewer race database evidence is invalid")

        expected_science_counts = race.get("science_row_counts_after_race")
        science_models = {
            "activities": Activity,
            "compounds": Compound,
            "edge_evidence_links": EdgeEvidenceLink,
            "evidence": Evidence,
            "lineage_edges": LineageEdge,
            "lineage_members": LineageMember,
            "lineages": Lineage,
            "structure_source_images": StructureSourceImage,
            "structures": Structure,
        }
        if (
            not isinstance(expected_science_counts, dict)
            or set(expected_science_counts) != set(science_models)
        ):
            raise ValueError("AI and Reviewer race science evidence is invalid")
        actual_science_counts = {
            name: int(
                session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.workspace_id == race_workspace_id)
                )
                or 0
            )
            for name, model in science_models.items()
        }
        if (
            any(
                type(value) is not int or value != 0
                for value in expected_science_counts.values()
            )
            or actual_science_counts != expected_science_counts
        ):
            raise ValueError("AI and Reviewer race created scientific rows")


def _database_probe(config: Mapping[str, object]) -> CheckResult:
    database_url = os.environ.get("LEADTRACE_DATABASE_URL", "").strip()
    try:
        if not database_url:
            raise ValueError("database URL is not configured")
        from sqlalchemy.orm import sessionmaker

        from app.database import create_database_engine, validate_schema_version

        managed_root, source_roots = _configured_storage(config)
        engine = create_database_engine(database_url)
        try:
            validate_schema_version(engine)
            sessions = sessionmaker(bind=engine, expire_on_commit=False)
            catalog = _validate_pilot_catalog(sessions, config)
            aggregate = _safe_database_counts(
                database_url,
                asset_root=managed_root,
                source_roots=source_roots,
            )
            expected_path = Path(
                str(_required_config(config, "expected_aggregate", str))
            ).resolve(strict=True)
            expected = json.loads(expected_path.read_text(encoding="utf-8"))
            if (
                expected.get("schema_version") != 2
                or aggregate.get("counts") != expected.get("counts")
                or aggregate.get("integrity")
                != expected.get("integrity_expectations")
                or any(
                    type(value) is not int or value != 0
                    for value in aggregate.get("integrity", {}).values()
                )
            ):
                raise ValueError("paper-centric aggregate does not match or is unclean")
            manifest_hash = str(catalog["pilot_manifest_sha256"])
            evidence = _load_acceptance_evidence(
                Path(str(_required_config(config, "acceptance_evidence", str))),
                application_commit=str(
                    _required_config(config, "application_commit", str)
                ),
                schema_revision=str(
                    _required_config(config, "schema_revision", str)
                ),
                pilot_manifest_sha256=manifest_hash,
            )
            _validate_acceptance_database(sessions, evidence)
        finally:
            engine.dispose()
        if version("leadtrace-backend") != config["application_version"]:
            raise ValueError("application version does not match configured target")
        runtime_commit = os.environ.get("LEADTRACE_APPLICATION_COMMIT", "").strip()
        if runtime_commit != config["application_commit"]:
            raise ValueError("application commit does not match configured target")
        return CheckResult.passed(
            "database",
            "Paper-centric schema, 20-Paper catalog, history, assets, audit, and workflows validated",
            **catalog,
        )
    except Exception:
        return CheckResult.failed(
            "database",
            "Paper-centric database, catalog, history, asset, audit, or workflow validation failed",
        )


def _services_probe(config: Mapping[str, object]) -> CheckResult:
    try:
        import httpx
        import redis

        from app.worker import celery_app

        asset_root = Path(str(_required_config(config, "asset_root", str))).resolve(
            strict=True
        )
        if not asset_root.is_dir() or not os.access(
            asset_root, os.R_OK | os.W_OK | os.X_OK
        ):
            raise ValueError("asset storage is unavailable")
        redis_url = os.environ.get("LEADTRACE_REDIS_URL", "").strip()
        if not redis_url or not redis.Redis.from_url(redis_url).ping():
            raise ValueError("Redis is unavailable")
        worker_replies = celery_app.control.inspect(timeout=5.0).ping() or {}
        if not any(
            isinstance(reply, dict) and reply.get("ok") == "pong"
            for reply in worker_replies.values()
        ):
            raise ValueError("Celery worker is unavailable")
        base_url = str(_required_config(config, "base_url", str)).rstrip("/")
        if urlparse(base_url).scheme != "https":
            raise ValueError("LeadTrace URL must use HTTPS")
        old_dashboard_url = str(
            _required_config(config, "old_dashboard_url", str)
        ).rstrip("/")
        with httpx.Client(timeout=5.0, follow_redirects=False) as client:
            live = client.get(f"{base_url}/health/live")
            ready = client.get(f"{base_url}/health/ready")
            fallback = client.get(f"{old_dashboard_url}/")
        if live.status_code != 200 or ready.status_code != 200:
            raise ValueError("LeadTrace health checks failed")
        if fallback.status_code != 200:
            raise ValueError("old Dashboard fallback is unavailable")
        return CheckResult.passed(
            "services",
            "HTTPS, database-adjacent services, storage, and fallback are ready",
        )
    except Exception:
        return CheckResult.failed(
            "services",
            "HTTPS, Redis, storage, readiness, or fallback check failed",
        )


def _login(client: object, username: str, password: str) -> tuple[bool, str]:
    response = client.post(  # type: ignore[attr-defined]
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    if response.status_code != 200:
        return False, ""
    return True, str(response.json().get("csrf_token", ""))


def _permissions_probe(config: Mapping[str, object]) -> CheckResult:
    try:
        import httpx

        base_url = str(_required_config(config, "base_url", str)).rstrip("/")
        paper_id = str(_required_config(config, "representative_paper_id", str))
        unassigned_paper_id = str(
            _required_config(config, "unassigned_paper_id", str)
        )
        draft_workspace_id = str(
            _required_config(config, "draft_workspace_id", str)
        )
        credentials = {
            role: (
                os.environ.get(f"LEADTRACE_PREFLIGHT_{role.upper()}_USERNAME", ""),
                os.environ.get(f"LEADTRACE_PREFLIGHT_{role.upper()}_PASSWORD", ""),
            )
            for role in ("visitor", "reviewer", "admin")
        }
        if any(
            not username or not password for username, password in credentials.values()
        ):
            raise ValueError("preflight role credentials are incomplete")
        with httpx.Client(
            base_url=base_url, timeout=5.0, follow_redirects=False
        ) as visitor:
            visitor_ok, _ = _login(visitor, *credentials["visitor"])
            visitor_checks = (
                visitor.get("/api/v2/papers?page=1&page_size=1").status_code == 200,
                visitor.get(f"/api/v2/papers/{paper_id}/source-pdf").status_code
                in {403, 404},
                visitor.get(f"/api/v2/workspaces/{draft_workspace_id}").status_code
                == 404,
                visitor.get("/api/v1/users").status_code == 403,
            )
        with httpx.Client(
            base_url=base_url, timeout=5.0, follow_redirects=False
        ) as reviewer:
            reviewer_ok, _ = _login(reviewer, *credentials["reviewer"])
            reviewer_checks = (
                reviewer.get(f"/api/v2/papers/{paper_id}/source-pdf").status_code
                in {200, 206},
                reviewer.get(
                    f"/api/v2/papers/{unassigned_paper_id}/source-pdf"
                ).status_code
                == 404,
                reviewer.get(
                    f"/api/v2/workspaces/{draft_workspace_id}"
                ).status_code
                == 200,
                reviewer.get("/api/v1/users").status_code == 403,
                reviewer.get("/api/v2/admin/papers?page=1&page_size=1").status_code
                == 403,
            )
        with httpx.Client(
            base_url=base_url, timeout=5.0, follow_redirects=False
        ) as admin:
            admin_ok, _ = _login(admin, *credentials["admin"])
            admin_checks = (
                admin.get("/api/v1/users").status_code == 200,
                admin.get("/api/v2/admin/papers?page=1&page_size=1").status_code
                == 200,
                admin.get("/api/v2/admin/submissions").status_code == 200,
                admin.get("/api/v1/audit/verify").status_code == 200,
            )
        if not all(
            (
                visitor_ok,
                reviewer_ok,
                admin_ok,
                *visitor_checks,
                *reviewer_checks,
                *admin_checks,
            )
        ):
            raise ValueError("permission matrix smoke test failed")
        return CheckResult.passed(
            "permissions",
            "Visitor, Reviewer, and Admin permission smoke tests passed",
        )
    except Exception:
        return CheckResult.failed(
            "permissions",
            "Role login or permission matrix smoke test failed",
        )


def _source_manifest_probe(config: Mapping[str, object]) -> CheckResult:
    try:
        from app.assets.storage import LocalAssetStore

        manifest, path = _pilot_manifest(config)
        managed_root, source_roots = _configured_storage(config)
        source_root_key = str(manifest["source_root_key"])
        if set(source_roots) != {source_root_key}:
            raise ValueError("source roots do not match manifest")
        store = LocalAssetStore(managed_root, source_roots=source_roots)
        entries = manifest["entries"]
        assert isinstance(entries, list)
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(
                entry.get("source_key"), str
            ):
                raise ValueError("pilot manifest entry is invalid")
            inspected = store.inspect(
                store.source_storage_key(source_root_key, entry["source_key"])
            )
            if (
                inspected.sha256 != entry.get("sha256")
                or inspected.byte_size != entry.get("byte_size")
                or inspected.mime_type != "application/pdf"
            ):
                raise ValueError("Source PDF changed")
        return CheckResult.passed(
            "source_manifest",
            "All 20 protected Source PDFs match the approved pilot manifest",
            file_differences=0,
            pilot_manifest_sha256=_sha256_file(path),
        )
    except Exception:
        return CheckResult.failed(
            "source_manifest",
            "Approved pilot manifest is missing or a protected Source PDF changed",
        )


DEFAULT_PROBES = PreflightProbes(
    database=_database_probe,
    services=_services_probe,
    permissions=_permissions_probe,
    source_manifest=_source_manifest_probe,
)


def write_report(path: Path, payload: dict[str, object]) -> None:
    destination = path.resolve(strict=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the LeadTrace production cutover preflight."
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    config = json.loads(args.config.resolve(strict=True).read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise SystemExit("preflight config must contain a JSON object")
    report = run_preflight(config)
    payload = report.as_dict()
    if args.report:
        write_report(args.report, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
