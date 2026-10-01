"""Offline tests: metadata inspection must never open a Harness transcript."""

import copy
import json
from pathlib import Path

import pytest

from leadtrace.ops.ai_prefill.harness_sessions import (
    find_sessions_for_cwd,
    inspect_harness_sessions,
)


USAGE = {
    "uncachedInputTokens": 100,
    "outputTokens": 20,
    "cacheReadTokens": 900,
    "cacheWriteTokens": 0,
}


def fixture_cache(tmp_path, cwd, session_id="session-one", **changes):
    home = tmp_path / "dsh"
    cache = home / "storages/session_projcache/sessions"
    cache.mkdir(parents=True, exist_ok=True)
    row = {
        "version": 7,
        "record": {
            "identity": {
                "formatVersion": 3,
                "createdAt": 1790075490354,
                "cwd": str(cwd.resolve()),
                "isSeeded": False,
                "inheritedEventCount": 0,
            },
            "rows": {
                "tokenUsage": {"ver": 2, "seq": 369, "val": {"totals": copy.deepcopy(USAGE)}},
                "titleInput": {"val": "DO_NOT_EXPORT_SOURCE_CONTENT"},
                "inbox": {"val": {"secret": "DO_NOT_EXPORT_CREDENTIAL"}},
            },
        },
    }
    row.update(changes)
    path = cache / (session_id + ".json")
    path.write_text(json.dumps(row))
    store = home / "sessions/cwd-encoded" / session_id
    store.mkdir(parents=True, exist_ok=True)
    (store / "session.v3.jsonl.zstd").write_text("DO_NOT_READ_TRANSCRIPT")
    return home, path, row


def test_exact_cwd_multiple_sessions_and_allowlisted_usage(tmp_path):
    run = tmp_path / "run"
    stage = run / "extract"
    stage.mkdir(parents=True)
    home, _, _ = fixture_cache(tmp_path, stage)
    fixture_cache(tmp_path, stage, "session-two")
    fixture_cache(tmp_path, tmp_path / "run-extract", "session-collision")

    result = inspect_harness_sessions(run, home)
    assert [s["session_id"] for s in result["sessions"]] == ["session-one", "session-two"]
    assert all(s["stage"] == "extract" for s in result["sessions"])
    assert result["usage_summary"]["known_totals"] == {k: 2 * v for k, v in USAGE.items()}
    assert result["usage_summary"]["complete"] is False
    assert result["usage_summary"]["billing_cost"] is None
    assert "DO_NOT_EXPORT" not in json.dumps(result)
    assert "DO_NOT_READ" not in json.dumps(result)
    assert len(find_sessions_for_cwd(stage, home)) == 2


def test_root_cwd_and_legacy_process_metadata_without_logs(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    (run / "process.json").write_text(json.dumps({"pid": 123, "exit_code": 0, "command": ["secret"]}))
    home, _, _ = fixture_cache(tmp_path, run)
    original_open = __import__("os").open

    def guarded_open(path, *args, **kwargs):
        assert "jsonl" not in str(path) and not str(path).endswith(".log")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr("os.open", guarded_open)
    result = inspect_harness_sessions(run, home)
    assert result["sessions"][0]["stage"] == "."
    assert result["sessions"][0]["usage"] == USAGE
    assert "secret" not in json.dumps(result)


def test_only_direct_stage_dirs_are_matched(tmp_path):
    run = tmp_path / "run"
    deep = run / "extract/work"
    deep.mkdir(parents=True)
    home, _, _ = fixture_cache(tmp_path, deep)
    assert inspect_harness_sessions(run, home)["sessions"] == []


@pytest.mark.parametrize("change", ["missing", "negative", "boolean", "missing_bucket", "version", "row_version"])
def test_unknown_or_invalid_usage_is_never_zero(tmp_path, change):
    run = tmp_path / "run"
    run.mkdir()
    home, path, data = fixture_cache(tmp_path, run)
    usage = data["record"]["rows"]["tokenUsage"]
    if change == "missing":
        del data["record"]["rows"]["tokenUsage"]
    elif change == "negative":
        usage["val"]["totals"]["outputTokens"] = -1
    elif change == "boolean":
        usage["val"]["totals"]["outputTokens"] = True
    elif change == "missing_bucket":
        del usage["val"]["totals"]["cacheReadTokens"]
    elif change == "version":
        data["version"] = 99
    elif change == "row_version":
        usage["ver"] = 99
    path.write_text(json.dumps(data))
    result = inspect_harness_sessions(run, home)
    assert result["sessions"][0]["usage"] is None
    assert result["usage_summary"]["known_totals"] is None
    assert result["usage_summary"]["excluded_session_ids"] == ["session-one"]


def test_seeded_session_usage_not_added_to_parent_again(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    home, _, _ = fixture_cache(tmp_path, run, "session-parent")
    _, path, data = fixture_cache(tmp_path, run, "session-child")
    data["record"]["identity"].update(isSeeded=True, inheritedEventCount=45)
    path.write_text(json.dumps(data))
    result = inspect_harness_sessions(run, home)
    assert result["usage_summary"]["known_totals"] == USAGE
    assert result["usage_summary"]["excluded_session_ids"] == ["session-child"]
    assert result["sessions"][0]["usage"] == USAGE


def test_missing_seed_identity_not_assumed_unseeded(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    home, path, data = fixture_cache(tmp_path, run)
    del data["record"]["identity"]["isSeeded"]
    path.write_text(json.dumps(data))
    result = inspect_harness_sessions(run, home)
    assert result["usage_summary"]["known_totals"] is None


def test_missing_cache_is_unknown_and_malformed_file_does_not_leak(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    home = tmp_path / "empty-home"
    result = inspect_harness_sessions(run, home)
    assert result["sessions"] == []
    assert result["usage_summary"]["known_totals"] is None
    assert str(run) in result["unmatched_cwds"]
    home, path, _ = fixture_cache(tmp_path, run)
    path.write_text('{"sensitive":"DO_NOT_EXPORT_INVALID_JSON"')
    result = inspect_harness_sessions(run, home)
    assert result["sessions"] == []
    assert "DO_NOT_EXPORT" not in json.dumps(result)
    assert result["warnings"]


def test_symlink_cache_and_stage_escape_are_not_followed(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    home, path, _ = fixture_cache(tmp_path, outside)
    (run / "stage-link").symlink_to(outside, target_is_directory=True)
    assert inspect_harness_sessions(run, home)["sessions"] == []
    _, real_path, _ = fixture_cache(tmp_path, run, "session-real")
    (path.parent / "session-link.json").symlink_to(real_path)
    result = inspect_harness_sessions(run, home)
    assert [s["session_id"] for s in result["sessions"]] == ["session-real"]


def test_cache_parent_symlink_not_followed(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    original_home, _, _ = fixture_cache(tmp_path, run)
    linked_home = tmp_path / "linked-home"
    linked_home.mkdir()
    (linked_home / "storages").symlink_to(original_home / "storages", target_is_directory=True)
    assert find_sessions_for_cwd(run, linked_home) == []


def test_orphan_cache_retained_but_excluded_from_verified_usage(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    home, _, _ = fixture_cache(tmp_path, run)
    import shutil
    shutil.rmtree(home / "sessions")
    result = inspect_harness_sessions(run, home)
    assert result["sessions"][0]["persisted_session_present"] is False
    assert result["usage_summary"]["known_totals"] is None


def test_inspection_does_not_modify_any_input(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    home, path, _ = fixture_cache(tmp_path, run)
    original = path.read_bytes()
    mtime = path.stat().st_mtime_ns
    inspect_harness_sessions(run, home)
    assert path.read_bytes() == original
    assert path.stat().st_mtime_ns == mtime
