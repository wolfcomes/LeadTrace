import json,os,sys,subprocess
from pathlib import Path
import pytest


def test_bridge_refuses_to_start_without_outer_filesystem_isolation(tmp_path,monkeypatch):
    from leadtrace.ops.ai_prefill.codex_bridge import require_outer_sandbox
    monkeypatch.delenv('LEADTRACE_LANDLOCK_GUARD',raising=False)
    with pytest.raises(RuntimeError,match='isolation'):require_outer_sandbox()
    guard=tmp_path/'guard';guard.write_text('synthetic');guard.chmod(0o600)
    monkeypatch.setenv('LEADTRACE_LANDLOCK_GUARD',str(guard))
    with pytest.raises(RuntimeError,match='not enforced'):require_outer_sandbox()


def test_bridge_fresh_thread_and_turn_preserve_requested_runtime(tmp_path):
    from leadtrace.ops.ai_prefill.codex_bridge import produce
    (tmp_path/'task.json').write_text(json.dumps({'runtime':{'model':'gpt-test','reasoning_effort':'high'}}))
    (tmp_path/'prompt.md').write_text('synthetic instructions')
    class RPC:
        def __init__(self):self.calls=[]
        def call(self,method,params):
            self.calls.append((method,params))
            if method=='thread/start':return {'thread':{'id':'fresh-thread'},'model':'gpt-test','reasoningEffort':'high'}
            if method=='turn/start':return {'turn':{'id':'turn-1'}}
            return {}
        def notification(self):return {'method':'turn/completed','params':{'threadId':'fresh-thread','turn':{'id':'turn-1','status':'completed','error':None}}}
    rpc=RPC();assert produce(rpc,tmp_path)==0
    assert rpc.calls[0][0]=='thread/start'
    assert rpc.calls[0][1]['ephemeral'] is True
    assert rpc.calls[0][1]['model']=='gpt-test'
    turn=rpc.calls[1][1]
    assert turn['effort']=='high'
    assert turn['sandboxPolicy']=={'type':'externalSandbox','networkAccess':'enabled'}
    assert turn['input']==[{'type':'text','text':'synthetic instructions'}]
    assert json.loads((tmp_path/'codex-session.json').read_text())['thread_id']=='fresh-thread'


def test_bridge_does_not_report_failed_or_foreign_turn_as_success(tmp_path):
    from leadtrace.ops.ai_prefill.codex_bridge import produce
    (tmp_path/'task.json').write_text(json.dumps({'runtime':{'model':'gpt-test','reasoning_effort':'high'}}))
    (tmp_path/'prompt.md').write_text('synthetic instructions')
    class RPC:
        def call(self,method,params):return {'thread':{'id':'ours'}} if method=='thread/start' else {'turn':{'id':'turn'}}
        def __init__(self):
            self.events=iter([
                {'method':'turn/completed','params':{'threadId':'other','turn':{'id':'turn','status':'completed'}}},
                {'method':'turn/completed','params':{'threadId':'ours','turn':{'id':'old','status':'completed'}}},
                {'method':'turn/completed','params':{'threadId':'ours','turn':{'id':'turn','status':'failed'}}}])
        def notification(self):return next(self.events)
    assert produce(RPC(),tmp_path)==1


def test_native_codex_exec_edit_and_image_tools_in_external_sandbox(tmp_path):
    """Real installed Codex, local deterministic Responses fixture; no provider call."""
    import shutil,threading,time,shlex
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    from leadtrace.ops.ai_prefill.sandbox import sandbox_command,cleanup_sandbox
    from leadtrace.ops.ai_prefill.runtime import RuntimeConfig,build_command
    executable=shutil.which('codex')
    if not executable:pytest.skip('Codex CLI is not installed')
    job=tmp_path/'job';job.mkdir()
    protected=tmp_path/'other-job.txt';protected.write_text('synthetic private content')
    script=job/'scientific-probe.py'
    script.write_text('''from pathlib import Path
import pymupdf
from rdkit import Chem
from rdkit.Chem import Draw
mol=Chem.MolFromSmiles('CCO');assert mol
Path('structure.svg').write_text(Draw.MolsToGridImage([mol],useSVG=True))
pdf=pymupdf.open();pdf.new_page();pdf.save('synthetic.pdf');pdf[0].get_pixmap().save('synthetic.png')
for path,mode in [(Path.cwd().parent/'other-job.txt','r'),(Path.cwd().parent/'outside.txt','w')]:
 try:
  with path.open(mode):pass
 except PermissionError:continue
 raise AssertionError('Isolation failed')
Path('probe.txt').write_text('read-write-render-isolation-ok')
''')
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            raw=self.rfile.read(int(self.headers['Content-Length']))
            if self.headers.get('Content-Encoding')=='zstd':
                import zstandard
                raw=zstandard.ZstdDecompressor().decompress(raw)
            calls.append(json.loads(raw));number=len(calls)
            if number==1:
                item={'id':'fc_1','type':'function_call','call_id':'call_1','name':'exec_command','arguments':json.dumps({'cmd':shlex.join([sys.executable,str(script)]),'max_output_tokens':1000})}
            elif number==2:
                item={'id':'fc_2','type':'custom_tool_call','call_id':'call_2','name':'apply_patch','input':'*** Begin Patch\n*** Add File: edited.txt\n+patch-write-ok\n*** End Patch'}
            elif number==3:
                item={'id':'fc_3','type':'function_call','call_id':'call_3','name':'view_image','arguments':json.dumps({'path':str(job/'synthetic.png')})}
            else:item={'id':'msg_test','type':'message','role':'assistant','status':'completed','content':[{'type':'output_text','text':'Synthetic integration completed.','annotations':[]}]}
            response={'id':'resp_'+str(number),'object':'response','created_at':int(time.time()),'status':'completed','output':[item],'usage':{'input_tokens':10,'output_tokens':10,'total_tokens':20}}
            events=[{'type':'response.created','response':{**response,'status':'in_progress','output':[]}},{'type':'response.output_item.added','output_index':0,'item':item},{'type':'response.output_item.done','output_index':0,'item':item},{'type':'response.completed','response':response}]
            data=''.join('data: '+json.dumps(e)+'\n\n' for e in events).encode()
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    home=tmp_path/'home';config=home/'.codex';config.mkdir(parents=True)
    (config/'config.toml').write_text(f'model_provider="fixture"\n[model_providers.fixture]\nname="Local deterministic test"\nbase_url="http://127.0.0.1:{server.server_port}/v1"\nwire_api="responses"\nrequires_openai_auth=false\n')
    runtime=RuntimeConfig(adapter='codex',model='gpt-6-astra',reasoning_effort='high')
    (job/'task.json').write_text(json.dumps({'runtime':runtime.model_dump()}));(job/'prompt.md').write_text('Synthetic integration fixture.')
    command=build_command(runtime,job,executable,'synthetic')
    command,env=sandbox_command(command,{**os.environ,'HOME':str(home),'CODEX_HOME':str(config)},job_directory=job,python_executable=sys.executable,adapter='codex')
    try:
        result=subprocess.run(command,cwd=job,env=env,capture_output=True,text=True,timeout=40)
        assert result.returncode==0,result.stderr
        assert (job/'probe.txt').read_text()=='read-write-render-isolation-ok',result.stdout
        assert (job/'edited.txt').read_text().strip()=='patch-write-ok',result.stdout
        assert (job/'structure.svg').is_file()
        assert len(calls)==4
        assert 'data:image/png;base64,' in json.dumps(calls[-1]), 'Image tool did not return rendered image'
        record=json.loads((job/'codex-session.json').read_text())
        assert record['status']=='completed' and record['requested_effort']=='high'
        assert not (tmp_path/'outside.txt').exists()
    finally:
        cleanup_sandbox(env);server.shutdown();server.server_close();thread.join(timeout=5)
