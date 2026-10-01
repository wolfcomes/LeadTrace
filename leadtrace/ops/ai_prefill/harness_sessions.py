"""Read-only, content-free discovery of persisted DeepSeek Harness sessions.

The installed Harness stores provider-reported usage in its projection cache.
This module reads only cache JSON and directory metadata, never session logs,
prompts, model configuration or credentials. Unknown fields are not exported.
Cache checkpoints are evidence of reported usage, not a complete billing ledger.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
from typing import Any


USAGE_BUCKETS = (
    "uncachedInputTokens",
    "outputTokens",
    "cacheReadTokens",
    "cacheWriteTokens",
)
_SESSION_ID = re.compile(r"session-[A-Za-z0-9-]{1,100}\Z")
_MAX_CACHE_BYTES = 16 * 1024 * 1024


def _integer(value: Any, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def _plain_directory(root: Path, *parts: str) -> Path | None:
    """Do not follow cache/storage child symlinks to unrelated files."""
    path = root
    for part in parts:
        path = path / part
        try:
            if not stat.S_ISDIR(path.lstat().st_mode):
                return None
        except OSError:
            return None
    return path


def _read_cache(path: Path) -> tuple[dict[str, Any], os.stat_result]:
    # O_NOFOLLOW also closes the file-level symlink check/open race.
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_CACHE_BYTES:
            raise ValueError("cache is not a bounded regular file")
        raw = stream.read(_MAX_CACHE_BYTES + 1)
    if len(raw) > _MAX_CACHE_BYTES:
        raise ValueError("cache exceeds size limit")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("cache is not an object")
    return data, metadata


def _persisted_ids(home: Path) -> set[str]:
    """Existence only: directory names are not proof of lifecycle identity."""
    root = _plain_directory(home, "sessions")
    result: set[str] = set()
    if root is None:
        return result
    for cwd_dir in root.iterdir():
        if _plain_directory(root, cwd_dir.name) is None:
            continue
        for entry in cwd_dir.iterdir():
            if _SESSION_ID.fullmatch(entry.name) and _plain_directory(cwd_dir, entry.name):
                result.add(entry.name)
    return result


def _scan(cwds: set[str], home: Path) -> tuple[list[dict[str, Any]], list[str]]:
    cache = _plain_directory(home, "storages", "session_projcache", "sessions")
    if cache is None:
        return [], ["projection_cache_unavailable"]
    persisted = _persisted_ids(home)
    sessions: list[dict[str, Any]] = []
    warnings: list[str] = []
    for path in sorted(cache.glob("session-*.json")):
        session_id = path.stem
        if not _SESSION_ID.fullmatch(session_id) or path.is_symlink():
            warnings.append("ignored_unsafe_cache_entry")
            continue
        try:
            data, metadata = _read_cache(path)
            record = data.get("record")
            if not isinstance(record, dict):
                raise ValueError("missing record")
            identity = record.get("identity")
            if not isinstance(identity, dict):
                raise ValueError("missing identity")
        except (OSError, ValueError, UnicodeError):
            # Never include raw JSON, exception text, title or message fields.
            warnings.append(f"unreadable_projection_cache:{session_id}")
            continue
        cwd = identity.get("cwd")
        if not isinstance(cwd, str) or cwd not in cwds:
            continue
        rows = record.get("rows")
        row = rows.get("tokenUsage") if isinstance(rows, dict) else None
        row = row if isinstance(row, dict) else {}
        val = row.get("val")
        totals = val.get("totals") if isinstance(val, dict) else None
        version = data.get("version")
        row_version = row.get("ver")
        format_version = identity.get("formatVersion")
        usage = None
        status = "unknown_missing_or_invalid_usage"
        if version != 7 or format_version != 3 or row_version != 2:
            status = "unknown_unsupported_cache_schema"
        elif (
            isinstance(totals, dict)
            and _integer(row.get("seq"), -1)
            and all(_integer(totals.get(key)) for key in USAGE_BUCKETS)
        ):
            usage = {key: totals[key] for key in USAGE_BUCKETS}
            status = "provider_reported_cache_checkpoint"
        created = identity.get("createdAt")
        seeded = identity.get("isSeeded")
        inherited = identity.get("inheritedEventCount")
        sessions.append({
            "session_id": session_id,
            "cwd": cwd,
            "created_at_epoch_ms": created if _integer(created) else None,
            "is_seeded": seeded if type(seeded) is bool else None,
            "inherited_event_count": inherited if _integer(inherited) else None,
            "persisted_session_present": session_id in persisted,
            "lifecycle_verified_from_log": False,
            "usage_status": status,
            "usage": usage,
            "checkpoint_complete": None,
            "provenance": {
                "cache_file": str(path),
                "cache_version": version if _integer(version) else None,
                "session_format_version": format_version if _integer(format_version) else None,
                "usage_row_version": row_version if _integer(row_version) else None,
                "usage_checkpoint_seq": row.get("seq") if _integer(row.get("seq"), -1) else None,
                "cache_mtime_ns": metadata.st_mtime_ns,
            },
        })
    return sessions, warnings


def find_sessions_for_cwd(cwd: Path, dsh_home: Path) -> list[dict[str, Any]]:
    """Return every exact-cwd cache match; never choose the newest session.

    Intended for a runner's before/after session-ID comparison. This function
    does not prove source/candidate association or that a session can resume.
    """
    sessions, _ = _scan({str(Path(cwd).resolve())}, Path(dsh_home).resolve())
    return sessions


def inspect_harness_sessions(run_root: Path, dsh_home: Path) -> dict[str, Any]:
    """Inspect a run cwd and immediate real stage directories, without writes.

    Stage selection never reads ``process.json``: historical files can omit
    session IDs or cwd. Their containing directory is the matching authority.
    Recursive source/work directories and directory symlinks are excluded.
    """
    run_root = Path(run_root).resolve()
    if not run_root.is_dir():
        raise ValueError("run_root must be an existing directory")
    home = Path(dsh_home).resolve()
    stages = {str(run_root): "."}
    for child in run_root.iterdir():
        if _plain_directory(run_root, child.name) is not None:
            stages[str(child)] = child.name
    sessions, warnings = _scan(set(stages), home)
    for session in sessions:
        session["stage"] = stages[session["cwd"]]
    # Filename-keyed cache layout gives unique IDs; keep dedup explicit so
    # future discovery sources cannot double-count the same session.
    sessions = list({s["session_id"]: s for s in sessions}.values())
    eligible = [
        s for s in sessions
        if s["usage"] is not None and s["is_seeded"] is False
        and s["inherited_event_count"] == 0 and s["persisted_session_present"]
    ]
    eligible_ids = {s["session_id"] for s in eligible}
    known_totals = (
        {key: sum(s["usage"][key] for s in eligible) for key in USAGE_BUCKETS}
        if eligible else None
    )
    return {
        "schema_version": 1,
        "run_root": str(run_root),
        "dsh_home": str(home),
        "sessions": sessions,
        "unmatched_cwds": sorted(set(stages) - {s["cwd"] for s in sessions}),
        "warnings": warnings,
        "usage_summary": {
            "source": "harness_provider_reported_projection_cache",
            "eligible_session_count": len(eligible),
            "excluded_session_ids": [s["session_id"] for s in sessions if s["session_id"] not in eligible_ids],
            "known_totals": known_totals,
            "complete": False,
            "billing_cost": None,
            "provider_call_count": None,
            "limitations": [
                "Cache checkpoints may be stale; session logs were not opened.",
                "Cache identity was matched by exact cwd; log lifecycle was not verified.",
                "Seeded, missing-identity, orphan and unknown-usage sessions are excluded from totals.",
                "Auxiliary model calls, retries without usage and other providers may be absent.",
                "Cache-read tokens have a separate price; token totals are not a monetary bill.",
            ],
        },
    }
