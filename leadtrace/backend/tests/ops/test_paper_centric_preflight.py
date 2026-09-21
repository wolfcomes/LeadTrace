from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.assets.models import (
    Asset,
    AssetAccessLevel,
    AssetCategory,
    AssetIntegrityState,
)
from app.catalog.models import PaperSource, PaperSourceIntegrityState
from app.papers.models import Paper, PaperCatalogState
from app.users.models import User, UserRole
from leadtrace.ops.cutover.preflight import (
    ACCEPTANCE_CHECK_KEYS,
    CheckResult,
    PreflightProbes,
    _load_acceptance_evidence,
    _validate_acceptance_database,
    _validate_pilot_catalog,
    run_preflight,
)
from leadtrace.ops.restore.verify_restored_system import (
    PAPER_CENTRIC_COUNT_KEYS,
    PAPER_CENTRIC_INTEGRITY_KEYS,
    build_backup_evidence,
)


NOW = datetime(2026, 9, 17, 8, 0, tzinfo=UTC)
SCHEMA_REVISION = "0025_ai_prefill_runs"
APPLICATION_COMMIT = "a" * 40
MANIFEST_SHA256 = "b" * 64


def _write_backup(
    root: Path,
    *,
    backup_id: str,
    scope: str,
    now: datetime = NOW,
) -> Path:
    if scope == "assets":
        root = root / backup_id
    root.mkdir(parents=True)
    artifact_names = {
        "database": {"database_dump": "database.dump.age"},
        "assets": {
            "asset_manifest": "assets.manifest.json",
            "asset_archive": "assets.tar.age",
            "asset_snapshot": "tar.snapshot",
        },
    }[scope]
    artifacts: dict[str, dict[str, object]] = {}
    for name, filename in artifact_names.items():
        content = f"{backup_id}:{name}".encode()
        (root / filename).write_bytes(content)
        artifacts[name] = {
            "path": filename,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }
    payload: dict[str, object] = {
        "schema_version": 1,
        "backup_id": backup_id,
        "backup_scope": scope,
        "started_at": (now - timedelta(minutes=2)).isoformat(),
        "completed_at": now.isoformat(),
        "outcome": "success",
        "versions": {
            "application": "0.1.0",
            "schema": SCHEMA_REVISION,
            "release": "paper-centric-pilot",
        },
        "encryption": {
            "algorithm": "age-x25519",
            "recipient_fingerprint": "SHA256:key",
            "payloads_encrypted": True,
        },
        "destination": {"kind": "separate_disk", "identity": "pilot-disk"},
        "artifacts": artifacts,
    }
    if scope == "assets":
        payload["asset_chain"] = {
            "mode": "full",
            "parent_backup_id": None,
            "position": 0,
        }
    metadata = root / "backup-metadata.json"
    metadata.write_text(json.dumps(payload), encoding="utf-8")
    return metadata


def _write_expected_aggregate(root: Path) -> Path:
    counts = {key: 0 for key in PAPER_CENTRIC_COUNT_KEYS}
    counts.update({"papers": 20, "paper_sources": 20, "assets": 20, "users": 3, "admin_users": 1})
    path = root / "expected-aggregate.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "counts": counts,
                "integrity_expectations": {
                    key: 0 for key in PAPER_CENTRIC_INTEGRITY_KEYS
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _acceptance_payload() -> dict[str, object]:
    manual_hash = "c" * 64
    ai_hash = "d" * 64
    race_title = "Reviewer title wins"
    return {
        "schema_version": 1,
        "application_commit": APPLICATION_COMMIT,
        "schema_revision": SCHEMA_REVISION,
        "pilot_manifest_sha256": MANIFEST_SHA256,
        "checks": {key: "PASS" for key in ACCEPTANCE_CHECK_KEYS},
        "workflows": {
            "manual": {
                "paper_id": "00000000-0000-0000-0000-000000000001",
                "submission_id": "00000000-0000-0000-0000-000000000011",
                "submission_content_hash": manual_hash,
                "published_version_id": "00000000-0000-0000-0000-000000000012",
                "published_content_hash": manual_hash,
            },
            "ai_prefill": {
                "paper_id": "00000000-0000-0000-0000-000000000002",
                "ai_run_id": "00000000-0000-0000-0000-000000000021",
                "ai_run_status": "succeeded",
                "reviewer_change_event_count": 1,
                "structure_uuid_stable": True,
                "submission_id": "00000000-0000-0000-0000-000000000022",
                "submission_content_hash": ai_hash,
                "published_version_id": "00000000-0000-0000-0000-000000000023",
                "published_content_hash": ai_hash,
            },
        },
        "ai_race": {
            "paper_id": "00000000-0000-0000-0000-000000000003",
            "workspace_id": "00000000-0000-0000-0000-000000000030",
            "run_id": "00000000-0000-0000-0000-000000000031",
            "run_status": "superseded",
            "reviewer_change_event_id": "00000000-0000-0000-0000-000000000032",
            "entity_type": "paper",
            "entity_id": "00000000-0000-0000-0000-000000000003",
            "field": "title",
            "expected_after_value": race_title,
            "science_row_counts_after_race": {
                "activities": 0,
                "compounds": 0,
                "edge_evidence_links": 0,
                "evidence": 0,
                "lineage_edges": 0,
                "lineage_members": 0,
                "lineages": 0,
                "structure_source_images": 0,
                "structures": 0,
            },
            "human_value_preserved": True,
        },
        "artifact_sha256": {"visual_acceptance": "e" * 64},
    }


def _write_acceptance(root: Path, payload: dict[str, object] | None = None) -> Path:
    path = root / "acceptance-evidence.json"
    path.write_text(json.dumps(payload or _acceptance_payload()), encoding="utf-8")
    return path


def _write_visual_acceptance(root: Path) -> Path:
    screenshot = root / "visual-screenshot.png"
    screenshot.write_bytes(b"visual-proof")
    path = root / "visual-acceptance.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "application_commit": APPLICATION_COMMIT,
                "status": "PASS",
                "source_pdfs_mutated": False,
                "checks": {
                    "rdkit_pixels": {},
                    "ketcher": {},
                    "pdf_pixels": {},
                    "compounds_desktop_layout": {},
                    "lineage": {},
                    "compounds_mobile_layout": {},
                    "admin_desktop_layout": {},
                    "admin_mobile_layout": {},
                },
                "screenshots": [
                    {
                        "file": screenshot.name,
                        "sha256": hashlib.sha256(screenshot.read_bytes()).hexdigest(),
                        "byte_size": screenshot.stat().st_size,
                    }
                ],
                "browser_errors": [],
                "failed_responses": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_restore_report(
    root: Path,
    *,
    database_metadata: Path,
    asset_metadata: Path,
    schema_version: int = 2,
    integrity_override: tuple[str, int] | None = None,
) -> Path:
    expected = json.loads(_write_expected_aggregate(root).read_text(encoding="utf-8"))
    integrity = dict(expected["integrity_expectations"])
    if integrity_override is not None:
        integrity[integrity_override[0]] = integrity_override[1]
    payload = {
        "schema_version": schema_version,
        "ok": True,
        "assets": {"ok": True, "file_count": 20, "errors": []},
        "baseline": {
            "ok": True,
            "schema_version": 2,
            "counts": expected["counts"],
            "integrity": integrity,
            "integrity_ok": all(value == 0 for value in integrity.values()),
        },
        "http": {
            "ok": True,
            "checks": {
                "papers": True,
                "paper_detail": True,
                "authorized_pdf": True,
                "audit": True,
            },
        },
        "started_at": (NOW - timedelta(minutes=5)).isoformat(),
        "completed_at": NOW.isoformat(),
        "duration_seconds": 300,
        "rto": {"target_seconds": 3600, "met": True},
        "errors": [],
        "backup_evidence": build_backup_evidence(
            database_metadata, asset_metadata
        ),
    }
    path = root / "restore-report.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _config(tmp_path: Path, *, restore_schema: int = 2) -> dict[str, object]:
    database_metadata = _write_backup(
        tmp_path / "database", backup_id="pilot-db", scope="database"
    )
    asset_metadata = _write_backup(
        tmp_path / "assets", backup_id="pilot-assets", scope="assets"
    )
    restore = _write_restore_report(
        tmp_path,
        database_metadata=database_metadata,
        asset_metadata=asset_metadata,
        schema_version=restore_schema,
    )
    manifest = tmp_path / "pilot-manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")
    acceptance = _acceptance_payload()
    acceptance["pilot_manifest_sha256"] = hashlib.sha256(
        manifest.read_bytes()
    ).hexdigest()
    visual = _write_visual_acceptance(tmp_path)
    acceptance["artifact_sha256"] = {
        "visual_acceptance": hashlib.sha256(visual.read_bytes()).hexdigest()
    }
    return {
        "schema_version": 2,
        "application_version": "0.1.0",
        "application_commit": APPLICATION_COMMIT,
        "schema_revision": SCHEMA_REVISION,
        "backup_version_marker": "paper-centric-pilot",
        "database_backup_metadata": str(database_metadata),
        "asset_backup_metadata": str(asset_metadata),
        "restore_report": str(restore),
        "expected_aggregate": str(tmp_path / "expected-aggregate.json"),
        "pilot_manifest": str(manifest),
        "acceptance_evidence": str(_write_acceptance(tmp_path, acceptance)),
        "visual_acceptance_report": str(visual),
        "restore_rto_seconds": 3600,
        "max_backup_age_hours": 4,
        "max_restore_age_days": 31,
    }


def _passing_probes() -> PreflightProbes:
    return PreflightProbes(
        database=lambda _: CheckResult.passed("database", "ok"),
        services=lambda _: CheckResult.passed("services", "ok"),
        permissions=lambda _: CheckResult.passed("permissions", "ok"),
        source_manifest=lambda _: CheckResult.passed("source_manifest", "ok"),
    )


def test_schema_v2_restore_report_is_accepted(tmp_path: Path) -> None:
    config = _config(tmp_path)

    report = run_preflight(config, probes=_passing_probes(), now=NOW)

    assert report.ok is True
    assert report.as_dict()["schema_version"] == 2
    assert {check.name for check in report.checks} == {
        "database_backup",
        "asset_backup",
        "restore_drill",
        "acceptance_evidence",
        "database",
        "services",
        "permissions",
        "source_manifest",
    }


def test_restore_report_uses_its_own_expected_aggregate(tmp_path: Path) -> None:
    config = _config(tmp_path)
    restore_expected = Path(str(config["expected_aggregate"]))
    database_expected = json.loads(restore_expected.read_text(encoding="utf-8"))
    database_expected["counts"]["users"] += 1
    database_expected_path = tmp_path / "database-expected-aggregate.json"
    database_expected_path.write_text(
        json.dumps(database_expected), encoding="utf-8"
    )
    config["expected_aggregate"] = str(database_expected_path)
    config["restore_expected_aggregate"] = str(restore_expected)

    report = run_preflight(config, probes=_passing_probes(), now=NOW)

    restore = next(check for check in report.checks if check.name == "restore_drill")
    assert restore.status == "PASS"


def test_schema_v1_restore_report_is_rejected(tmp_path: Path) -> None:
    config = _config(tmp_path, restore_schema=1)

    report = run_preflight(config, probes=_passing_probes(), now=NOW)

    restore = next(check for check in report.checks if check.name == "restore_drill")
    assert restore.status == "FAIL"


def test_nonzero_restore_integrity_is_rejected(tmp_path: Path) -> None:
    config = _config(tmp_path)
    restore = _write_restore_report(
        tmp_path,
        database_metadata=Path(str(config["database_backup_metadata"])),
        asset_metadata=Path(str(config["asset_backup_metadata"])),
        integrity_override=("audit_chain_invalid", 1),
    )
    config["restore_report"] = str(restore)

    report = run_preflight(config, probes=_passing_probes(), now=NOW)

    restore_check = next(
        check for check in report.checks if check.name == "restore_drill"
    )
    assert restore_check.status == "FAIL"


def test_missing_acceptance_gate_is_rejected(tmp_path: Path) -> None:
    config = _config(tmp_path)
    evidence = _acceptance_payload()
    del evidence["checks"]["visual_mobile"]  # type: ignore[index]
    Path(str(config["acceptance_evidence"])).write_text(
        json.dumps(evidence), encoding="utf-8"
    )

    report = run_preflight(config, probes=_passing_probes(), now=NOW)

    acceptance = next(
        check for check in report.checks if check.name == "acceptance_evidence"
    )
    assert acceptance.status == "FAIL"


def test_tampered_visual_acceptance_report_is_rejected(tmp_path: Path) -> None:
    config = _config(tmp_path)
    Path(str(config["visual_acceptance_report"])).write_text(
        '{"schema_version": 1, "status": "FAIL"}\n', encoding="utf-8"
    )

    report = run_preflight(config, probes=_passing_probes(), now=NOW)

    acceptance = next(
        check for check in report.checks if check.name == "acceptance_evidence"
    )
    assert acceptance.status == "FAIL"


def test_tampered_visual_screenshot_is_rejected(tmp_path: Path) -> None:
    config = _config(tmp_path)
    visual_path = Path(str(config["visual_acceptance_report"]))
    visual = json.loads(visual_path.read_text(encoding="utf-8"))
    screenshot = visual["screenshots"][0]
    (visual_path.parent / screenshot["file"]).write_bytes(b"tampered-visual-proof")

    report = run_preflight(config, probes=_passing_probes(), now=NOW)

    acceptance = next(
        check for check in report.checks if check.name == "acceptance_evidence"
    )
    assert acceptance.status == "FAIL"


def test_visual_acceptance_report_must_match_application_commit(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    visual_path = Path(str(config["visual_acceptance_report"]))
    visual = json.loads(visual_path.read_text(encoding="utf-8"))
    visual["application_commit"] = "f" * 40
    visual_path.write_text(json.dumps(visual), encoding="utf-8")
    acceptance = json.loads(
        Path(str(config["acceptance_evidence"])).read_text(encoding="utf-8")
    )
    acceptance["artifact_sha256"]["visual_acceptance"] = hashlib.sha256(
        visual_path.read_bytes()
    ).hexdigest()
    Path(str(config["acceptance_evidence"])).write_text(
        json.dumps(acceptance), encoding="utf-8"
    )

    report = run_preflight(config, probes=_passing_probes(), now=NOW)

    acceptance_check = next(
        check for check in report.checks if check.name == "acceptance_evidence"
    )
    assert acceptance_check.status == "FAIL"


@pytest.mark.parametrize("defect", ["same-paper", "hash-mismatch"])
def test_acceptance_requires_distinct_workflows_and_matching_hashes(
    tmp_path: Path,
    defect: str,
) -> None:
    payload = _acceptance_payload()
    workflows = payload["workflows"]
    assert isinstance(workflows, dict)
    manual = workflows["manual"]
    ai = workflows["ai_prefill"]
    assert isinstance(manual, dict)
    assert isinstance(ai, dict)
    if defect == "same-paper":
        ai["paper_id"] = manual["paper_id"]
    else:
        ai["published_content_hash"] = "e" * 64
    path = _write_acceptance(tmp_path, payload)

    with pytest.raises(ValueError):
        _load_acceptance_evidence(
            path,
            application_commit=APPLICATION_COMMIT,
            schema_revision=SCHEMA_REVISION,
            pilot_manifest_sha256=MANIFEST_SHA256,
        )


def test_database_acceptance_allows_not_reported_in_only_one_workflow() -> None:
    from app.ai_prefill.models import AiExtractionRun, AiExtractionRunStatus
    from app.publications.models import PublishedPaperVersion
    from app.workspaces.models import ChangeActorKind, PaperSubmission

    evidence = _acceptance_payload()
    workflows = evidence["workflows"]
    race = evidence["ai_race"]
    assert isinstance(workflows, dict)
    assert isinstance(race, dict)

    records: dict[tuple[str, UUID], SimpleNamespace] = {}
    for name, section_state in (("manual", "not_reported"), ("ai_prefill", "completed")):
        workflow = workflows[name]
        assert isinstance(workflow, dict)
        paper_id = UUID(str(workflow["paper_id"]))
        submission_id = UUID(str(workflow["submission_id"]))
        published_id = UUID(str(workflow["published_version_id"]))
        content_hash = str(workflow["submission_content_hash"])
        records[("Paper", paper_id)] = SimpleNamespace(
            id=paper_id,
            current_published_version_id=published_id,
        )
        records[(PaperSubmission.__name__, submission_id)] = SimpleNamespace(
            paper_id=paper_id,
            content_hash=content_hash,
        )
        records[(PublishedPaperVersion.__name__, published_id)] = SimpleNamespace(
            paper_id=paper_id,
            submission_id=submission_id,
            content_hash=content_hash,
            snapshot={"sections": [{"state": section_state}]},
        )

    ai = workflows["ai_prefill"]
    assert isinstance(ai, dict)
    ai_run_id = UUID(str(ai["ai_run_id"]))
    records[(AiExtractionRun.__name__, ai_run_id)] = SimpleNamespace(
        paper_id=UUID(str(ai["paper_id"])),
        status=AiExtractionRunStatus.SUCCEEDED,
    )
    race_run_id = UUID(str(race["run_id"]))
    records[(AiExtractionRun.__name__, race_run_id)] = SimpleNamespace(
        paper_id=UUID(str(race["paper_id"])),
        status=AiExtractionRunStatus.SUPERSEDED,
    )
    race_event_id = UUID(str(race["reviewer_change_event_id"]))
    race_paper_id = UUID(str(race["paper_id"]))
    race_workspace_id = UUID(str(race["workspace_id"]))
    records[("Paper", race_paper_id)] = SimpleNamespace(
        id=race_paper_id,
        title=race["expected_after_value"],
    )
    records[("ChangeEvent", race_event_id)] = SimpleNamespace(
        paper_id=race_paper_id,
        workspace_id=race_workspace_id,
        entity_type=race["entity_type"],
        entity_id=UUID(str(race["entity_id"])),
        action="bibliography.update",
        after_value={race["field"]: race["expected_after_value"]},
        actor_kind=ChangeActorKind.REVIEWER,
    )

    class FakeSession:
        def __init__(self) -> None:
            self.scalar_results = iter((1, SimpleNamespace(), 1, *([0] * 10)))

        def __enter__(self) -> FakeSession:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def get(self, model: type[object], record_id: UUID) -> SimpleNamespace | None:
            return records.get((model.__name__, record_id))

        def scalar(self, _statement: object) -> object:
            return next(self.scalar_results)

    _validate_acceptance_database(FakeSession, evidence)

    bad_evidence = _acceptance_payload()
    bad_race = bad_evidence["ai_race"]
    assert isinstance(bad_race, dict)
    bad_race["expected_after_value"] = "AI overwrote this value"
    with pytest.raises(ValueError, match="race"):
        _validate_acceptance_database(FakeSession, bad_evidence)


def _populate_catalog(
    session_factory: sessionmaker[Session],
    root: Path,
    *,
    count: int = 20,
    enabled_admins: int = 1,
) -> tuple[Path, Path]:
    source_root = root / "source_pdfs"
    source_root.mkdir(parents=True)
    entries: list[dict[str, object]] = []
    with session_factory.begin() as session:
        for index in range(count):
            source_key = f"volume67 issue5/paper-{index + 1:02d}.pdf"
            source_path = source_root / source_key
            source_path.parent.mkdir(parents=True, exist_ok=True)
            content = (
                f"%PDF-1.4\n/Type /Page\npilot-{index + 1}\n%%EOF\n".encode()
            )
            source_path.write_bytes(content)
            digest = hashlib.sha256(content).hexdigest()
            asset = Asset(
                storage_key=f"source/source_pdfs/{source_key}",
                original_filename=source_path.name,
                sha256=digest,
                byte_size=len(content),
                mime_type="application/pdf",
                page_count=1,
                category=AssetCategory.ARTICLE_PDF,
                access_level=AssetAccessLevel.REVIEWER,
                integrity_state=AssetIntegrityState.VERIFIED,
                derivation_metadata={},
                source_metadata={"source_root_key": "source_pdfs"},
            )
            session.add(asset)
            session.flush()
            source = PaperSource(
                asset_id=asset.id,
                source_root_key="source_pdfs",
                source_key=source_key,
                sha256=digest,
                byte_size=len(content),
                page_count=1,
                integrity_state=PaperSourceIntegrityState.VERIFIED,
            )
            session.add(source)
            session.flush()
            session.add(
                Paper(
                    paper_key=f"LT-PILOT-{index + 1:02d}",
                    source_id=source.id,
                    title=f"Pilot paper {index + 1}",
                    journal="Journal of Medicinal Chemistry",
                    publication_year=2024,
                    volume="67",
                    issue="5",
                    doi=None,
                    catalog_state=PaperCatalogState.EXTRACTED,
                )
            )
            entries.append(
                {
                    "manifest_order": index + 1,
                    "original_filename": source_path.name,
                    "source_key": source_key,
                    "sha256": digest,
                    "byte_size": len(content),
                }
            )
        for index in range(enabled_admins):
            session.add(
                User(
                    username=f"admin-{index + 1}",
                    normalized_username=f"admin-{index + 1}",
                    display_name=f"Admin {index + 1}",
                    role=UserRole.ADMIN,
                    is_enabled=True,
                    password_hash="test-only",
                    must_change_password=False,
                )
            )
    manifest = root / "pilot-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_root_key": "source_pdfs",
                "entries": entries,
            }
        ),
        encoding="utf-8",
    )
    return manifest, source_root


def _catalog_config(root: Path, manifest: Path, source_root: Path) -> dict[str, object]:
    managed = root / "managed"
    managed.mkdir()
    return {
        "schema_revision": ScriptDirectory.from_config(Config("alembic.ini")).get_current_head(),
        "pilot_manifest": str(manifest),
        "asset_root": str(managed),
        "source_roots": {"source_pdfs": str(source_root)},
    }


def test_database_catalog_requires_exactly_twenty_papers_sources_and_source_assets(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    del empty_postgresql_database_url
    manifest, source_root = _populate_catalog(
        auth_session_factory, tmp_path, count=19
    )

    with pytest.raises(ValueError, match="exactly 20"):
        _validate_pilot_catalog(
            auth_session_factory,
            _catalog_config(tmp_path, manifest, source_root),
        )


def test_database_catalog_requires_exactly_one_enabled_admin(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    del empty_postgresql_database_url
    manifest, source_root = _populate_catalog(
        auth_session_factory, tmp_path, enabled_admins=2
    )

    with pytest.raises(ValueError, match="one enabled Admin"):
        _validate_pilot_catalog(
            auth_session_factory,
            _catalog_config(tmp_path, manifest, source_root),
        )


def test_database_catalog_detects_missing_immutable_history_trigger(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    del empty_postgresql_database_url
    manifest, source_root = _populate_catalog(auth_session_factory, tmp_path)
    with auth_session_factory.begin() as session:
        session.execute(
            text("DROP TRIGGER trg_change_events_append_only ON change_events")
        )

    with pytest.raises(ValueError, match="immutable-history triggers"):
        _validate_pilot_catalog(
            auth_session_factory,
            _catalog_config(tmp_path, manifest, source_root),
        )


def test_database_catalog_detects_disabled_immutable_history_trigger(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    del empty_postgresql_database_url
    manifest, source_root = _populate_catalog(auth_session_factory, tmp_path)
    with auth_session_factory.begin() as session:
        session.execute(
            text("ALTER TABLE change_events DISABLE TRIGGER trg_change_events_append_only")
        )

    with pytest.raises(ValueError, match="immutable-history triggers"):
        _validate_pilot_catalog(
            auth_session_factory,
            _catalog_config(tmp_path, manifest, source_root),
        )


def test_database_catalog_detects_replaced_immutable_history_trigger_function(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    del empty_postgresql_database_url
    manifest, source_root = _populate_catalog(auth_session_factory, tmp_path)
    with auth_session_factory.begin() as session:
        session.execute(
            text("DROP TRIGGER trg_change_events_append_only ON change_events")
        )
        session.execute(
            text(
                "CREATE FUNCTION leadtrace_test_allow_change_event_mutation() "
                "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN OLD; END; $$"
            )
        )
        session.execute(
            text(
                "CREATE TRIGGER trg_change_events_append_only "
                "BEFORE UPDATE OR DELETE ON change_events FOR EACH ROW "
                "EXECUTE FUNCTION leadtrace_test_allow_change_event_mutation()"
            )
        )

    with pytest.raises(ValueError, match="immutable-history triggers"):
        _validate_pilot_catalog(
            auth_session_factory,
            _catalog_config(tmp_path, manifest, source_root),
        )


def test_database_catalog_validates_manifest_against_source_bytes(
    tmp_path: Path,
    empty_postgresql_database_url: str,
    auth_session_factory: sessionmaker[Session],
) -> None:
    del empty_postgresql_database_url
    manifest, source_root = _populate_catalog(auth_session_factory, tmp_path)
    (source_root / "volume67 issue5/paper-20.pdf").write_bytes(b"tampered")

    with pytest.raises(ValueError, match="manifest or Source PDF"):
        _validate_pilot_catalog(
            auth_session_factory,
            _catalog_config(tmp_path, manifest, source_root),
        )
