from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

if __package__:
    from .build_manifest import SCHEMA_VERSION, collect_manifest
else:  # Support the documented `python path/to/verify_manifest.py` invocation.
    from build_manifest import SCHEMA_VERSION, collect_manifest


@dataclass(frozen=True)
class VerificationResult:
    counts: dict[str, int]
    differences: dict[str, list[str]]

    @property
    def ok(self) -> bool:
        return not any(self.counts.values())


def verify_manifest(manifest_path: Path) -> VerificationResult:
    path = Path(manifest_path).resolve(strict=True)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported manifest schema version")
    workspace = Path(str(payload["workspace_root"])).resolve(strict=True)
    roots = [workspace / str(root) for root in payload["source_roots"]]
    current = collect_manifest(roots, workspace_root=workspace)
    expected_by_path = {str(row["path"]): row for row in payload["files"]}
    current_by_path = {str(row["path"]): row for row in current["files"]}
    missing = sorted(set(expected_by_path) - set(current_by_path))
    unexpected = sorted(set(current_by_path) - set(expected_by_path))
    changed = sorted(
        relative_path
        for relative_path in set(expected_by_path) & set(current_by_path)
        if expected_by_path[relative_path] != current_by_path[relative_path]
    )
    differences = {
        "changed": changed,
        "missing": missing,
        "unexpected": unexpected,
    }
    return VerificationResult(
        counts={name: len(values) for name, values in differences.items()},
        differences=differences,
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify a source manifest.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    result = verify_manifest(args.manifest)
    if args.as_json:
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "counts": result.counts,
                    "differences": result.differences,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(" ".join(f"{name}={count}" for name, count in result.counts.items()))
        for name, values in result.differences.items():
            for value in values:
                print(f"{name}: {value}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
