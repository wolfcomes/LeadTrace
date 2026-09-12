from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from leadtrace.ops.backup.asset_chain import resolve_asset_chain  # noqa: E402
from leadtrace.ops.backup.verify_backup import verify_backup  # noqa: E402


def _timestamp(raw: str) -> datetime:
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return parsed.astimezone(UTC)


def _validated_destination(destination: Path, allowed_parent: Path) -> Path:
    root = destination.resolve(strict=True)
    parent = allowed_parent.resolve(strict=True)
    if not root.is_dir() or root.is_symlink() or parent == Path("/"):
        raise ValueError("backup destination or allowed parent is unsafe")
    if root.parent == root:
        raise ValueError("backup destination must not be a filesystem root")
    try:
        relative = root.relative_to(parent)
    except ValueError as error:
        raise ValueError("backup destination is outside its allowed parent") from error
    if relative == Path("."):
        raise ValueError("backup destination must be below its allowed parent")
    return root


def expired_backup_directories(
    destination: Path,
    *,
    allowed_parent: Path,
    cutoff: datetime,
) -> tuple[Path, ...]:
    root = _validated_destination(destination, allowed_parent)
    records: list[tuple[Path, Path, str, datetime]] = []
    for child in sorted(root.iterdir()):
        if child.is_symlink() or not child.is_dir():
            continue
        metadata = child / "backup-metadata.json"
        try:
            report = verify_backup(metadata)
            payload = json.loads(metadata.read_text(encoding="utf-8"))
            completed_at = _timestamp(str(payload["completed_at"]))
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            continue
        if report.backup_id != child.name:
            continue
        records.append((child, metadata, report.backup_scope, completed_at))

    normalized_cutoff = cutoff.astimezone(UTC)
    protected_asset_chain_directories: set[Path] = set()
    for _, metadata, scope, completed_at in records:
        if scope != "assets" or completed_at < normalized_cutoff:
            continue
        protected_asset_chain_directories.update(
            node.metadata_path.parent for node in resolve_asset_chain(metadata)
        )

    return tuple(
        child
        for child, _, _, completed_at in records
        if completed_at < normalized_cutoff
        and child not in protected_asset_chain_directories
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List or prune verified LeadTrace backups past retention."
    )
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--allowed-parent", type=Path, required=True)
    parser.add_argument("--retention-days", type=int, default=30)
    parser.add_argument("--now", help="UTC ISO timestamp; defaults to current time")
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.retention_days < 1:
        raise SystemExit("retention-days must be positive")
    now = _timestamp(args.now) if args.now else datetime.now(UTC)
    root = _validated_destination(args.destination, args.allowed_parent)
    candidates = expired_backup_directories(
        root,
        allowed_parent=args.allowed_parent,
        cutoff=now - timedelta(days=args.retention_days),
    )
    for candidate in candidates:
        if candidate.parent != root or candidate.is_symlink():
            raise SystemExit("refusing non-child retention candidate")
        action = "delete" if args.apply else "preview"
        print(f"backup_id={candidate.name} action={action}")
        if args.apply:
            shutil.rmtree(candidate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
