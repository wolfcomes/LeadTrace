"""Codex app-server adapter for the externally enforced Admin filesystem sandbox.

No listener is exposed: JSON-RPC uses private child pipes. The outer launcher
must install Landlock before this adapter will create a model thread/turn.
"""
from collections import deque
from pathlib import Path
import argparse
import json
import os
import stat
import subprocess
import sys

EXTERNAL_POLICY={'type':'externalSandbox','networkAccess':'enabled'}


def require_outer_sandbox():
    marker=os.environ.get('LEADTRACE_LANDLOCK_GUARD')
    if not marker:raise RuntimeError('External filesystem isolation is required')
    path=Path(marker)
    info=path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o600:
        raise RuntimeError('External filesystem isolation guard is invalid')
    try:
        with path.open('rb'):pass
    except PermissionError:return
    raise RuntimeError('External filesystem isolation was not enforced')


class Rpc:
    def __init__(self,process):
        self.process=process;self.sequence=0;self.pending=deque()
    def send(self,value):
        self.process.stdin.write(json.dumps(value)+'\n');self.process.stdin.flush()
    def read(self):
        line=self.process.stdout.readline(16*1024*1024+1)
        if not line or len(line)>16*1024*1024:raise RuntimeError('Codex protocol stream ended or exceeded limit')
        value=json.loads(line)
        if not isinstance(value,dict):raise RuntimeError('Invalid Codex protocol response')
        if 'method' in value and 'id' in value:
            self.send({'id':value['id'],'error':{'code':-32601,'message':'Interactive requests are unavailable in this task'}})
            raise RuntimeError('Codex requested unsupported interactive input')
        if 'method' in value:
            # Native event log may include paper content; never exposed by Admin API.
            print(json.dumps(value),flush=True)
        return value
    def call(self,method,params):
        self.sequence+=1;identifier=self.sequence
        self.send({'id':identifier,'method':method,'params':params})
        while True:
            value=self.read()
            if value.get('id')==identifier:
                if 'error' in value:raise RuntimeError('Codex protocol request failed')
                return value.get('result',{})
            if 'method' in value:self.pending.append(value)
    def notification(self):
        if self.pending:return self.pending.popleft()
        while True:
            value=self.read()
            if 'method' in value:return value


def produce(rpc,directory):
    task=json.loads((directory/'task.json').read_text());runtime=task['runtime']
    response=rpc.call('thread/start',{'model':runtime['model'],'cwd':str(directory),
        'approvalPolicy':'never','sandbox':'workspace-write','ephemeral':True})
    thread=response['thread']['id']
    result=rpc.call('turn/start',{'threadId':thread,'cwd':str(directory),
        'model':runtime['model'],'effort':runtime['reasoning_effort'],'approvalPolicy':'never',
        'sandboxPolicy':EXTERNAL_POLICY,'input':[{'type':'text','text':(directory/'prompt.md').read_text()}]})
    turn=result['turn']['id']
    metadata={'thread_id':thread,'turn_id':turn,'requested_model':runtime['model'],
        'requested_effort':runtime['reasoning_effort'],'execution_sandbox':'landlock-external',
        'server_model':response.get('model'),'server_effort':response.get('reasoningEffort'),'status':'running'}
    def save():
        path=directory/'codex-session.json';path.write_text(json.dumps(metadata,indent=2));path.chmod(0o600)
    save()
    while True:
        event=rpc.notification();params=event.get('params',{})
        if params.get('threadId')!=thread:continue
        if event.get('method')=='thread/tokenUsage/updated':
            usage=params.get('tokenUsage',{})
            # Usage metadata only; does not attest wire-observed model configuration.
            metadata['usage']={k:v for k,v in usage.get('total',{}).items() if isinstance(v,int)}
        if event.get('method')=='turn/completed' and params.get('turn',{}).get('id')==turn:
            metadata['status']=params['turn']['status'];save()
            return 0 if metadata['status']=='completed' else 1


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--executable',required=True);parser.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args();require_outer_sandbox()
    process=subprocess.Popen([args.executable,'app-server'],cwd=args.directory,env=os.environ,
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=sys.stderr,text=True)
    try:
        rpc=Rpc(process);rpc.call('initialize',{'clientInfo':{'name':'leadtrace_scientific_worker','version':'1'}})
        rpc.send({'method':'initialized'})
        return produce(rpc,args.directory)
    finally:
        process.stdin.close()
        try:process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        process.stdout.close()


if __name__=='__main__':
    try:sys.exit(main())
    except Exception:
        print('Codex task protocol failed; preserved outputs remain unapproved.',file=sys.stderr)
        sys.exit(1)
