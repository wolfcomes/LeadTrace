"""Exercise Codex's actual command sandbox before any model turn is started."""
from pathlib import Path
import json
import os
import selectors
import subprocess
import tempfile
import time


class ToolExecutionUnavailable(ValueError):
    code = 'TOOL_EXECUTION_UNAVAILABLE'
    def __init__(self):
        super().__init__('模型工具执行环境不可用：无法在隔离环境中执行命令并保存文件。尚未启动模型生成；请先修复运行环境。')


class ToolExecutionCleanupPending(ValueError):
    """A probe process may still exist; preserve its ownership and queue slot."""
    def __init__(self,process_state):
        super().__init__('模型工具检查的进程清理尚未确认；任务名额保持占用，未启动模型生成。')
        self.process_state=process_state


def codex_execution_preflight(executable, python_executable, environment, *, timeout=20):
    from leadtrace.ops.ai_prefill.sandbox import sandbox_command, cleanup_sandbox, require_sandbox_cleanup
    from leadtrace.ops.ai_prefill.tasks import _process_identity, _terminate_owned_group
    # Entirely synthetic: initialize + command/exec creates no model thread/turn.
    with tempfile.TemporaryDirectory(prefix='leadtrace-tool-probe-') as temporary:
        parent=Path(temporary)
        directory=parent/'job';directory.mkdir()
        protected=parent/'other-task.txt';protected.write_text('synthetic private fixture')
        probe=directory/'probe.txt'
        command=[str(executable),'app-server']
        wrapped,env=sandbox_command(command,environment,job_directory=directory,
            python_executable=python_executable,adapter='codex')
        process=None;identity=None;confirmed=False
        try:
            process=subprocess.Popen(wrapped,cwd=directory,env=env,stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True)
            identity=_process_identity(process.pid)
            selector=selectors.DefaultSelector();selector.register(process.stdout,selectors.EVENT_READ)
            buffer=b'';deadline=time.monotonic()+timeout
            def rpc(identifier,method,params):
                nonlocal buffer
                process.stdin.write((json.dumps({'id':identifier,'method':method,'params':params})+'\n').encode());process.stdin.flush()
                while time.monotonic()<deadline:
                    while b'\n' in buffer:
                        line,buffer=buffer.split(b'\n',1)
                        item=json.loads(line)
                        if item.get('id')==identifier:return item
                    if not selector.select(min(1,max(0,deadline-time.monotonic()))):continue
                    chunk=os.read(process.stdout.fileno(),65536)
                    if not chunk:raise ToolExecutionUnavailable()
                    buffer+=chunk
                    if len(buffer)>1024*1024:raise ToolExecutionUnavailable()
                raise ToolExecutionUnavailable()
            try:
                initialized=rpc(1,'initialize',{'clientInfo':{'name':'leadtrace_tool_preflight','version':'1'}})
                if 'error' in initialized:raise ToolExecutionUnavailable()
                process.stdin.write(b'{"method":"initialized"}\n');process.stdin.flush()
                code="""from pathlib import Path
import pymupdf
from rdkit import Chem
from rdkit.Chem import Draw
mol=Chem.MolFromSmiles('CCO');assert mol
assert 'svg' in Draw.MolsToGridImage([mol],useSVG=True)
pdf=pymupdf.open();pdf.new_page();pdf.save('synthetic.pdf')
assert pdf[0].get_pixmap().width>0
for path,mode in [(Path.cwd().parent/'other-task.txt','r'),(Path.cwd().parent/'outside-write.txt','w'),(Path('/proc')/str(__import__('os').getppid())/'environ','rb')]:
 try:
  with path.open(mode):pass
 except PermissionError:continue
 raise AssertionError('Isolation boundary failed')
Path('probe.txt').write_text('leadtrace-tool-ok')
"""
                result=rpc(2,'command/exec',{'command':[str(python_executable),'-c',code],
                    'cwd':str(directory),'sandboxPolicy':{'type':'externalSandbox','networkAccess':'enabled'},'timeoutMs':5000})
                if result.get('result',{}).get('exitCode')!=0 or not probe.is_file() or probe.read_text()!='leadtrace-tool-ok':
                    raise ToolExecutionUnavailable()
                return {'command_execution':True,'workspace_write':True,'scientific_imports':True,'isolation_denials':True,'model_calls':0}
            finally:selector.close()
        except (OSError,ValueError,subprocess.SubprocessError):
            raise ToolExecutionUnavailable() from None
        finally:
            if process is not None:
                if process.stdin:process.stdin.close()
                try:
                    _terminate_owned_group(process,identity)
                    require_sandbox_cleanup(env,expected_job_directory=directory,supervisor_identity=identity)
                    confirmed=True
                except (ValueError,OSError,subprocess.TimeoutExpired):
                    raise ToolExecutionCleanupPending({'process_id':process.pid,'process_identity':identity,
                        'sandbox_home':env.get('LEADTRACE_SANDBOX_HOME'),
                        'sandbox_job_directory':str(directory)}) from None
                finally:
                    if process.stdout:process.stdout.close()
            if process is None or confirmed:cleanup_sandbox(env,expected_job_directory=directory)
