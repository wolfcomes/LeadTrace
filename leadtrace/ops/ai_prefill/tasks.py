"""Frozen producer jobs. No database access, scientific approval or native resume.

This local operator runner is not a security sandbox or a background scheduler.
Its process lock coordinates all jobs using the same lock root; children inherit
the lock so a supervisor crash cannot immediately allow a second writer.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
from uuid import UUID, uuid4

from app.ai_prefill.assistance_contracts import CandidateEnvelope, validate_declared_hashes
from app.ai_prefill.assistance_coverage import CompoundInventory
from app.ai_prefill.assistance_inputs import PrefillInputPackage
from app.ai_prefill.assistance_self_check import SourceSelfReview, self_check_candidate


GUIDE_VERSION = 'deepseek-led-v3-20260923'
REPOSITORY = Path(__file__).resolve().parents[3]
GUIDES = (
    'START_HERE.md', 'extraction-guide.md', 'deepseek-supervised-runbook.md',
    'deepseek-self-check-guide.md', 'deepseek-quality-checklist.md',
    'quality-audit-protocol.md', 'quality-pitfalls.md',
    'prompts/deepseek-task.md', 'prompts/deepseek-revision.md', 'prompts/deepseek-audit.md',
    'templates/deepseek-quality-record.json', 'templates/deepseek-self-review.json',
    'templates/run-state.json', 'templates/run-handoff.md',
    'schemas/compound-inventory-v1.json', 'schemas/source-self-review-v1.json',
    'examples/candidate-v1.json',
)


def _now():
    return datetime.now(UTC).isoformat()


def _hash(path: Path) -> str:
    # Hash bytes only; never extract or return source content.
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def _write(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.task-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _same_source(a, b):
    # Optional DOI absent in old envelopes need not reject the same exact source.
    return all(getattr(a, k) == getattr(b, k) for k in ('paper_key', 'source_sha256', 'byte_size', 'page_count')) and not (
        a.doi and b.doi and a.doi != b.doi)


def _regular(path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError('Expected a regular artifact file: ' + str(path))
    return path


def _verify_bundle(directory: Path):
    state = _json(_regular(directory / 'state.json'))
    manifest_path = _regular(directory / 'bundle-manifest.json')
    if _hash(manifest_path) != state['bundle_manifest_sha256']:
        raise ValueError('Frozen bundle manifest changed')
    manifest = _json(manifest_path)
    for name, digest in manifest['files'].items():
        path = directory / name
        if path.resolve().is_relative_to(directory) is False or path.is_symlink() or _hash(path) != digest:
            raise ValueError('Frozen bundle changed: ' + name)
    return state


def _prompt(task: dict) -> str:
    entry = task['entry']
    repair = entry == 'selfcheck'
    read = ['bundle/extraction-guide.md', 'bundle/deepseek-self-check-guide.md']
    read.append('bundle/prompts/deepseek-revision.md' if repair else 'bundle/prompts/deepseek-task.md')
    action = (
        'Start from inputs/current-candidate.json and inputs/compound-inventory.json. '
        'Check inputs/feedback.json when present; preserve all unaffected data and human edits. '
        'Repair the affected scope and shared dependencies. Do not rebuild the whole paper unless '
        'the inventory or evidence is unreliable. Previous-session metadata is provenance, not independent review.'
        if repair else
        'Survey the complete supplied source inventory and measurements; save checkpoints. '
        'Verify representative cores, regio/stereochemistry and attachment sites before family expansion. '
        'Continue extraction and producer self-check in this session; do not wait for Codex between routine checkpoints.'
    )
    return f'''You are the sole DeepSeek scientific producer for this frozen LeadTrace task.
Read task.json and inputs/input.json first, then {', '.join(read)}.
Read inputs/handoff.json and inputs/previous-task.json when present; verify their
paper/source/parent identity against task.json before using previous conclusions.
Read bundle/deepseek-quality-checklist.md at delivery. The full current bundle is frozen;
other guides are available by reference, not mandatory repeated reading. Task-specific
values here override placeholders in the prompt templates. Mode: {task['mode']}.
{action}
Authorized original source: inputs/source.pdf. Confirm its title/DOI/page count against
the input identity; report mismatch and stop rather than guessing. Preserve numbered or
labelled complete identities, including unassayed Methods intermediates. Unresolved
complete identities stay required; generic scaffolds/fragments need explicit ineligibility reasons.
Before expensive source checks run deterministic candidate checks, including graph diagnostics.
No Preview/production access, credentials, database writes or external messaging. This
task directory is the output boundary; source and bundle are read-only inputs. Do not
read unrelated paper runs, harness configuration, reasoning logs or other session transcripts.
Write a complete CandidateEnvelope.v1 to outputs/candidate.json, compound inventory to
outputs/compound-inventory.json, and the seven-check producer source review to outputs/self-review.json.
candidate_id={task['candidate_id']}; experiment_id={task['experiment_id']}; guide_version={GUIDE_VERSION}.
parent_candidate_id={task['baseline'].get('candidate_id')!r}. Do not copy stale declared hashes.
Bind self-review to the final candidate FILE SHA256. Keep unverified whole-paper checks
unresolved: partial repair and inherited evidence are not a new full-paper certification.
Save concise outputs/handoff.json with resolved entity refs, actual source locations,
unresolved items, changed/unchanged scope and the next action. Use per-event/variant records;
do not repeat full candidates in prose or use blanket Scheme references as per-item proof.
Program checks (read CLI --help if needed) use {sys.executable} -m leadtrace.ops.ai_prefill:
  candidate validate outputs/candidate.json
  candidate coverage outputs/candidate.json --inventory outputs/compound-inventory.json
  candidate self-check outputs/candidate.json --inventory outputs/compound-inventory.json --self-review outputs/self-review.json --output outputs/self-check.json
At most two producer correction cycles in this job. Save partial artifacts early and stop
with honest unresolved findings at the time budget. A fresh independent DeepSeek review
is a separate step; this producer must never assert independent or human approval.
'''


def prepare_task(*, entry: str, input_path: Path, output: Path, mode: str = 'routine',
                 candidate_path: Path | None = None, inventory_path: Path | None = None,
                 feedback_path: Path | None = None, previous_task: Path | None = None,
                 handoff_path: Path | None = None, workspace_id: str | None = None,
                 workspace_version: int | None = None) -> dict:
    if entry not in {'prefill', 'selfcheck'} or mode not in {'routine', 'evaluation'}:
        raise ValueError('Unknown task entry or mode')
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('Task output already exists; choose a new directory')
    if output.resolve().is_relative_to(REPOSITORY):
        raise ValueError('Task artifacts must be outside the source checkout')
    if bool(workspace_id) != (workspace_version is not None):
        raise ValueError('workspace ID and version must be supplied together')
    if workspace_id:
        workspace_id = str(UUID(workspace_id))
        if not isinstance(workspace_version, int) or isinstance(workspace_version, bool) or workspace_version < 1:
            raise ValueError('workspace version must be positive')
    package = PrefillInputPackage.model_validate_json(input_path.read_bytes())
    if not package.source_locator.path:
        raise ValueError('A local source path is required for headless tasks')
    source = Path(package.source_locator.path)
    if not source.is_absolute():
        raise ValueError('The source locator must be an absolute path')
    if not source.is_file() or source.stat().st_size != package.target.byte_size or _hash(source) != package.target.source_sha256:
        raise ValueError('Actual source bytes/hash do not match the input identity')
    if entry == 'selfcheck' and (candidate_path is None or inventory_path is None):
        raise ValueError('selfcheck requires the current candidate and compound inventory')
    if entry == 'prefill' and any(x is not None for x in (candidate_path, inventory_path, feedback_path, workspace_id)):
        raise ValueError('Use selfcheck for candidate, inventory, feedback or workspace inputs')
    baseline = {'candidate_id': None, 'candidate_file_sha256': None,
                'workspace_id': workspace_id, 'workspace_version': workspace_version,
                'live_version_verified': False}
    if candidate_path:
        candidate = CandidateEnvelope.model_validate_json(candidate_path.read_bytes())
        validate_declared_hashes(candidate)
        if not _same_source(candidate.source, package.target):
            raise ValueError('Current candidate source identity differs from task input')
        inventory = CompoundInventory.model_validate_json(inventory_path.read_bytes())
        if not _same_source(inventory.source, package.target):
            raise ValueError('Inventory source identity differs from task input')
        baseline.update(candidate_id=candidate.candidate_id, candidate_file_sha256=_hash(candidate_path))
    continuation = {'strategy': 'fresh_session', 'previous_task': None, 'producer_session_ids': []}
    previous_record = None
    if previous_task:
        previous_task = previous_task.resolve()
        _verify_bundle(previous_task)
        previous_record = _json(previous_task / 'task.json')
        from app.ai_prefill.assistance_contracts import SourceIdentity
        if not _same_source(SourceIdentity.model_validate(previous_record['source']), package.target):
            raise ValueError('Previous task source identity differs from current input')
        previous_state = _json(previous_task / 'state.json')
        if previous_state['status'] == 'running':
            raise ValueError('Previous task still running; resolve its process before continuing')
        continuation.update(strategy='structured_handoff_new_session', previous_task=str(previous_task),
                            producer_session_ids=previous_state.get('producer_session_ids', []))
    if handoff_path:
        _json(handoff_path)
        continuation['strategy'] = 'structured_handoff_new_session'
    if feedback_path:
        _json(feedback_path)
    task = {'task_version': 1, 'task_id': uuid4().hex, 'entry': entry, 'mode': mode,
            'guide_version': GUIDE_VERSION, 'created_at_utc': _now(),
            'source': package.target.model_dump(mode='json'), 'experiment_id': package.experiment_id,
            'candidate_id': 'candidate-' + uuid4().hex, 'baseline': baseline, 'continuation': continuation,
            'permissions': {'preview_apply': False, 'scientific_approval': False},
            'budget': {'max_producer_correction_cycles': 2, 'token_cap_enforced': False},
            'repository_checkout': str(REPOSITORY)}
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.prefill-prepare-', dir=output.parent))
    try:
        for name in ('inputs', 'bundle', 'outputs', 'checks'):
            (temporary / name).mkdir()
        for name in GUIDES:
            dest = temporary / 'bundle' / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPOSITORY / 'docs/ai-prefill' / name, dest)
        _write(temporary / 'bundle/schemas/candidate-envelope-v1.json', CandidateEnvelope.model_json_schema())
        shutil.copyfile(input_path, temporary / 'inputs/original-input.json')
        shutil.copyfile(source, temporary / 'inputs/source.pdf')
        if _hash(temporary / 'inputs/source.pdf') != package.target.source_sha256:
            raise ValueError('Source changed while building task')
        package.guide_version = GUIDE_VERSION
        package.source_locator.path = str(output.resolve() / 'inputs/source.pdf')
        package.parent_candidate_id = baseline['candidate_id']
        package.recipe = {**package.recipe, 'entry': entry, 'mode': mode, 'candidate_id': task['candidate_id']}
        _write(temporary / 'inputs/input.json', package.model_dump(mode='json'))
        for src, dest in ((candidate_path, 'current-candidate.json'), (inventory_path, 'compound-inventory.json'),
                          (feedback_path, 'feedback.json'), (handoff_path, 'handoff.json')):
            if src:
                shutil.copyfile(src, temporary / 'inputs' / dest)
        if candidate_path and _hash(temporary / 'inputs/current-candidate.json') != baseline['candidate_file_sha256']:
            raise ValueError('Current candidate changed while building task')
        if previous_record:
            _write(temporary / 'inputs/previous-task.json', previous_record)
            old_handoff = previous_task / 'outputs/handoff.json'
            if old_handoff.is_file() and not handoff_path:
                _json(_regular(old_handoff))
                shutil.copyfile(old_handoff, temporary / 'inputs/handoff.json')
        _write(temporary / 'task.json', task)
        (temporary / 'prompt.md').write_text(_prompt(task), encoding='utf-8')
        frozen = [p for p in temporary.rglob('*') if p.is_file()]
        _write(temporary / 'bundle-manifest.json', {'manifest_version': 1,
               'files': {str(p.relative_to(temporary)): _hash(p) for p in sorted(frozen)}})
        _write(temporary / 'state.json', {'status': 'prepared', 'updated_at_utc': _now(),
               'bundle_manifest_sha256': _hash(temporary / 'bundle-manifest.json'), 'producer_session_ids': []})
        for path in [*frozen, temporary / 'bundle-manifest.json']:
            path.chmod(0o400)
        # Reserve the new name exclusively. Never replace even an empty existing job.
        output.mkdir(mode=0o700)
        for path in temporary.iterdir():
            path.rename(output / path.name)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return task_status(output)


def task_status(directory: Path) -> dict:
    directory = directory.resolve()
    task = _json(_regular(directory / 'task.json'))
    state = _json(_regular(directory / 'state.json'))
    live = _process_identity(state.get('process_id'))
    return {'ok': True, 'task_directory': str(directory), 'task': task, 'state': state,
            'leader_identity_matches': bool(live and live == state.get('process_identity')),
            'scientific_approval': False, 'preview_applied': False,
            'note': 'State is a saved checkpoint, not a live process or workspace-version guarantee.'}


def _process_identity(pid):
    if not pid:
        return None
    try:
        fields = Path(f'/proc/{int(pid)}/stat').read_text().rsplit(')', 1)[1].split()
        return {'pid': int(pid), 'start_ticks': int(fields[19]),
                'process_group': int(fields[2]), 'session': int(fields[3]),
                'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    except FileNotFoundError:
        return None


def _lock_directory(lock_root: Path | None):
    return (lock_root or Path(os.environ.get('LEADTRACE_PREFILL_LOCK_ROOT',
                 str(Path.home() / '.local/state/leadtrace/ai-prefill/locks')))).resolve()


@contextmanager
def _writer_lock(paper_key: str, lock_root: Path | None):
    root = _lock_directory(lock_root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = hashlib.sha256(paper_key.encode()).hexdigest()
    fd = os.open(root / (key + '.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another writer owns this paper; do not start a second producer') from None
        yield fd
    finally:
        # Do not explicitly unlock: the child inherits this fd until it exits.
        os.close(fd)


def recover_task(directory: Path) -> dict:
    """Close an abandoned checkpoint, without terminating or replaying processes."""
    directory = directory.resolve()
    state = _verify_bundle(directory)
    task = _json(directory / 'task.json')
    if state['status'] != 'running':
        raise ValueError('Only an abandoned running task needs recovery')
    lock_root = Path(state['lock_root']) if state.get('lock_root') else None
    with _writer_lock(task['source']['paper_key'], lock_root):
        # A child may have closed the inherited descriptor; also check the owned
        # process session conservatively. Never signal a possibly reused PID.
        state = _verify_bundle(directory)
        if state['status'] != 'running':
            raise ValueError('Task changed while acquiring recovery lock')
        recorded = state.get('process_identity')
        pid = state.get('process_id')
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        if pid and (not recorded or recorded['boot_id'] == boot):
            for path in Path('/proc').iterdir():
                if path.name.isdigit():
                    live = _process_identity(int(path.name))
                    if live and (live['pid'] == pid or live['session'] == pid):
                        # Zombies cannot write and do not hold writer locks.
                        try:
                            status = (path / 'stat').read_text().rsplit(')', 1)[1].split()[0]
                        except FileNotFoundError:
                            continue
                        if status != 'Z':
                            raise ValueError('Task process session may still be active; recovery refused')
        state.update(status='interrupted', recovered_at_utc=_now(), updated_at_utc=_now(),
                     recovery='Writer lock free and no active original process session; artifacts preserved')
        _write(directory / 'state.json', state)
    return task_status(directory)


def _terminate_owned_group(process):
    """Stop descendants even when the leader exits before its tool children."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    # Reaping the leader does not imply that the process group is empty.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def _postflight(directory: Path, task: dict) -> tuple[str, dict]:
    out = directory / 'outputs'
    needed = ['candidate.json', 'compound-inventory.json', 'self-review.json']
    missing = [name for name in needed if not (out / name).is_file()]
    if missing:
        return 'partial', {'missing_outputs': missing}
    raw = _regular(out / 'candidate.json').read_bytes()
    candidate = CandidateEnvelope.model_validate_json(raw)
    from app.ai_prefill.assistance_contracts import SourceIdentity
    if (not _same_source(candidate.source, SourceIdentity.model_validate(task['source']))
            or candidate.candidate_id != task['candidate_id']
            or candidate.experiment_id != task['experiment_id']
            or candidate.parent_candidate_id != task['baseline']['candidate_id']
            or candidate.recipe.guide_version != task['guide_version']):
        raise ValueError('Output candidate does not match task/source/parent/recipe identity')
    inventory = CompoundInventory.model_validate_json(_regular(out / 'compound-inventory.json').read_bytes())
    review = SourceSelfReview.model_validate_json(_regular(out / 'self-review.json').read_bytes())
    if task['entry'] == 'selfcheck':
        from app.ai_prefill.assistance_compare import compare_candidates
        parent = CandidateEnvelope.model_validate_json((directory / 'inputs/current-candidate.json').read_bytes())
        _write(directory / 'checks/candidate-diff.json', compare_candidates(parent, candidate))
    report = self_check_candidate(candidate, inventory, candidate_file_bytes=raw, self_review=review)
    _write(directory / 'checks/self-check.json', report)
    return report['status'], {'candidate_file_sha256': _hash(out / 'candidate.json'),
                              'self_check_report': 'checks/self-check.json'}


def run_task(directory: Path, *, timeout_seconds: float = 1800, executable: str = 'dsh',
             lock_root: Path | None = None) -> dict:
    if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 43200:
        raise ValueError('timeout seconds must be between 0 and 43200')
    directory = directory.resolve()
    _verify_bundle(directory)
    task = _json(directory / 'task.json')
    with _writer_lock(task['source']['paper_key'], lock_root) as lock_fd:
        state = _verify_bundle(directory)
        if state['status'] != 'prepared':
            raise ValueError('Task already attempted; inspect status and prepare a new continuation job')
        resolved_executable = shutil.which(executable)
        if not resolved_executable:
            raise ValueError('DeepSeek executable not available')
        env = {k: v for k, v in os.environ.items()
               if not (k.startswith('LEADTRACE_') or k in {'DATABASE_URL', 'PGPASSWORD', 'PGSERVICEFILE'})}
        env['PYTHONPATH'] = str(REPOSITORY) + os.pathsep + str(REPOSITORY / 'leadtrace/backend')
        dsh_home = Path(env.get('DSH_HOME', str(Path.home() / '.dsh'))).resolve()
        # Resolve relative DSH_HOME before changing cwd so launch and inspection agree.
        env['DSH_HOME'] = str(dsh_home)
        prior_sessions = []
        try:
            from leadtrace.ops.ai_prefill.harness_sessions import find_sessions_for_cwd
            prior_sessions = [s['session_id'] for s in find_sessions_for_cwd(directory, dsh_home)]
        except Exception:
            pass
        state.update(status='running', started_at_utc=_now(), updated_at_utc=_now(),
                     timeout_seconds=timeout_seconds, executable=resolved_executable,
                     harness_profile='headless', process_id=None,
                     lock_root=str(_lock_directory(lock_root)),
                     dsh_home=str(dsh_home), prior_session_ids=prior_sessions)
        _write(directory / 'state.json', state)
        process = None
        try:
            with (directory / 'stdout.log').open('xb') as stdout, (directory / 'stderr.log').open('xb') as stderr:
                os.chmod(stdout.name, 0o600); os.chmod(stderr.name, 0o600)
                process = subprocess.Popen([resolved_executable, '--profile', 'headless',
                                            (directory / 'prompt.md').read_text()],
                                           cwd=directory, env=env, stdout=stdout, stderr=stderr,
                                           start_new_session=True, pass_fds=(lock_fd,))
                state['process_id'] = process.pid
                state['process_identity'] = _process_identity(process.pid)
                _write(directory / 'process.json', {'cwd': str(directory), 'pid': process.pid,
                       'started_at_utc': state['started_at_utc'], 'timeout_seconds': timeout_seconds,
                       'profile': 'headless', 'executable': resolved_executable,
                       'process_identity': state['process_identity']})
                _write(directory / 'state.json', state)
                try:
                    process.wait(timeout=timeout_seconds)
                    state['status'] = 'failed' if process.returncode else 'checking'
                except subprocess.TimeoutExpired:
                    state['status'] = 'timed_out'
                    _terminate_owned_group(process)
                else:
                    # No background writers may outlive a one-shot producer job.
                    _terminate_owned_group(process)
            state['exit_code'] = process.returncode
            if state['status'] == 'checking':
                _verify_bundle(directory)
                state['status'], details = _postflight(directory, task)
                state.update(details)
        except (Exception, KeyboardInterrupt):
            if process and process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            state.update(status='failed', exit_code=process.returncode if process else None,
                         failure='Launch, frozen-input or output validation failed; inspect artifacts, not reasoning logs.')
        finally:
            state.update(finished_at_utc=_now(), updated_at_utc=_now())
            try:
                from leadtrace.ops.ai_prefill.harness_sessions import find_sessions_for_cwd
                sessions = find_sessions_for_cwd(directory, Path(state['dsh_home']))
                _write(directory / 'sessions.json', {'sessions': sessions,
                       'native_resume_supported': False, 'cost': None})
                new_sessions = [s for s in sessions if s['session_id'] not in prior_sessions]
                state['producer_session_ids'] = [s['session_id'] for s in new_sessions]
                if len(new_sessions) != 1:
                    state['session_binding'] = 'unknown' if not new_sessions else 'ambiguous'
                else:
                    state['session_binding'] = 'new_exact_cwd_match'
            except Exception:
                state['session_binding'] = 'metadata_unavailable'
            _write(directory / 'state.json', state)
            process_path = directory / 'process.json'
            if process_path.exists():
                record = _json(process_path)
                record.update(exit_code=state.get('exit_code'), finished_at_utc=state['finished_at_utc'])
                _write(process_path, record)
    return task_status(directory)
