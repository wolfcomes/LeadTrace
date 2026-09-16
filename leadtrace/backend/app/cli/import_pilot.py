from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.assets.storage import LocalAssetStore
from app.catalog.service import CatalogImportService
from app.config import get_settings
from app.database import bootstrap_database, transactional_session


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate or import the 20-paper pilot catalog")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = get_settings()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    source_root_key = str(manifest.get("source_root_key", ""))
    store = LocalAssetStore(
        settings.asset_root,
        source_roots={source_root_key: args.source_root},
    )
    service = CatalogImportService(args.manifest, store)
    if args.dry_run:
        result = service.preview()
    else:
        resources = bootstrap_database(settings)
        try:
            with transactional_session(resources.session_factory) as session:
                result = service.apply(session)
        finally:
            resources.close()
    print(
        f"verified={result.verified_count} created={result.created_count} "
        f"unchanged={result.unchanged_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
