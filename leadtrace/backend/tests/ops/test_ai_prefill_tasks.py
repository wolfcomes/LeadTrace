import hashlib
import json
import os
from pathlib import Path

import pytest

from app.ai_prefill.assistance_inputs import prepare_input_package
from app.ai_prefill.assistance_contracts import SourceIdentity
from leadtrace.ops.ai_prefill.tasks import prepare_task, recover_task, run_task, task_status


ROOT = Path(__file__).resolve().parents[4]


def inputs(tmp_path):
    source = tmp_path / 'source.pdf'
    source.write_bytes(b'harmless synthetic source; no scientific content')
    identity = SourceIdentity(paper_key='synthetic-paper', source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                              byte_size=source.stat().st_size, page_count=1)
    package = prepare_input_package(experiment_id='synthetic', source=identity,
                                    guide_version='old-guide', source_path=source)
    inp = tmp_path / 'input.json'
    inp.write_text(package.model_dump_json())
    c = json.loads((ROOT / 'docs/ai-prefill/examples/candidate-v1.json').read_text())
    c.update(source=identity.model_dump(), hashes=None, experiment_id='synthetic')
    c['payload'] = {'schema_version': 1, 'compounds': [
        {'ref': 'c1', 'compound_label': '1', 'structure': {'smiles': 'CCO'}}], 'activities': [], 'lineages': []}
    candidate = tmp_path / 'current.json'
    candidate.write_text(json.dumps(c))
    inv = tmp_path / 'inventory.json'
    inv.write_text(json.dumps({'inventory_version': 1, 'source': identity.model_dump(), 'scope': 'synthetic',
                              'reviewed_by': 'synthetic', 'entries': [{'label': '1', 'required': True,
                              'role': 'assayed', 'source_locator': 'synthetic p1'}]}))
    return inp, source, candidate, inv


def test_prefill_freezes_actual_guides_and_source_and_refuses_overwrite(tmp_path):
    inp, source, _, _ = inputs(tmp_path)
    task = tmp_path / 'task'
    prepare_task(entry='prefill', input_path=inp, output=task)
    assert task_status(task)['state']['status'] == 'prepared'
    manifest = json.loads((task / 'bundle-manifest.json').read_text())
    for path, digest in manifest['files'].items():
        assert hashlib.sha256((task / path).read_bytes()).hexdigest() == digest
    assert (task / 'inputs/source.pdf').read_bytes() == source.read_bytes()
    assert 'extraction-guide.md' in (task / 'prompt.md').read_text()
    assert json.loads((task / 'inputs/input.json').read_text())['guide_version'] == 'model-neutral-v4-20261008'
    with pytest.raises(ValueError, match='exists'):
        prepare_task(entry='prefill', input_path=inp, output=task)


def test_repair_requires_current_candidate_identity_and_binds_baseline(tmp_path):
    inp, _, candidate, inv = inputs(tmp_path)
    with pytest.raises(ValueError, match='candidate'):
        prepare_task(entry='selfcheck', input_path=inp, output=tmp_path / 'missing')
    with pytest.raises(ValueError, match='together'):
        prepare_task(entry='selfcheck', input_path=inp, output=tmp_path / 'workspace',
                     candidate_path=candidate, inventory_path=inv, workspace_version=10)
    prepare_task(entry='selfcheck', input_path=inp, output=tmp_path / 'good',
                 candidate_path=candidate, inventory_path=inv,
                 workspace_id='11111111-1111-1111-1111-111111111111', workspace_version=10)
    task = json.loads((tmp_path / 'good/task.json').read_text())
    assert task['baseline']['candidate_file_sha256'] == hashlib.sha256(candidate.read_bytes()).hexdigest()
    assert task['baseline']['workspace_version'] == 10
    c = json.loads(candidate.read_text()); c['source']['paper_key'] = 'different'; candidate.write_text(json.dumps(c))
    with pytest.raises(ValueError, match='identity'):
        prepare_task(entry='selfcheck', input_path=inp, output=tmp_path / 'bad', candidate_path=candidate, inventory_path=inv)


def test_source_mismatch_and_frozen_bundle_tamper_stop_before_execution(tmp_path):
    inp, source, _, _ = inputs(tmp_path)
    source.write_bytes(b'changed')
    with pytest.raises(ValueError, match='source'):
        prepare_task(entry='prefill', input_path=inp, output=tmp_path / 'bad')
    inp, source, _, _ = inputs(tmp_path)
    task = tmp_path / 'task'; prepare_task(entry='prefill', input_path=inp, output=task)
    (task / 'prompt.md').chmod(0o600); (task / 'prompt.md').write_text('tampered')
    with pytest.raises(ValueError, match='changed'):
        run_task(task, timeout_seconds=5, executable='never-run-this')


def fake_harness(tmp_path, body):
    script = tmp_path / 'fake-dsh'
    script.write_text('#!/usr/bin/env python3\n' + body)
    script.chmod(0o700)
    return str(script)


def test_runner_checks_outputs_and_never_replays_or_reads_logs(tmp_path):
    inp, _, candidate, inv = inputs(tmp_path)
    task = tmp_path / 'task'
    prepare_task(entry='selfcheck', input_path=inp, output=task, candidate_path=candidate, inventory_path=inv)
    fake = fake_harness(tmp_path, '''import json, hashlib, pathlib
p=pathlib.Path('.')
t=json.loads((p/'task.json').read_text())
c=json.loads((p/'inputs/current-candidate.json').read_text())
c['parent_candidate_id']=c['candidate_id']; c['candidate_id']=t['candidate_id']; c['recipe']['guide_version']=t['guide_version']
(p/'outputs/candidate.json').write_text(json.dumps(c))
(p/'outputs/compound-inventory.json').write_bytes((p/'inputs/compound-inventory.json').read_bytes())
checks=['compound_scope','measurement_coverage','activity_semantics','structure_identity','source_crops','sar_reasoning','synthesis_paths']
r={'self_review_version':1,'candidate_file_sha256':hashlib.sha256((p/'outputs/candidate.json').read_bytes()).hexdigest(),'reviewer_type':'producer_self_check','checks':[{'check_id':s,'status':'checked','details':'synthetic fixture','source_locations':['synthetic p1']} for s in checks]}
(p/'outputs/self-review.json').write_text(json.dumps(r))
print('SENSITIVE_REASONING_SENTINEL')
''')
    result = run_task(task, timeout_seconds=5, executable=fake, lock_root=tmp_path / 'locks')
    assert result['state']['status'] == 'ready_for_independent_review'
    assert result['scientific_approval'] is False
    assert 'SENSITIVE_REASONING_SENTINEL' not in json.dumps(result)
    assert (task / 'checks/self-check.json').exists()
    assert json.loads((task / 'checks/candidate-diff.json').read_text())['payload_changed'] is False
    with pytest.raises(ValueError, match='already'):
        run_task(task, timeout_seconds=5, executable=fake, lock_root=tmp_path / 'locks')


def test_exit_zero_without_candidate_is_partial_and_timeout_is_saved(tmp_path):
    inp, _, _, _ = inputs(tmp_path)
    task = tmp_path / 'task'; prepare_task(entry='prefill', input_path=inp, output=task)
    result = run_task(task, timeout_seconds=5, executable=fake_harness(tmp_path, 'pass\n'), lock_root=tmp_path / 'locks')
    assert result['state']['status'] == 'partial'
    next_task = tmp_path / 'timeout'; prepare_task(entry='prefill', input_path=inp, output=next_task)
    result = run_task(next_task, timeout_seconds=0.1, executable=fake_harness(tmp_path, 'import time\ntime.sleep(20)\n'), lock_root=tmp_path / 'locks')
    assert result['state']['status'] == 'timed_out'
    assert result['state']['exit_code'] is not None


def test_continuation_checks_paper_and_does_not_claim_native_resume(tmp_path):
    inp, _, candidate, inv = inputs(tmp_path)
    old = tmp_path / 'old'; prepare_task(entry='prefill', input_path=inp, output=old)
    new = tmp_path / 'new'
    prepare_task(entry='selfcheck', input_path=inp, output=new, candidate_path=candidate, inventory_path=inv, previous_task=old)
    metadata = json.loads((new / 'task.json').read_text())
    assert metadata['continuation']['strategy'] == 'structured_handoff_new_session'
    c = json.loads(inp.read_text()); c['target']['paper_key'] = 'other'; inp.write_text(json.dumps(c))
    with pytest.raises(ValueError, match='identity'):
        prepare_task(entry='prefill', input_path=inp, output=tmp_path / 'bad', previous_task=old)


def test_shared_paper_lock_prevents_two_writers(tmp_path):
    import fcntl
    inp, _, _, _ = inputs(tmp_path)
    task = tmp_path / 'task'; prepare_task(entry='prefill', input_path=inp, output=task)
    lock_root = tmp_path / 'locks'; lock_root.mkdir()
    key = hashlib.sha256(b'synthetic-paper').hexdigest()
    with (lock_root / (key + '.lock')).open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='writer'):
            run_task(task, timeout_seconds=5, executable='never-run-this', lock_root=lock_root)
    assert task_status(task)['state']['status'] == 'prepared'


def test_timeout_kills_child_even_if_leader_exits_on_term(tmp_path):
    inp, _, _, _ = inputs(tmp_path)
    task = tmp_path / 'task'; prepare_task(entry='prefill', input_path=inp, output=task)
    fake = fake_harness(tmp_path, '''import os, signal, time, pathlib
pid=os.fork()
if pid == 0:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    pathlib.Path('child.pid').write_text(str(os.getpid()))
    time.sleep(20)
else:
    time.sleep(20)
''')
    try:
        result = run_task(task, timeout_seconds=0.3, executable=fake, lock_root=tmp_path / 'locks')
        assert result['state']['status'] == 'timed_out'
        child = int((task / 'child.pid').read_text())
        import time
        for _ in range(20):
            proc = Path(f'/proc/{child}/stat')
            if not proc.exists() or proc.read_text().rsplit(')', 1)[1].split()[0] == 'Z':
                break
            time.sleep(0.01)
        else:
            pytest.fail('Timed-out descendant still executing')
    finally:
        if (task / 'child.pid').exists():
            import signal
            try:
                os.kill(int((task / 'child.pid').read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_runner_uses_actual_dsh_home(tmp_path, monkeypatch):
    from leadtrace.ops.ai_prefill import harness_sessions
    inp, _, _, _ = inputs(tmp_path)
    task = tmp_path / 'task'; prepare_task(entry='prefill', input_path=inp, output=task)
    actual_home = tmp_path / 'private-harness'
    monkeypatch.setenv('DSH_HOME', str(actual_home))
    calls = []
    monkeypatch.setattr(harness_sessions, 'find_sessions_for_cwd', lambda cwd, home: calls.append(home) or [])
    run_task(task, timeout_seconds=5, executable=fake_harness(tmp_path, 'pass\n'), lock_root=tmp_path / 'locks')
    assert calls and all(x == actual_home for x in calls)


def test_session_binding_excludes_existing_same_directory_session(tmp_path, monkeypatch):
    from leadtrace.ops.ai_prefill import harness_sessions
    inp, _, _, _ = inputs(tmp_path)
    task = tmp_path / 'task'; prepare_task(entry='prefill', input_path=inp, output=task)
    responses = iter([[{'session_id': 'old'}], [{'session_id': 'old'}, {'session_id': 'new'}]])
    monkeypatch.setattr(harness_sessions, 'find_sessions_for_cwd', lambda cwd, home: next(responses))
    result = run_task(task, timeout_seconds=5, executable=fake_harness(tmp_path, 'pass\n'), lock_root=tmp_path / 'locks')
    assert result['state']['producer_session_ids'] == ['new']
    assert result['state']['session_binding'] == 'new_exact_cwd_match'


def test_recover_requires_no_active_writer_and_preserves_artifacts(tmp_path):
    import fcntl
    inp, _, candidate, inv = inputs(tmp_path)
    task = tmp_path / 'task'; prepare_task(entry='prefill', input_path=inp, output=task)
    locks = tmp_path / 'locks'; locks.mkdir()
    state = json.loads((task / 'state.json').read_text())
    state.update(status='running', process_id=None, lock_root=str(locks))
    (task / 'state.json').write_text(json.dumps(state))
    key = hashlib.sha256(b'synthetic-paper').hexdigest()
    with (locks / (key + '.lock')).open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='writer'):
            recover_task(task)
    (task / 'outputs/partial.txt').write_text('preserved')
    result = recover_task(task)
    assert result['state']['status'] == 'interrupted'
    assert (task / 'outputs/partial.txt').read_text() == 'preserved'
    prepare_task(entry='selfcheck', input_path=inp, output=tmp_path / 'continued',
                 candidate_path=candidate, inventory_path=inv, previous_task=task)


def test_recovery_refuses_live_process_even_with_free_lock(tmp_path):
    from leadtrace.ops.ai_prefill.tasks import _process_identity
    inp, _, _, _ = inputs(tmp_path)
    task = tmp_path / 'task'; prepare_task(entry='prefill', input_path=inp, output=task)
    state = json.loads((task / 'state.json').read_text())
    state.update(status='running', process_id=os.getpid(), process_identity=_process_identity(os.getpid()),
                 lock_root=str(tmp_path / 'locks'))
    (task / 'state.json').write_text(json.dumps(state))
    with pytest.raises(ValueError, match='active'):
        recover_task(task)
    assert task_status(task)['state']['status'] == 'running'


def test_cli_two_entries_and_session_export_never_overwrites(tmp_path, capsys):
    from leadtrace.ops.ai_prefill.cli import main
    inp, _, candidate, inv = inputs(tmp_path)
    task = tmp_path / 'cli-task'
    assert main(['task', 'selfcheck', '--input', str(inp), '--candidate', str(candidate),
                 '--inventory', str(inv), '--output', str(task)]) == 0
    assert json.loads(capsys.readouterr().out)['task']['entry'] == 'selfcheck'
    assert main(['task', 'status', str(task)]) == 0
    assert json.loads(capsys.readouterr().out)['state']['status'] == 'prepared'
    out = tmp_path / 'sessions.json'
    assert main(['session', 'inspect', '--run-dir', str(task), '--dsh-home', str(tmp_path / 'dsh'), '--output', str(out)]) == 0
    capsys.readouterr()
    before = out.read_bytes()
    assert main(['session', 'inspect', '--run-dir', str(task), '--dsh-home', str(tmp_path / 'dsh'), '--output', str(out)]) != 0
    assert before == out.read_bytes()


def test_explicit_runtime_is_frozen_and_review_is_separate_read_only_job(tmp_path):
    inp, _, candidate, inv = inputs(tmp_path)
    job = tmp_path / 'review'
    prepare_task(entry='review', input_path=inp, output=job, candidate_path=candidate,
                 inventory_path=inv, adapter='codex', model='gpt-test', reasoning_effort='high')
    task = json.loads((job / 'task.json').read_text())
    assert task['runtime']['adapter'] == 'codex'
    assert task['runtime']['reasoning_effort'] == 'high'
    assert 'independent' in (job / 'prompt.md').read_text().lower()
    assert 'Do not repair' in (job / 'prompt.md').read_text()
    fake = fake_harness(tmp_path, '''import pathlib,json,hashlib
p=pathlib.Path('.')
r={'candidate_file_sha256':hashlib.sha256((p/'inputs/current-candidate.json').read_bytes()).hexdigest(), 'source_sha256':hashlib.sha256((p/'inputs/source.pdf').read_bytes()).hexdigest(), 'complete_scope':False,'unreviewed_scope':['synthetic'], 'scientific_approval':False}
(p/'outputs/audit-summary.json').write_text(json.dumps(r))
''')
    result=run_task(job, executable=fake, timeout_seconds=10, lock_root=tmp_path/'locks')
    assert result['state']['status']=='partial'
    assert (job/'inputs/current-candidate.json').read_bytes()==candidate.read_bytes()
    provenance=json.loads((job/'runtime-provenance.json').read_text())
    assert provenance['verification']=='requested_only'
    assert provenance['requested']['model']=='gpt-test'
    assert not (job/'outputs/candidate.json').exists()

    from leadtrace.ops.ai_prefill.provenance import export_run_provenance
    record = export_run_provenance(job, candidate)
    assert record['stage'] == 'independent_review' and record['outcome'] == 'partial'
    assert record['model'] == 'gpt-test'
    with pytest.raises(ValueError, match='review cannot apply'):
        export_run_provenance(job, candidate, applied_workspace_version=2)
    tampered = tmp_path/'other-candidate.json'
    tampered.write_bytes(candidate.read_bytes()+b'\n')
    with pytest.raises(ValueError, match='bytes'):
        export_run_provenance(job, tampered)


def test_running_task_can_be_cancelled_without_early_completion(tmp_path):
    inp,_,_,_=inputs(tmp_path)
    job=tmp_path/'cancel-task'
    prepare_task(entry='prefill',input_path=inp,output=job)
    fake=fake_harness(tmp_path,'import time\ntime.sleep(20)\n')
    from time import monotonic
    start=monotonic()
    result=run_task(job,executable=fake,timeout_seconds=30,lock_root=tmp_path/'locks',
                    should_cancel=lambda:monotonic()-start>0.5)
    assert result['state']['status']=='cancelled'
    assert result['state']['exit_code'] is not None


def test_exception_after_leader_exit_still_stops_descendant(tmp_path):
    import time
    import signal
    inp,_,_,_=inputs(tmp_path)
    job=tmp_path/'exception-task'
    prepare_task(entry='prefill',input_path=inp,output=job)
    fake=fake_harness(tmp_path,'''import os,signal,time,pathlib
pid=os.fork()
if pid==0:
    os.setpgid(0,0)
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    pathlib.Path('child.pid').write_text(str(os.getpid()))
    time.sleep(30)
else:
    os._exit(0)
''')
    def failed_heartbeat():
        deadline=time.monotonic()+3
        while not (job/'child.pid').exists() and time.monotonic()<deadline:time.sleep(.01)
        time.sleep(.05)
        raise RuntimeError('Synthetic heartbeat failure after leader exit')
    child=None
    try:
        result=run_task(job,executable=fake,timeout_seconds=10,lock_root=tmp_path/'locks',heartbeat=failed_heartbeat)
        child=int((job/'child.pid').read_text())
        assert result['state']['status']=='failed'
        assert result['state']['process_cleanup_confirmed'] is True
        path=Path(f'/proc/{child}/stat')
        assert not path.exists() or path.read_text().rsplit(')',1)[1].split()[0]=='Z'
    finally:
        if child:
            try:os.kill(child,signal.SIGKILL)
            except ProcessLookupError:pass


def test_admin_runner_uses_isolated_home_and_removes_it_after_exit(tmp_path,monkeypatch):
    # Exercise common isolation with the simple headless adapter; Codex RPC has native tests.
    inp,_,_,_=inputs(tmp_path)
    job=tmp_path/'sandboxed-task'
    prepare_task(entry='prefill',input_path=inp,output=job,adapter='dsh',model='deepseek-flash',reasoning_effort='high')
    empty_home=tmp_path/'empty-home';empty_home.mkdir()
    monkeypatch.setenv('HOME',str(empty_home));monkeypatch.setenv('CODEX_HOME',str(empty_home/'.codex'))
    monkeypatch.setenv('LEADTRACE_TEST_SECRET','must-not-reach-child')
    fake=fake_harness(job,'''import os,json,pathlib
pathlib.Path('outputs/runtime-probe.json').write_text(json.dumps({'home':os.environ['HOME'],'secret':os.environ.get('LEADTRACE_TEST_SECRET')}))
''')
    result=run_task(job,executable=fake,timeout_seconds=10,lock_root=tmp_path/'locks',sandboxed=True)
    assert result['state']['status']=='partial', (job/'stderr.log').read_text()
    probe=json.loads((job/'outputs/runtime-probe.json').read_text())
    assert probe['home']!=str(empty_home) and probe['secret'] is None
    assert result['state']['process_cleanup_confirmed'] is True
    assert not Path(result['state']['sandbox_home']).exists()


def _combined_review_job(tmp_path):
    inp, _, candidate, inv = inputs(tmp_path)
    job = tmp_path / 'combined-review'
    prepare_task(entry='review', input_path=inp, output=job, candidate_path=candidate,
                 inventory_path=inv, review_with_repair=True)
    task = json.loads((job / 'task.json').read_text())
    targets = json.loads((job / 'inputs/review-targets.json').read_text())
    rows = [{'domain': domain, 'ref': ref, 'verdict': 'uncertain', 'source_locations': ['synthetic p1'],
             'checked_fields': ['identity'], 'field_results': {'identity': 'uncertain'},
             'expected': 'synthetic', 'observed': 'synthetic', 'reason': 'synthetic uncertainty'}
            for domain, refs in targets.items() for ref in refs]
    (job / 'outputs/rows.json').write_text(json.dumps(rows))
    (job / 'outputs/audit-summary.json').write_text(json.dumps({
        'candidate_file_sha256': task['baseline']['candidate_file_sha256'],
        'source_sha256': task['source']['source_sha256'], 'complete_scope': True,
        'unreviewed_scope': [], 'scientific_approval': False, 'item_reports': ['rows.json']}))
    return job, task, candidate


def _combined_proposal(job, task, candidate, *, changed=True):
    c = json.loads(candidate.read_text())
    c.update(parent_candidate_id=c['candidate_id'], candidate_id=task['candidate_id'])
    c['recipe']['guide_version'] = task['guide_version']
    if changed:
        c['payload']['compounds'][0]['structure']['smiles'] = 'CCCO'
    (job / 'outputs/candidate.json').write_text(json.dumps(c))
    (job / 'outputs/compound-inventory.json').write_bytes((job / 'inputs/compound-inventory.json').read_bytes())
    from app.ai_prefill.assistance_self_check import SOURCE_REVIEW_CHECKS
    (job / 'outputs/self-review.json').write_text(json.dumps({
        'self_review_version': 1, 'candidate_file_sha256': hashlib.sha256((job / 'outputs/candidate.json').read_bytes()).hexdigest(),
        'reviewer_type': 'producer_self_check', 'checks': [
            {'check_id': name, 'status': 'unresolved', 'details': 'synthetic uncertainty'} for name in SOURCE_REVIEW_CHECKS]}))


def test_combined_review_runs_once_and_binds_audit_and_proposal_separately(tmp_path):
    job, task, candidate = _combined_review_job(tmp_path)
    _combined_proposal(job, task, candidate)
    prompt = (job / 'prompt.md').read_text()
    assert task['review_with_repair'] is True
    assert 'SAME session' in prompt and 'NOT another independent review' in prompt
    fake = fake_harness(tmp_path, "import pathlib\np=pathlib.Path('invocations'); p.write_text(p.read_text()+'x' if p.exists() else 'x')\n")
    result = run_task(job, executable=fake, timeout_seconds=10, lock_root=tmp_path / 'locks')
    assert (job / 'invocations').read_text() == 'x'
    assert result['state']['status'] == 'review_complete'
    assert result['state']['repair_proposal_status'] == 'ready'
    assert result['state']['repair_self_check_status'] == 'needs_revision'
    assert (job / 'inputs/current-candidate.json').read_bytes() == candidate.read_bytes()
    provenance = json.loads((job / 'runtime-provenance.json').read_text())
    assert provenance['candidate_file_sha256'] == task['baseline']['candidate_file_sha256']
    assert provenance['proposal_candidate_file_sha256'] == result['state']['candidate_file_sha256']
    assert provenance['candidate_file_sha256'] != provenance['proposal_candidate_file_sha256']


@pytest.mark.parametrize('fault', ['missing', 'bad_parent', 'invalid_json', 'missing_self_review', 'bad_declared_hash', 'invalid_structure'])
def test_combined_review_preserves_valid_audit_when_proposal_unavailable(tmp_path, fault):
    from leadtrace.ops.ai_prefill.tasks import _postflight
    job, task, candidate = _combined_review_job(tmp_path)
    if fault != 'missing':
        _combined_proposal(job, task, candidate)
        path = job / 'outputs/candidate.json'
        if fault == 'invalid_json':
            path.write_text('{broken')
        elif fault == 'missing_self_review':
            (job / 'outputs/self-review.json').unlink()
        else:
            c = json.loads(path.read_text())
            if fault == 'bad_parent':
                c['parent_candidate_id'] = 'wrong-parent'
            elif fault == 'invalid_structure':
                c['payload']['compounds'][0]['structure']['smiles'] = 'C1broken'
            else:
                c['hashes'] = {'candidate_sha256': '0' * 64}
            path.write_text(json.dumps(c))
    status, details = _postflight(job, task)
    assert status == 'partial'
    assert details['complete_scope'] is True
    assert details['repair_proposal_status'] == 'unavailable'
    assert details['repair_proposal_errors']
    assert details['audit_summary'] == 'outputs/audit-summary.json'
    assert 'candidate_file_sha256' not in details


@pytest.mark.parametrize('candidate_output', [False, True])
def test_combined_review_explicit_no_change_is_not_scientific_approval(tmp_path, candidate_output):
    from leadtrace.ops.ai_prefill.tasks import _postflight
    job, task, candidate = _combined_review_job(tmp_path)
    if candidate_output:
        _combined_proposal(job, task, candidate, changed=False)
    else:
        (job / 'outputs/repair-outcome.json').write_text(json.dumps({
            'status': 'no_changes', 'reason': 'Synthetic source conflict cannot be resolved'}))
    status, details = _postflight(job, task)
    assert status == 'review_complete'
    assert details['repair_proposal_status'] == 'no_changes'
    assert json.loads((job / 'outputs/audit-summary.json').read_text())['scientific_approval'] is False


def test_combined_review_flag_rejected_for_producer(tmp_path):
    inp, _, _, _ = inputs(tmp_path)
    with pytest.raises(ValueError, match='requires a review'):
        prepare_task(entry='prefill', input_path=inp, output=tmp_path / 'bad', review_with_repair=True)


def test_combined_review_accepts_task_relative_item_reports(tmp_path):
    job, task, candidate = _combined_review_job(tmp_path)
    _combined_proposal(job, task, candidate)
    path=job/'outputs/audit-summary.json';summary=json.loads(path.read_text())
    summary['item_reports']=['outputs/rows.json'];path.write_text(json.dumps(summary))
    fake=fake_harness(tmp_path,"pass\n")
    result=run_task(job,executable=fake,timeout_seconds=10,lock_root=tmp_path/'locks')
    assert result['state']['status']=='review_complete'
    assert result['state']['repair_proposal_status']=='ready'
