from __future__ import annotations

import json
from pathlib import Path

from app.cli.import_baseline import main


def test_dry_run_cli_writes_machine_readable_report_without_database_or_paths(
    tmp_path: Path,
    baseline_fixture: dict[str, object],
) -> None:
    source_root = baseline_fixture["source_root"]
    manifest_path = baseline_fixture["manifest_path"]
    expected = baseline_fixture["expected"]
    assert isinstance(source_root, Path)
    assert isinstance(manifest_path, Path)
    assert isinstance(expected, dict)
    expected_path = tmp_path / "expected.json"
    expected_path.write_text(json.dumps(expected), encoding="utf-8")
    report_path = tmp_path / "reports" / "dry-run.json"

    exit_code = main(
        [
            "--source-root",
            str(source_root),
            "--dry-run",
            "--report",
            str(report_path),
            "--expected-aggregate",
            str(expected_path),
            "--source-manifest",
            str(manifest_path),
        ]
    )

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["matches_expected"] is True
    assert "workspace_root" not in payload
    assert str(tmp_path) not in report_path.read_text(encoding="utf-8")
