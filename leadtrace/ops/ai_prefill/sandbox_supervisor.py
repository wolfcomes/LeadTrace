"""Keep session-escaping model tools beneath a subreaper until they are reaped.

Runs outside Landlock with the launcher's sanitized environment, but never runs
model instructions. Scientific child gets Landlock before executing its adapter.
"""
from __future__ import annotations
import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import time


def _identities():
    from leadtrace.ops.ai_prefill.tasks import _process_identity
    result={}
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():continue
        identity=_process_identity(int(path.name))
        if not identity:continue
        try:
            fields=(path/'stat').read_text().rsplit(')',1)[1].split()
            result[identity['pid']] = (int(fields[1]),fields[0],identity)
        except (OSError,ValueError,IndexError):continue
    return result


def descendants(root_pid:int):
    """Includes children adopted by this subreaper after intermediate exit."""
    rows=_identities();members={root_pid};changed=True
    while changed:
        changed=False
        for pid,(parent,_,_) in rows.items():
            if parent in members and pid not in members:
                members.add(pid);changed=True
    return [(state,identity) for pid,(_,state,identity) in rows.items() if pid!=root_pid and pid in members]


def supervise(command:list[str], *, env:dict[str,str]|None=None, receipt_path:Path|None=None, job_directory:str|None=None) -> int:
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(36,1,0,0,0)!=0:  # PR_SET_CHILD_SUBREAPER
        raise OSError(ctypes.get_errno(),'Cannot enable model process supervision')
    stopping=False
    def stop(signum,frame):
        nonlocal stopping
        stopping=True
    previous={sig:signal.signal(sig,stop) for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP)}
    process=None
    try:
        # Install handlers before imports; a cancellation during startup must
        # not terminate the supervisor before it can attest an empty process tree.
        from leadtrace.ops.ai_prefill.tasks import _signal_identity
        process=subprocess.Popen(['/bin/true'] if stopping else command,env=env)
        while not stopping and process.poll() is None:
            time.sleep(.1)
        result=process.poll()
        started=time.monotonic()
        sent={}
        # Do not finish, even on slow cleanup, while a verified descendant lives.
        # The outer runner retains capacity if this supervisor cannot terminate.
        while True:
            process.poll()
            rows=descendants(os.getpid())
            if not rows:break
            sig=signal.SIGKILL if time.monotonic()-started>=.35 else signal.SIGTERM
            for state,identity in rows:
                pid=identity['pid']
                if state in {'Z','X'}:
                    if pid!=process.pid:
                        try:os.waitpid(pid,os.WNOHANG)
                        except ChildProcessError:pass
                    continue
                key=(pid,identity['start_ticks'])
                if sent.get(key)!=sig:
                    try:_signal_identity(identity,sig)
                    except ProcessLookupError:pass
                    sent[key]=sig
            time.sleep(.02)
        process.wait()
        if receipt_path is not None:
            from leadtrace.ops.ai_prefill.tasks import _process_identity
            receipt={'job_directory':job_directory,'supervisor':_process_identity(os.getpid()),'all_descendants_reaped':True}
            fd=os.open(receipt_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as stream:
                json.dump(receipt,stream);stream.flush();os.fsync(stream.fileno())
        return 128+signal.SIGTERM if stopping else (result if result is not None else process.returncode)
    finally:
        for sig,handler in previous.items():signal.signal(sig,handler)
