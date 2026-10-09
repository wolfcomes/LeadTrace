"""Fail-closed filesystem confinement for unattended Admin model jobs.

Landlock is applied in a separate exec launcher, never preexec_fn in a threaded
server. Provider-only homes are temporary and live outside archived job trees.
"""
from __future__ import annotations
import ctypes
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import tempfile
import tomllib

READ = (1 << 0) | (1 << 2) | (1 << 3)
ALL_FS = (1 << 15) - 1
REPOSITORY = Path(__file__).resolve().parents[3]


def landlock_abi() -> int:
    if sys.platform != 'linux' or platform.machine() not in {'x86_64', 'aarch64'}:
        raise RuntimeError('Admin AI isolation requires Linux Landlock ABI 3 or newer')
    libc = ctypes.CDLL(None, use_errno=True)
    abi = libc.syscall(444, 0, 0, 1)
    if abi < 3:
        raise RuntimeError('Admin AI isolation requires Linux Landlock ABI 3 or newer')
    return abi


def restrict_filesystem(read_paths: list[str], write_paths: list[str]) -> None:
    landlock_abi()
    libc = ctypes.CDLL(None, use_errno=True)
    class Ruleset(ctypes.Structure):
        _fields_ = [('handled_access_fs', ctypes.c_uint64)]
    class Rule(ctypes.Structure):
        _pack_ = 1
        _fields_ = [('allowed_access', ctypes.c_uint64), ('parent_fd', ctypes.c_int32)]
    attr = Ruleset(ALL_FS)
    fd = libc.syscall(444, ctypes.byref(attr), ctypes.sizeof(attr), 0)
    if fd < 0:
        raise OSError(ctypes.get_errno(), 'Cannot create Landlock ruleset')
    try:
        for paths, access in ((read_paths, READ), (write_paths, ALL_FS)):
            for value in paths:
                path = Path(value).resolve(strict=True)
                allowed = access if path.is_dir() else access & ((1 << 0) | (1 << 1) | (1 << 2) | (1 << 14))
                item = os.open(path, getattr(os, "O_PATH", 0o10000000) | os.O_CLOEXEC)
                try:
                    rule = Rule(allowed, item)
                    if libc.syscall(445, fd, 1, ctypes.byref(rule), 0) < 0:
                        raise OSError(ctypes.get_errno(), 'Cannot install Landlock path rule')
                finally:
                    os.close(item)
        if libc.prctl(38, 1, 0, 0, 0) != 0 or libc.syscall(446, fd, 0) != 0:
            raise OSError(ctypes.get_errno(), 'Cannot restrict model filesystem')
    finally:
        os.close(fd)


def _toml(value):
    if isinstance(value, bool): return 'true' if value else 'false'
    if isinstance(value, str): return json.dumps(value)
    if isinstance(value, (float, int)): return str(value)
    if isinstance(value, list): return '[' + ','.join(_toml(v) for v in value) + ']'
    if isinstance(value, dict): return '{' + ','.join(json.dumps(k)+'='+_toml(v) for k,v in value.items()) + '}'
    raise ValueError('Unsupported provider configuration')


def _copy_private(source: Path, target: Path) -> None:
    if source.is_file():
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with target.open('x') as stream:
            stream.write(source.read_text())
        target.chmod(0o600)


def sandbox_command(command: list[str], env: dict[str,str], *, job_directory: Path | str,
                    python_executable: Path | str, adapter: str) -> tuple[list[str],dict[str,str]]:
    landlock_abi()  # fail before copying credentials or launching an adapter
    job = Path(job_directory).resolve(strict=True)
    python = Path(python_executable).absolute()
    private = Path(tempfile.mkdtemp(prefix='leadtrace-model-home-'))
    try:
        home = private/'home'; home.mkdir(mode=0o700)
        tmp = private/'tmp'; tmp.mkdir(mode=0o700)
        imports = private/'imports'
        (imports/'leadtrace/ops').mkdir(parents=True,mode=0o700)
        (imports/'leadtrace/ops/ai_prefill').symlink_to(REPOSITORY/'leadtrace/ops/ai_prefill',target_is_directory=True)
        (imports/'app').symlink_to(REPOSITORY/'leadtrace/backend/app',target_is_directory=True)
        # Only explicit runtime/provider variables survive; no application/DB env.
        keys = {'PATH','LANG','LC_ALL','TZ','SSL_CERT_FILE','SSL_CERT_DIR','NODE_EXTRA_CA_CERTS',
                'OPENAI_API_KEY','DEEPSEEK_API_KEY','OPENAI_BASE_URL','DEEPSEEK_BASE_URL'}
        clean = {k:v for k,v in env.items() if k in keys}
        clean.update(HOME=str(home),TMPDIR=str(tmp),TMP=str(tmp),TEMP=str(tmp),
                     XDG_CACHE_HOME=str(home/'.cache'),XDG_CONFIG_HOME=str(home/'.config'),
                     XDG_DATA_HOME=str(home/'.local/share'),PYTHONDONTWRITEBYTECODE='1',
                     PYTHONPATH=str(imports),
                     LEADTRACE_SCIENTIFIC_PYTHON=str(python),LEADTRACE_SANDBOX_HOME=str(private))
        original_home = Path(env.get('HOME', str(Path.home())))
        if adapter == 'dsh':
            original = Path(env.get('DSH_HOME', str(original_home/'.dsh')))
            isolated = home/'.dsh';isolated.mkdir(mode=0o700)
            _copy_private(original/'.credentials.yaml', isolated/'.credentials.yaml')
            clean['DSH_HOME'] = str(isolated)
            clean['DSH_TELEMETRY_DISABLED'] = '1'
            clean['NODE_OPTIONS'] = '--require='+str(Path(__file__).with_name('request_observer.cjs'))
        elif adapter == 'codex':
            original = Path(env.get('CODEX_HOME', str(original_home/'.codex')))
            isolated = home/'.codex';isolated.mkdir(mode=0o700)
            _copy_private(original/'auth.json', isolated/'auth.json')
            config = tomllib.loads((original/'config.toml').read_text()) if (original/'config.toml').is_file() else {}
            safe = {k:config[k] for k in ('model','model_provider','model_reasoning_effort','preferred_auth_method','forced_login_method') if k in config}
            provider = config.get('model_provider')
            if provider and provider in config.get('model_providers', {}):
                allowed = {'name','base_url','env_key','wire_api','requires_openai_auth','request_max_retries','stream_max_retries','stream_idle_timeout_ms','http_headers','env_http_headers'}
                values = {k:v for k,v in config['model_providers'][provider].items() if k in allowed}
                safe['model_providers'] = {provider:values}
                for key in [values.get('env_key'), *values.get('env_http_headers', {}).values()]:
                    if isinstance(key,str) and key in env: clean[key] = env[key]
            (isolated/'config.toml').write_text('\n'.join(json.dumps(k)+'='+_toml(v) for k,v in safe.items())+'\n')
            (isolated/'config.toml').chmod(0o600)
            clean['CODEX_HOME'] = str(isolated)
        else: raise ValueError('Unsupported sandbox adapter')
        read = [Path(p) for p in ('/usr','/bin','/sbin','/lib','/lib64','/etc/ssl','/etc/fonts','/etc/ld.so.cache','/etc/resolv.conf','/etc/nsswitch.conf','/etc/hosts','/etc/localtime','/etc/passwd','/dev/urandom','/dev/random','/proc/cpuinfo','/proc/meminfo')]
        read += [REPOSITORY/'leadtrace/ops/ai_prefill', REPOSITORY/'leadtrace/backend/app', python.parent.parent, python.resolve().parent.parent]
        # Node distributions and the selected installed CLI package are runtime code.
        executable = Path(shutil.which(command[0], path=env.get('PATH')) or command[0]).resolve(strict=True)
        for path in [executable,Path(shutil.which('node',path=env.get('PATH')) or '/usr/bin/node').resolve()]:
            ancestors=list(path.parents)
            module=next((p for p in ancestors if p.parent.name=='node_modules' or p.parent.name.startswith('@') and p.parent.parent.name=='node_modules'),None)
            read.append(module or path.parent.parent)
        for key in ('SSL_CERT_FILE','SSL_CERT_DIR','NODE_EXTRA_CA_CERTS'):
            if clean.get(key):read.append(Path(clean[key]))
        guard=private/'isolation-guard'
        guard.write_text('Synthetic isolation guard; contains no credential.');guard.chmod(0o600)
        read.append(imports)
        if adapter=='codex' and len(command)>1 and command[1]=='exec':
            command=[str(python),'-m','leadtrace.ops.ai_prefill.codex_bridge',
                     '--executable',str(executable),'--directory',str(job)]
        spec = {'read': sorted({str(p.resolve()) for p in read if p.exists()}),
                'write': [str(job),str(home),str(tmp),'/dev/null'], 'guard':str(guard), 'command':command, 'job_directory':str(job)}
        spec_path=private/'sandbox.json';spec_path.write_text(json.dumps(spec));spec_path.chmod(0o600)
        return [str(python),'-m','leadtrace.ops.ai_prefill.sandbox',str(spec_path)],clean
    except Exception:
        shutil.rmtree(private)
        raise


def require_sandbox_cleanup(env: dict[str,str], *, expected_job_directory: Path | str, supervisor_identity: dict | None = None) -> None:
    """Require a supervisor-written receipt inaccessible to the scientific child."""
    value=env.get('LEADTRACE_SANDBOX_HOME')
    if not value:raise ValueError('Missing sandbox identity; cleanup remains unconfirmed')
    root=Path(value)
    if root.parent!=Path(tempfile.gettempdir()) or not root.name.startswith('leadtrace-model-home-'):
        raise ValueError('Invalid sandbox identity')
    if supervisor_identity and supervisor_identity.get('boot_id') != Path('/proc/sys/kernel/random/boot_id').read_text().strip():
        return  # All processes from the recorded earlier boot are gone.
    receipt=root.with_name(root.name+'.cleanup.json')
    try:
        import stat
        info=receipt.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o600:
            raise ValueError('Invalid sandbox cleanup receipt')
        result=json.loads(receipt.read_text())
        if supervisor_identity is not None and result.get('supervisor')!=supervisor_identity:
            raise ValueError('Sandbox supervisor identity does not match receipt')
        if result.get('job_directory')!=str(Path(expected_job_directory).resolve()) or result.get('all_descendants_reaped') is not True:
            raise ValueError('Sandbox cleanup receipt does not match the task')
    except (OSError,ValueError) as error:
        raise ValueError('Sandbox supervisor did not confirm all descendants stopped; capacity must be retained') from error


def cleanup_sandbox(env: dict[str,str], *, expected_job_directory: Path | str | None = None) -> None:
    value=env.get('LEADTRACE_SANDBOX_HOME')
    if value:
        root=Path(value)
        if root.parent==Path(tempfile.gettempdir()) and root.name.startswith('leadtrace-model-home-') and not root.is_symlink():
            if expected_job_directory is not None:
                try:
                    spec=json.loads((root/'sandbox.json').read_text())
                    if spec.get('job_directory') != str(Path(expected_job_directory).resolve()):return
                except (OSError,ValueError):return
            shutil.rmtree(root,ignore_errors=True)


def main() -> None:
    if len(sys.argv) == 2:
        from leadtrace.ops.ai_prefill.sandbox_supervisor import supervise
        spec_path=Path(sys.argv[1]);spec=json.loads(spec_path.read_text())
        receipt=spec_path.parent.with_name(spec_path.parent.name+'.cleanup.json')
        raise SystemExit(supervise([sys.executable,'-m','leadtrace.ops.ai_prefill.sandbox','--child',sys.argv[1]],receipt_path=receipt,job_directory=spec['job_directory']))
    if len(sys.argv) != 3 or sys.argv[1] != '--child':
        raise RuntimeError('Invalid isolated launcher arguments')
    spec=json.loads(Path(sys.argv[2]).read_text())
    restrict_filesystem(spec['read'],spec['write'])
    os.environ['LEADTRACE_LANDLOCK_GUARD']=spec['guard']
    os.execvpe(spec['command'][0],spec['command'],os.environ)


if __name__=='__main__': main()
