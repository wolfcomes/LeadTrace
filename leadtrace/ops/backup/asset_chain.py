from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from leadtrace.ops.backup.verify_backup import verify_backup  # noqa: E402


MAX_CHAIN_LENGTH = 128


@dataclass(frozen=True, slots=True)
class AssetChainNode:
    metadata_path: Path
    backup_id: str
    position: int
    mode: str
    snapshot_path: Path


def _artifact_path(metadata_path: Path, payload: dict[str, object], name: str) -> Path:
    artifacts = payload["artifacts"]
    assert isinstance(artifacts, dict)
    artifact = artifacts[name]
    assert isinstance(artifact, dict)
    path = metadata_path.parent / str(artifact["path"])
    return path.resolve(strict=True)


def resolve_asset_chain(metadata_path: Path) -> tuple[AssetChainNode, ...]:
    terminal = Path(metadata_path).resolve(strict=True)
    destination = terminal.parent.parent
    reversed_nodes: list[AssetChainNode] = []
    visited: set[str] = set()
    current = terminal
    while True:
        if len(reversed_nodes) >= MAX_CHAIN_LENGTH:
            raise ValueError("asset backup chain exceeds the supported length")
        report = verify_backup(current)
        if report.backup_scope != "assets" or current.parent.name != report.backup_id:
            raise ValueError("asset backup chain directory identity is invalid")
        if report.backup_id in visited:
            raise ValueError("asset backup chain contains a cycle")
        visited.add(report.backup_id)
        payload = json.loads(current.read_text(encoding="utf-8"))
        chain = payload["asset_chain"]
        node = AssetChainNode(
            metadata_path=current,
            backup_id=report.backup_id,
            position=int(chain["position"]),
            mode=str(chain["mode"]),
            snapshot_path=_artifact_path(current, payload, "asset_snapshot"),
        )
        reversed_nodes.append(node)
        parent_backup_id = chain["parent_backup_id"]
        if node.mode == "full":
            break
        current = (
            destination / str(parent_backup_id) / "backup-metadata.json"
        ).resolve(strict=True)
        try:
            current.relative_to(destination)
        except ValueError as error:
            raise ValueError("asset backup parent escapes the destination") from error

    nodes = tuple(reversed(reversed_nodes))
    for expected_position, node in enumerate(nodes):
        if node.position != expected_position:
            raise ValueError("asset backup chain positions are not contiguous")
        if expected_position == 0 and node.mode != "full":
            raise ValueError("asset backup chain does not start with a full backup")
        if expected_position and node.mode != "incremental":
            raise ValueError("asset backup chain contains an unexpected full backup")
    return nodes


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resolve a verified asset backup chain.")
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--next", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    nodes = resolve_asset_chain(args.metadata)
    if args.next:
        if len(nodes) >= MAX_CHAIN_LENGTH:
            raise SystemExit(
                "asset backup chain reached its maximum length; create a new full backup"
            )
        terminal = nodes[-1]
        print(f"{terminal.backup_id}|{terminal.position + 1}|{terminal.snapshot_path}")
    else:
        for node in nodes:
            print(node.metadata_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
