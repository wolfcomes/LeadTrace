from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence
from uuid import UUID

from app.assets.storage import LocalAssetStore
from app.config import get_settings
from app.database import bootstrap_database, transactional_session
from app.imports.proposal_backfill import backfill_machine_evidence
from app.imports.reconcile import DEFAULT_EXPECTED_AGGREGATE, DEFAULT_SOURCE_MANIFEST
from app.imports.service import BaselineImporter


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.import_proposals",
        description="Append OCSR/Region machine evidence in a successor Release.",
    )
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument(
        "--source-fingerprint",
        required=True,
        help="64-character baseline source fingerprint",
    )
    parser.add_argument("--actor-id", type=UUID, required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument(
        "--source-manifest",
        type=Path,
        default=DEFAULT_SOURCE_MANIFEST,
    )
    parser.add_argument(
        "--expected-aggregate",
        type=Path,
        default=DEFAULT_EXPECTED_AGGREGATE,
    )
    parser.add_argument("--managed-asset-root", type=Path)
    parser.add_argument("--title", default=None)
    parser.add_argument("--notes", default="")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = get_settings()
    resources = bootstrap_database(settings)
    try:
        managed_asset_root = args.managed_asset_root or settings.asset_root
        # The importer manifest identifies the immutable source workspace that
        # backs ``source:*`` asset keys in a Release.  Build the same physical
        # store used by release validation so idempotent replays verify that
        # the referenced PDF/crop files still exist and match their metadata.
        importer = BaselineImporter(
            args.source_root,
            managed_asset_root=managed_asset_root,
            expected_path=args.expected_aggregate,
            source_manifest_path=args.source_manifest,
        )
        validation_store = LocalAssetStore(
            managed_asset_root,
            source_roots={"baseline": importer.manifest_workspace_root()},
        )
        with transactional_session(resources.session_factory) as session:
            result = backfill_machine_evidence(
                session,
                source_root=args.source_root,
                managed_asset_root=managed_asset_root,
                source_manifest_path=args.source_manifest,
                expected_path=args.expected_aggregate,
                actor_id=args.actor_id,
                source_fingerprint=args.source_fingerprint,
                idempotency_key=args.idempotency_key,
                title=args.title,
                notes=args.notes,
                asset_store=validation_store,
            )
    except (OSError, ValueError):
        print("machine evidence backfill failed", file=sys.stderr)
        return 2
    finally:
        resources.close()
    print(
        " ".join(
            [
                f"release_id={result.release.id}",
                f"release_key={result.release.release_key}",
                f"idempotent={str(result.idempotent).lower()}",
                f"added_proposals={result.added_proposals}",
                f"added_regions={result.added_regions}",
            ]
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
