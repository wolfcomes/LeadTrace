"""Linux native lifecycle for a single loopback Preview backend process.

Process records contain no credentials. A pidfd and /proc birth/command identity
are both required before any signal is sent; a stale record never authorizes it.
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
import fcntl
from ipaddress import IPv4Address
import json
import os
from pathlib import Path
import select
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

from pydantic import ValidationError

from app.ai_prefill.preview_identity import PreviewIdentityError, read_preview_registry, require_preview_settings
from app.config import Settings


class PreviewProcessError(RuntimeError):
    """Safe, nonsecret lifecycle error suitable for CLI output."""


class _ProfileSettings(Settings):
    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
        return (init_settings,)


def _path(path: Path) -> Path:
    path = Path(path).absolute()
    if ".." in path.parts or any(item.is_symlink() for item in (path, *path.parents)):
        raise PreviewProcessError("Preview profile paths must not contain symlinks or traversal")
    return path


def _read_json(path: Path, *, private: bool = False) -> dict:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or (private and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600)):
                raise PreviewProcessError("Preview profile must be an owned mode-0600 regular file")
            data = stream.read(65_537)
        if len(data) > 65_536:
            raise PreviewProcessError("Preview metadata exceeds size limit")
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (OSError, ValueError) as error:
        raise PreviewProcessError("Preview metadata is unavailable or invalid") from None


def load_runtime_settings(profile_path: Path) -> Settings:
    """Load only the protected profile; ignore environment and .env sources."""
    value = _read_json(_path(profile_path), private=True)
    try:
        settings = _ProfileSettings(**value)
        require_preview_settings(settings)
    except (ValidationError, PreviewIdentityError):
        raise PreviewProcessError("Preview runtime profile is invalid") from None
    return settings


def _origin(settings: Settings) -> tuple[str, str, int]:
    try:
        read_preview_registry(settings)
        origin = _read_json(settings.preview_registry_path).get("origin", "")
        value = urlsplit(origin)
        address = IPv4Address(value.hostname)
        if (value.scheme != "http" or not address.is_loopback or value.hostname != str(address)
                or value.username is not None or value.password is not None
                or value.path not in {"", "/"} or value.query or value.fragment
                or value.port is None or not 1 <= value.port <= 65535):
            raise ValueError
        return origin.rstrip("/"), str(address), value.port
    except (ValueError, TypeError, PreviewIdentityError):
        raise PreviewProcessError("Preview requires a ready registry and an explicit loopback HTTP origin") from None


@contextmanager
def _locked(profile: Path):
    try:
        fd = os.open(profile.parent / ".process.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            os.close(fd)
            raise PreviewProcessError("Preview process lock is unsafe")
    except OSError:
        raise PreviewProcessError("Preview process lock is unavailable") from None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _process_starttime(pid: int) -> str | None:
    try:
        value = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return None if value[0] == "Z" else value[19]
    except (OSError, IndexError):
        return None


def _record(profile: Path) -> dict | None:
    path = profile.parent / "process.json"
    if not path.exists() and not path.is_symlink():
        return None
    value = _read_json(path)
    if type(value.get("pid")) is not int or value["pid"] <= 1 or not isinstance(value.get("starttime"), str):
        raise PreviewProcessError("Preview process ownership record is invalid")
    return value


def _owned(record: dict, profile: Path) -> bool:
    if _process_starttime(record["pid"]) != record["starttime"]:
        return False
    try:
        args = Path(f"/proc/{record['pid']}/cmdline").read_bytes().split(b"\0")
        args = [item.decode() for item in args if item]
        expected = ["-m", "app.ai_prefill.preview_server", "--profile", str(profile), "--fd"]
        if (record.get("profile") != str(profile) or len(args) != 7
                or Path(args[0]).resolve() != Path(sys.executable).resolve()
                or args[1:6] != expected or not args[6].isdigit()):
            raise PreviewProcessError("Preview process ownership could not be verified")
    except (OSError, UnicodeError):
        raise PreviewProcessError("Preview process ownership could not be verified") from None
    return True


def _write_record(profile: Path, value: dict) -> None:
    fd, name = tempfile.mkstemp(prefix=".process-", dir=profile.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, profile.parent / "process.json")
    finally:
        Path(name).unlink(missing_ok=True)


def _report(settings: Settings, status: str, record: dict | None = None) -> dict:
    value = {"status": status, "instance_id": str(settings.preview_instance_id)}
    if record is not None:
        value["pid"] = record["pid"]
    return value


def status_preview(profile_path: Path) -> dict:
    profile = _path(profile_path)
    settings = load_runtime_settings(profile)
    with _locked(profile):
        record = _record(profile)
        running = record is not None and _owned(record, profile)
        return _report(settings, "running" if running else "stopped", record if running else None)


def _pidfd_open(pid: int) -> int:
    if hasattr(os, "pidfd_open"):
        return os.pidfd_open(pid)
    # Some supported Python builds omit wrappers despite libc/kernel support.
    library = ctypes.CDLL(None, use_errno=True)
    function = library.pidfd_open
    function.argtypes = [ctypes.c_int, ctypes.c_uint]
    function.restype = ctypes.c_int
    result = function(pid, 0)
    if result < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return result


def _pidfd_send_signal(fd: int, value: int) -> None:
    if hasattr(signal, "pidfd_send_signal"):
        signal.pidfd_send_signal(fd, value)
        return
    library = ctypes.CDLL(None, use_errno=True)
    function = library.pidfd_send_signal
    function.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    if function(fd, value, None, 0) < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def _stop_pidfd(fd: int) -> None:
    """Stop the process pinned by this descriptor, without consulting metadata."""
    try:
        _pidfd_send_signal(fd, signal.SIGTERM)
        poller = select.poll()
        poller.register(fd, select.POLLIN)
        if not poller.poll(10_000):
            _pidfd_send_signal(fd, signal.SIGKILL)
            if not poller.poll(5_000):
                raise PreviewProcessError("Preview process did not stop")
    except ProcessLookupError:
        pass


def _terminate(record: dict, profile: Path) -> None:
    try:
        fd = _pidfd_open(record["pid"])
    except ProcessLookupError:
        return
    except (OSError, AttributeError):
        raise PreviewProcessError("Preview stop requires Linux pidfd support") from None
    try:
        if not _owned(record, profile):
            return
        _stop_pidfd(fd)
        try:
            os.waitpid(record["pid"], os.WNOHANG)
        except ChildProcessError:
            pass
    except ProcessLookupError:
        pass
    finally:
        os.close(fd)


def stop_preview(profile_path: Path) -> dict:
    profile = _path(profile_path)
    settings = load_runtime_settings(profile)
    with _locked(profile):
        record = _record(profile)
        if record is not None and _owned(record, profile):
            _terminate(record, profile)
        (profile.parent / "process.json").unlink(missing_ok=True)
        return _report(settings, "stopped")


def _verify_database(settings: Settings) -> None:
    from app.database import bootstrap_database
    try:
        resources = bootstrap_database(settings)
        if resources is None:
            raise PreviewProcessError("Preview database identity could not be verified")
        resources.close()
    except Exception:
        raise PreviewProcessError("Preview database identity could not be verified") from None


def start_preview(profile_path: Path) -> dict:
    profile = _path(profile_path)
    settings = load_runtime_settings(profile)
    origin, host, port = _origin(settings)
    with _locked(profile):
        record = _record(profile)
        if record is not None and _owned(record, profile):
            return _report(settings, "running", record)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            try:
                # Reclaim this stopped server's TIME_WAIT connections; an
                # actively listening foreign process still makes bind fail.
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind((host, port))
                listener.listen(128)
            except OSError:
                raise PreviewProcessError("Preview origin port is unavailable") from None
            try:
                probe_fd = _pidfd_open(os.getpid())
                try:
                    _pidfd_send_signal(probe_fd, 0)
                finally:
                    os.close(probe_fd)
            except (OSError, AttributeError):
                raise PreviewProcessError("Preview lifecycle requires Linux pidfd support") from None
            _verify_database(settings)
            environment = {key: value for key, value in os.environ.items() if not key.startswith("LEADTRACE_")}
            command = [sys.executable, "-m", "app.ai_prefill.preview_server", "--profile", str(profile), "--fd", str(listener.fileno())]
            child = subprocess.Popen(command, pass_fds=(listener.fileno(),), env=environment,
                cwd=Path(__file__).resolve().parents[2], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            child_fd = None
            try:
                # Pin the child before reading or publishing fallible metadata.
                child_fd = _pidfd_open(child.pid)
                record = {"pid": child.pid, "starttime": _process_starttime(child.pid), "profile": str(profile)}
                if record["starttime"] is None:
                    raise PreviewProcessError("Preview backend exited before startup")
                _write_record(profile, record)
                opener = build_opener(ProxyHandler({}))
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if child.poll() is not None:
                        raise PreviewProcessError("Preview backend exited before becoming ready")
                    try:
                        with opener.open(origin + "/health/ready", timeout=0.5) as response:
                            if response.status == 200:
                                return _report(settings, "running", record)
                    except (URLError, OSError):
                        pass
                    time.sleep(0.1)
                raise PreviewProcessError("Preview backend did not become ready within 30 seconds")
            except BaseException:
                # Startup owns this child independently of process.json or
                # /proc readability. Never use an incomplete record to clean up.
                if child_fd is not None:
                    _stop_pidfd(child_fd)
                elif child.poll() is None:
                    # If acquiring pidfd itself failed, this unreaped direct
                    # Popen child still reserves its PID until wait() below.
                    child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
                (profile.parent / "process.json").unlink(missing_ok=True)
                raise
            finally:
                if child_fd is not None:
                    os.close(child_fd)
