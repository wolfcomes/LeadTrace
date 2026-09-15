from __future__ import annotations

from pathlib import Path

from app.cli import import_proposals as proposals_cli
from app.assets.storage import LocalAssetStore
from app.config import Settings
from app.releases.service import publish_approved_baseline
from tests.releases.test_baseline_publish import (
    _approve,
    _asset_store,
    _import_candidate,
)


pytest_plugins = ("tests.imports.conftest",)


def test_backfill_cli_supplies_a_physical_asset_store(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory,
    monkeypatch,
) -> None:
    source_root = baseline_fixture["source_root"]
    manifest_path = baseline_fixture["manifest_path"]
    assert isinstance(source_root, Path)
    assert isinstance(manifest_path, Path)
    database_url = str(auth_session_factory.kw["bind"].url)
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        asset_root=tmp_path / "managed",
    )
    monkeypatch.setattr(proposals_cli, "get_settings", lambda: settings)
    captured: dict[str, object] = {}

    def capture_backfill(*args: object, **kwargs: object) -> None:
        del args
        captured.update(kwargs)
        raise OSError("Stop after capturing the physical asset store")

    monkeypatch.setattr(
        proposals_cli,
        "backfill_machine_evidence",
        capture_backfill,
    )

    exit_code = proposals_cli.main(
        [
            "--source-root",
            str(source_root),
            "--source-manifest",
            str(manifest_path),
            "--source-fingerprint",
            "f" * 64,
            "--actor-id",
            "00000000-0000-4000-8000-000000000001",
            "--idempotency-key",
            "machine-evidence-cli-asset-store",
        ]
    )

    assert exit_code == 2
    assert isinstance(captured["asset_store"], LocalAssetStore)


def test_backfill_cli_reports_source_failures_without_printing_paths(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
    auth_session_factory,
    monkeypatch,
    capsys,
) -> None:
    with auth_session_factory.begin() as session:
        admin, candidate = _import_candidate(session, tmp_path, baseline_fixture)
        _approve(session, admin, candidate)
        baseline = publish_approved_baseline(
            session,
            candidate_id=candidate.id,
            actor_id=admin.id,
            title="Baseline",
            idempotency_key="baseline-for-backfill-cli",
            asset_store=_asset_store(tmp_path, baseline_fixture),
        ).release
        actor_id = admin.id
        source_fingerprint = baseline.metrics["baseline"]["source_fingerprint"]

    database_url = str(auth_session_factory.kw["bind"].url)
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        asset_root=tmp_path / "managed",
    )
    monkeypatch.setattr(proposals_cli, "get_settings", lambda: settings)
    secret_source_path = tmp_path / "private-source-that-does-not-exist"

    exit_code = proposals_cli.main(
        [
            "--source-root",
            str(secret_source_path),
            "--source-fingerprint",
            source_fingerprint,
            "--actor-id",
            str(actor_id),
            "--idempotency-key",
            "machine-evidence-cli-safe-error",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "machine evidence backfill failed" in captured.err
    assert captured.out == ""
    assert str(tmp_path) not in captured.err
