from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
from typing import Sequence

from app.config import get_settings
from app.database import bootstrap_database, transactional_session
from app.imports.reconcile import (
    DEFAULT_EXPECTED_AGGREGATE,
    DEFAULT_SOURCE_MANIFEST,
    reconcile_baseline,
)
from app.imports.service import BaselineImporter, ImportValidationError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reconcile or transactionally import the LeadTrace baseline"
    )
    parser.add_argument("--source-root", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--expected-aggregate",
        type=Path,
        default=DEFAULT_EXPECTED_AGGREGATE,
    )
    parser.add_argument(
        "--source-manifest",
        type=Path,
        default=DEFAULT_SOURCE_MANIFEST,
    )
    return parser


def _write_json(path: Path, payload: dict[str, object]) -> None:
    destination = path.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
    finally:
        temporary_path = Path(temporary_name)
        if temporary_path.exists():
            temporary_path.unlink()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = reconcile_baseline(
        args.source_root,
        expected_path=args.expected_aggregate,
        source_manifest_path=args.source_manifest,
    )
    report_payload = report.as_dict()
    if args.report is not None:
        _write_json(args.report, report_payload)
    if not report.matches_expected:
        return 2
    if args.dry_run:
        return 0

    settings = get_settings()
    resources = bootstrap_database(settings)
    try:
        importer = BaselineImporter(
            args.source_root,
            managed_asset_root=settings.asset_root,
            expected_path=args.expected_aggregate,
            source_manifest_path=args.source_manifest,
        )
        with transactional_session(resources.session_factory) as session:
            result = importer.apply(session)
    except ImportValidationError:
        return 2
    finally:
        resources.close()
    print(
        json.dumps(
            {
                "batch_id": str(result.batch_id),
                "release_candidate_id": str(result.release_candidate_id),
                "created": result.created,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
