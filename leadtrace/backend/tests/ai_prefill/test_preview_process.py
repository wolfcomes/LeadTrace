"""Native Preview lifecycle rejects unsafe profiles and foreign processes."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from uuid import uuid4

import pytest


@pytest.fixture
def profile(tmp_path):
    from app.config import Settings
    instance = uuid4()
    for name in ("assets", "sources", "artifacts"):
        (tmp_path / name).mkdir()
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({
        "schema_version": 1, "state": "ready", "instance_id": str(instance),
        "database_name": "test_preview", "database_host": "127.0.0.1", "database_port": 5432,
        "schema_revision": "test-head", "baseline_sha256": "a" * 64,
        "asset_root": str(tmp_path / "assets"), "source_root": str(tmp_path / "sources"),
        "artifact_root": str(tmp_path / "artifacts"), "commit": "test-commit",
        "lockfile_sha256": "b" * 64, "origin": "http://127.0.0.1:18080",
    }))
    settings = Settings(_env_file=None, environment="preview", database_url="postgresql+psycopg://runtime:private-password@127.0.0.1/test_preview",
        asset_root=tmp_path / "assets", source_roots={"source_pdfs": tmp_path / "sources"},
        preview_artifact_root=tmp_path / "artifacts", preview_registry_path=registry,
        preview_instance_id=instance, preview_baseline_sha256="a" * 64,
        session_secret="private-session-secret")
    value = settings.model_dump(mode="json")
    value["session_secret"] = settings.session_secret.get_secret_value()
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    return path


def test_profile_ignores_environment(profile, monkeypatch):
    from app.ai_prefill.preview_process import load_runtime_settings
    monkeypatch.setenv("LEADTRACE_ENVIRONMENT", "production")
    monkeypatch.setenv("LEADTRACE_DEFAULT_ACCOUNT_PASSWORD", "inherited-secret")
    value = json.loads(profile.read_text())
    del value["default_account_password"]
    profile.write_text(json.dumps(value))
    settings = load_runtime_settings(profile)
    assert settings.environment == "preview"
    assert settings.default_account_password is None
    assert settings.session_secret.get_secret_value() == "private-session-secret"


@pytest.mark.parametrize("problem", ["permissions", "symlink", "directory", "oversized", "bad_json", "non_preview"])
def test_profile_rejects_unsafe_inputs(profile, problem):
    from app.ai_prefill.preview_process import PreviewProcessError, load_runtime_settings
    target = profile
    if problem == "permissions":
        profile.chmod(0o644)
    elif problem == "symlink":
        target = profile.parent / "linked.json"
        target.symlink_to(profile)
    elif problem == "directory":
        target = profile.parent
    elif problem == "oversized":
        profile.write_bytes(b"x" * 65537)
    elif problem == "bad_json":
        profile.write_text('{"session_secret":"private-session-secret",')
    else:
        value = json.loads(profile.read_text())
        value["environment"] = "test"
        profile.write_text(json.dumps(value))
    with pytest.raises(PreviewProcessError) as caught:
        load_runtime_settings(target)
    assert "private" not in str(caught.value)


def test_status_and_stop_without_process_are_idempotent(profile):
    from app.ai_prefill.preview_process import status_preview, stop_preview
    assert status_preview(profile)["status"] == "stopped"
    assert stop_preview(profile)["status"] == "stopped"
    assert "private" not in json.dumps(status_preview(profile))


@pytest.mark.parametrize("origin", ["http://0.0.0.0:18080", "https://127.0.0.1:18080", "http://example.org:18080", "http://127.0.0.1:18080/path", "http://user:secret@127.0.0.1:18080"])
def test_start_rejects_nonlocal_or_non_http_origin(profile, origin):
    from app.ai_prefill.preview_process import PreviewProcessError, start_preview
    registry = profile.parent / "registry.json"
    value = json.loads(registry.read_text())
    value["origin"] = origin
    registry.write_text(json.dumps(value))
    with pytest.raises(PreviewProcessError, match="origin"):
        start_preview(profile)


def test_start_does_not_disturb_occupied_port(profile):
    from app.ai_prefill.preview_process import PreviewProcessError, start_preview
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        registry = profile.parent / "registry.json"
        value = json.loads(registry.read_text())
        value["origin"] = f"http://127.0.0.1:{listener.getsockname()[1]}"
        registry.write_text(json.dumps(value))
        with pytest.raises(PreviewProcessError, match="port"):
            start_preview(profile)
        assert listener.getsockname()[1] > 0


def test_stop_refuses_foreign_process_even_with_matching_starttime(profile):
    from app.ai_prefill.preview_process import PreviewProcessError, stop_preview, _process_starttime
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        (profile.parent / "process.json").write_text(json.dumps({
            "pid": child.pid, "starttime": _process_starttime(child.pid), "profile": str(profile),
        }))
        with pytest.raises(PreviewProcessError, match="ownership"):
            stop_preview(profile)
        assert child.poll() is None
    finally:
        child.terminate()
        child.wait(timeout=5)


def test_status_reports_stale_record_without_signaling(profile):
    from app.ai_prefill.preview_process import status_preview, stop_preview
    (profile.parent / "process.json").write_text(json.dumps({"pid": 2147483647, "starttime": "0", "profile": str(profile)}))
    assert status_preview(profile)["status"] == "stopped"
    assert stop_preview(profile)["status"] == "stopped"


def test_database_failure_is_redacted_and_releases_listener(profile, monkeypatch):
    from app.ai_prefill.preview_process import PreviewProcessError, start_preview
    import app.database
    monkeypatch.setattr(app.database, "bootstrap_database", lambda settings: (_ for _ in ()).throw(RuntimeError(settings.database_url)))
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    registry = profile.parent / "registry.json"
    value = json.loads(registry.read_text())
    value["origin"] = f"http://127.0.0.1:{port}"
    registry.write_text(json.dumps(value))
    with pytest.raises(PreviewProcessError) as caught:
        start_preview(profile)
    assert "private-password" not in str(caught.value)
    assert not (profile.parent / "process.json").exists()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))


@pytest.mark.parametrize("loopback_host", ["127.0.0.1", "127.23.45.67"])
def test_real_backend_start_status_stop(preview_settings, loopback_host):
    from http.client import HTTPConnection
    from app.ai_prefill.preview_process import start_preview, status_preview, stop_preview
    from urllib.request import ProxyHandler, build_opener
    settings = preview_settings.model_copy(update={"allowed_hosts": [loopback_host]})
    registry = settings.preview_registry_path
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        origin = f"http://{loopback_host}:{probe.getsockname()[1]}"
    value = json.loads(registry.read_text())
    value["origin"] = origin
    registry.write_text(json.dumps(value))
    profile = registry.parent / "runtime.json"
    value = settings.model_dump(mode="json")
    value["session_secret"] = settings.session_secret.get_secret_value()
    profile.write_text(json.dumps(value))
    profile.chmod(0o600)
    try:
        result = start_preview(profile)
        assert result["status"] == "running"
        assert start_preview(profile) == result
        assert status_preview(profile) == result
        # The same virtualenv can be invoked through a normalized path from a
        # different directory; ownership should survive that spelling change.
        interpreter = str(Path(os.path.abspath(sys.executable)))
        status_script = "import json,sys; from app.ai_prefill.preview_process import status_preview; print(json.dumps(status_preview(sys.argv[1])))"
        external = subprocess.run([interpreter, "-c", status_script, str(profile)], cwd=profile.parent,
            check=True, text=True, capture_output=True)
        assert json.loads(external.stdout) == result
        with build_opener(ProxyHandler({})).open(origin + "/health/ready", timeout=5) as response:
            assert response.status == 200
        with build_opener(ProxyHandler({})).open(origin + "/api/preview/environment", timeout=5) as response:
            environment = json.load(response)
            assert environment["environment"] == "preview"
            assert environment["instance_id"] == str(settings.preview_instance_id)
        if environment["frontend_available"]:
            with build_opener(ProxyHandler({})).open(origin + "/login", timeout=5) as response:
                assert b'<div id="app">' in response.read()
        # Keep a client connected so stopping makes the server close first,
        # leaving its accepted connection in TIME_WAIT before immediate restart.
        persistent = HTTPConnection(loopback_host, int(origin.rsplit(":", 1)[1]), timeout=5)
        persistent.request("GET", "/health/ready")
        persistent.getresponse().read()
        try:
            assert stop_preview(profile)["status"] == "stopped"
            assert persistent.sock.recv(1) == b""
        finally:
            persistent.close()
        assert status_preview(profile)["status"] == "stopped"
        assert stop_preview(profile)["status"] == "stopped"
        restarted = start_preview(profile)
        assert restarted["status"] == "running"
        assert restarted["pid"] != result["pid"]
    finally:
        stop_preview(profile)


def test_start_refuses_when_safe_stop_is_unavailable(profile, monkeypatch):
    import app.ai_prefill.preview_process as process
    def unavailable(pid):
        raise OSError(38, "Function not implemented")
    monkeypatch.setattr(process, "_pidfd_open", unavailable)
    monkeypatch.setattr(process, "_verify_database", lambda settings: None)
    with pytest.raises(process.PreviewProcessError, match="pidfd"):
        process.start_preview(profile)
    assert not (profile.parent / "process.json").exists()


@pytest.mark.parametrize("failure", ["starttime_none", "starttime_error", "pidfd_open_error"])
def test_startup_metadata_failure_reaps_its_live_child(preview_settings, monkeypatch, failure):
    import app.ai_prefill.preview_process as process
    settings = preview_settings.model_copy(update={"allowed_hosts": ["127.0.0.1"]})
    registry = settings.preview_registry_path
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    value = json.loads(registry.read_text())
    value["origin"] = f"http://127.0.0.1:{port}"
    registry.write_text(json.dumps(value))
    profile = registry.parent / "runtime.json"
    value = settings.model_dump(mode="json")
    value["session_secret"] = settings.session_secret.get_secret_value()
    profile.write_text(json.dumps(value))
    profile.chmod(0o600)
    children = []
    real_popen = subprocess.Popen
    real_starttime = process._process_starttime
    real_pidfd_open = process._pidfd_open
    injected = False

    def capture_child(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        children.append(child)
        return child

    def starttime(pid):
        nonlocal injected
        if children and pid == children[0].pid and not injected and failure.startswith("starttime"):
            assert children[0].poll() is None
            injected = True
            if failure == "starttime_error":
                raise RuntimeError("injected process metadata failure")
            return None
        return real_starttime(pid)

    def pidfd_open(pid):
        if children and pid == children[0].pid and failure == "pidfd_open_error":
            raise OSError(24, "injected descriptor exhaustion")
        return real_pidfd_open(pid)

    monkeypatch.setattr(process.subprocess, "Popen", capture_child)
    monkeypatch.setattr(process, "_process_starttime", starttime)
    monkeypatch.setattr(process, "_pidfd_open", pidfd_open)
    try:
        with pytest.raises((process.PreviewProcessError, RuntimeError, OSError)):
            process.start_preview(profile)
        assert len(children) == 1
        assert children[0].poll() is not None
        assert not (profile.parent / "process.json").exists()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)


def test_start_rejects_localhost_with_ambiguous_address_family(profile):
    from app.ai_prefill.preview_process import PreviewProcessError, start_preview
    registry = profile.parent / "registry.json"
    value = json.loads(registry.read_text())
    value["origin"] = "http://localhost:18080"
    registry.write_text(json.dumps(value))
    with pytest.raises(PreviewProcessError, match="origin"):
        start_preview(profile)


def test_origin_binds_exact_canonical_loopback_address(profile):
    from app.ai_prefill.preview_process import _origin, load_runtime_settings
    registry = profile.parent / "registry.json"
    value = json.loads(registry.read_text())
    value["origin"] = "http://127.23.45.67:18080"
    registry.write_text(json.dumps(value))
    assert _origin(load_runtime_settings(profile)) == ("http://127.23.45.67:18080", "127.23.45.67", 18080)


@pytest.mark.parametrize("host", ["localhost", "127.1", "2130706433", "127.000.0.1", "[::1]", "192.168.0.1"])
def test_origin_rejects_noncanonical_or_nonloopback_hosts(profile, host):
    from app.ai_prefill.preview_process import PreviewProcessError, _origin, load_runtime_settings
    registry = profile.parent / "registry.json"
    value = json.loads(registry.read_text())
    value["origin"] = f"http://{host}:18080"
    registry.write_text(json.dumps(value))
    with pytest.raises(PreviewProcessError, match="origin"):
        _origin(load_runtime_settings(profile))
