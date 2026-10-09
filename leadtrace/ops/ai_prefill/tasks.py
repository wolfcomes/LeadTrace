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
import time
from typing import Callable
from uuid import UUID, uuid4

from app.ai_prefill.assistance_contracts import CandidateEnvelope, validate_declared_hashes
from app.ai_prefill.assistance_coverage import CompoundInventory
from app.ai_prefill.assistance_inputs import PrefillInputPackage
from app.ai_prefill.assistance_self_check import SourceSelfReview, self_check_candidate


GUIDE_VERSION = 'model-neutral-v4-20261008'
REPOSITORY = Path(__file__).resolve().parents[3]
GUIDES = (
    'START_HERE.md', 'extraction-guide.md', 'model-runbook.md',
    'self-check-guide.md', 'quality-checklist.md',
    'quality-audit-protocol.md', 'quality-pitfalls.md',
    'prompts/producer.md', 'prompts/repair.md', 'prompts/review.md',
    'templates/quality-record.json', 'templates/self-review.json',
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
    if entry == 'review':
        return _review_prompt(task)
    repair = entry == 'selfcheck'
    read = ['bundle/extraction-guide.md', 'bundle/self-check-guide.md']
    read.append('bundle/prompts/repair.md' if repair else 'bundle/prompts/producer.md')
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
    return f'''You are the sole scientific producer for this frozen LeadTrace task.
Scientific Python: {task['runtime']['python_executable']}; use it for RDKit/PyMuPDF and final structure depictions. Its bin directory is first on PATH.
Read task.json and inputs/input.json first, then {', '.join(read)}.
Read inputs/handoff.json and inputs/previous-task.json when present; verify their
paper/source/parent identity against task.json before using previous conclusions.
Read bundle/quality-checklist.md at delivery. The full current bundle is frozen;
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
with honest unresolved findings at the time budget. A fresh independent model review
is a separate step; this producer must never assert independent or human approval.
'''


def _review_prompt(task: dict) -> str:
    repair = task.get('review_with_repair', False)
    boundary = ('Do not edit the frozen baseline. After saving the independent baseline audit, '
                'prepare supported corrections as a separate output in this SAME session.' if repair else
                'Do not repair or edit the candidate. This task is audit-only.')
    proposal = f"""
This is ONE independent review task including a repair proposal, not a second model call.
First finish and save the baseline audit without revising its original verdicts to match your repairs.
Then read bundle/prompts/repair.md and bundle/self-check-guide.md; reuse your source checks.
Repair only supported findings and affected dependencies. Preserve stable refs, unchanged
human edits and relative order; do not delete uncertain items to improve statistics.
Write a complete revised CandidateEnvelope.v1 to outputs/candidate.json, updated inventory
to outputs/compound-inventory.json and honest seven-check producer_self_check to outputs/self-review.json.
Use candidate_id={task['candidate_id']}, experiment_id={task['experiment_id']},
parent_candidate_id={task['baseline']['candidate_id']}, guide_version={task['guide_version']}.
Do not copy stale declared hashes. Bind self-review to the revised candidate FILE SHA256.
Include every payload collection (even empty lists) and every lineage's members/edges;
omitting populated collections is not an instruction to delete them. At most two internal
correction cycles, within this task's original time budget; save audit artifacts early.
Run candidate validate, coverage and self-check as documented in bundle/self-check-guide.md.
If no supported changes are needed or possible, omit candidate.json and save
outputs/repair-outcome.json as {{"status":"no_changes","reason":"specific explanation"}}.
Retain unresolved findings; no_changes does not mean the baseline is correct.
If repair cannot finish, preserve the audit and record limitations in outputs/handoff.json.
The baseline audit statistics describe ONLY the original frozen candidate. Your revised
candidate receives a same-session self-check, NOT another independent review. Do not
claim scientific approval or overwrite the baseline audit. The Admin sees the proposal
and explicitly accepts saved changes later; acceptance makes no model call.
""" if repair else ''
    return f"""You are a fresh independent scientific reviewer for this frozen LeadTrace task.
Read task.json, inputs/input.json, bundle/quality-audit-protocol.md,
bundle/prompts/review.md and relevant bundle/extraction-guide.md sections.
Authorized source: inputs/source.pdf. Verify title/DOI/source identity. Before reading
producer assertions, establish source expectations, then compare the actual parsed
final structures and their depictions, every variant, saved crop, Activity and Edge.
Scientific Python: {task['runtime']['python_executable']}; use it for RDKit and PyMuPDF.
Its bin directory is first on PATH. Do not substitute system Python silently.
Read inputs/current-candidate.json and inputs/compound-inventory.json as assertions,
not ground truth. A successful parse or formula match cannot certify identity.
{boundary} No other task directories, credentials, databases,
Preview access, external messages, subagents or extra model calls. Work only within
this task; frozen inputs/bundle are read-only. Keep raw source extracts in work/.
Save source expectations and per-record structures, locators, activities, edges,
groups, participation and omissions reviews as derived JSON under outputs/.
Each verdict has domain/ref from inputs/review-targets.json (activities and links use zero-based index strings),
expected/observed, nonempty source_locations, checked_fields, field_results,
reason, and correct/incorrect/uncertain; list every unreviewed ref and propagate
identity uncertainty to dependent Activity/Edge claims. Every frozen target requires a row;
missing domains/refs become partial, and unknown/duplicate refs are rejected. Inventory rows
assess coverage/exclusions including missing identities, not merely candidate presence. Read producer claims only
after independent judgments. Return honest partial coverage if tools/time insufficient.
Save outputs/audit-summary.json with candidate_file_sha256=
{task['baseline']['candidate_file_sha256']}, source_sha256={task['source']['source_sha256']},
complete_scope:boolean, unreviewed_scope:list, domain_results, findings,
item_reports:list of relative JSON paths under outputs/ (each a list of item verdicts with ref) and
scientific_approval:false. Preserve detailed per-item reports; a row count is not
proof all fields were checked. Report tool failures rather than claiming verification.
{proposal}"""


def prepare_task(*, entry: str, input_path: Path, output: Path, mode: str = 'routine',
                 candidate_path: Path | None = None, inventory_path: Path | None = None,
                 feedback_path: Path | None = None, previous_task: Path | None = None,
                 handoff_path: Path | None = None, workspace_id: str | None = None,
                 workspace_version: int | None = None, adapter: str = 'dsh',
                 model: str | None = None, reasoning_effort: str | None = None,
                 python_executable: str | None = None, review_with_repair: bool = False) -> dict:
    if entry not in {'prefill', 'selfcheck', 'review'} or mode not in {'routine', 'evaluation'}:
        raise ValueError('Unknown task entry or mode')
    if review_with_repair and entry != 'review':
        raise ValueError('review_with_repair requires a review task')
    from leadtrace.ops.ai_prefill.runtime import RuntimeConfig
    runtime = RuntimeConfig(adapter=adapter, model=model, reasoning_effort=reasoning_effort,
                            python_executable=python_executable or sys.executable)
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
    if entry in {'selfcheck', 'review'} and (candidate_path is None or inventory_path is None):
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
            'review_with_repair': bool(review_with_repair),
            'source': package.target.model_dump(mode='json'), 'experiment_id': package.experiment_id,
            'candidate_id': 'candidate-' + uuid4().hex, 'baseline': baseline, 'continuation': continuation,
            'permissions': {'preview_apply': False, 'scientific_approval': False},
            'budget': {'max_producer_correction_cycles': 2, 'token_cap_enforced': False},
            'repository_checkout': str(REPOSITORY), 'runtime': runtime.model_dump()}
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
        if entry == 'review':
            from leadtrace.ops.ai_prefill.review_coverage import review_targets
            candidate = CandidateEnvelope.model_validate_json((temporary / 'inputs/current-candidate.json').read_bytes())
            inventory = CompoundInventory.model_validate_json((temporary / 'inputs/compound-inventory.json').read_bytes())
            _write(temporary / 'inputs/review-targets.json', review_targets(candidate, inventory))
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
        if state.get('sandbox_home'):
            from leadtrace.ops.ai_prefill.sandbox import require_sandbox_cleanup
            require_sandbox_cleanup({'LEADTRACE_SANDBOX_HOME':state['sandbox_home']},expected_job_directory=state.get('sandbox_job_directory',directory),supervisor_identity=state.get('process_identity'))
        state.update(status='interrupted', recovered_at_utc=_now(), updated_at_utc=_now(),
                     recovery='Writer lock free and no active original process session; artifacts preserved')
        _write(directory / 'state.json', state)
    return task_status(directory)


def _active_session_processes(state: dict) -> list[dict]:
    """Identify a saved session without ever trusting a reusable PID alone."""
    pid = state.get('process_id')
    recorded = state.get('process_identity')
    if not pid:
        if recorded:
            raise ValueError('Process identity is incomplete; cleanup cannot be confirmed')
        return []
    if not recorded or recorded.get('pid') != pid:
        raise ValueError('Process identity is missing; cleanup cannot be confirmed')
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if recorded.get('boot_id') != boot:
        # No process from a prior boot can still be executing.
        return []
    if not isinstance(recorded.get('start_ticks'), int):
        raise ValueError('Process identity start time is missing')
    current = _process_identity(pid)
    if current and current != recorded:
        raise ValueError('Process identity changed; refusing to signal a reused PID')
    if recorded.get('session') != pid or recorded.get('process_group') != pid:
        # Scientific runners always start_new_session. Reject arbitrary input.
        raise ValueError('Process identity is not an owned scientific session')
    members = []
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        identity = _process_identity(int(path.name))
        if not identity or identity['session'] != pid:
            continue
        if identity['start_ticks'] < recorded['start_ticks']:
            raise ValueError('Process session identity is ambiguous')
        try:
            status = (path / 'stat').read_text().rsplit(')', 1)[1].split()[0]
        except FileNotFoundError:
            continue
        if status not in {'Z', 'X'}:
            members.append(identity)
    return members


def _signal_identity(identity: dict, sig: int) -> None:
    """Use a pidfd so an exiting process cannot redirect a signal to a reused PID."""
    try:
        from app.ai_prefill.preview_process import _pidfd_open
        fd = _pidfd_open(identity['pid'])
    except ProcessLookupError:
        return
    try:
        if _process_identity(identity['pid']) != identity:
            raise ValueError('Process identity changed before signal')
        from app.ai_prefill.preview_process import _pidfd_send_signal
        _pidfd_send_signal(fd, sig)
    except ProcessLookupError:
        pass
    finally:
        os.close(fd)


def stop_task_processes(state: dict, *, grace_seconds: float = 2) -> None:
    """Stop only a verified owned session, including children in other groups.

    Returning confirms no live session members remain. An ambiguous identity or
    an unkillable process raises; callers must keep the capacity slot reserved.
    """
    members = _active_session_processes(state)
    for identity in members:
        _signal_identity(identity, signal.SIGTERM)
    deadline = time.monotonic() + grace_seconds
    while members and time.monotonic() < deadline:
        time.sleep(0.02)
        members = _active_session_processes(state)
    deadline = time.monotonic() + 2
    while members:
        for identity in members:
            _signal_identity(identity, signal.SIGKILL)
        time.sleep(0.02)
        members = _active_session_processes(state)
        if members and time.monotonic() >= deadline:
            raise ValueError('Task process session is still active; capacity must be retained')


def _terminate_owned_group(process, identity=None):
    """Reap the leader only after all verified session members have stopped."""
    stop_task_processes({'process_id': process.pid,
                         'process_identity': identity or _process_identity(process.pid)})
    process.wait(timeout=2)


def _postflight(directory: Path, task: dict) -> tuple[str, dict]:
    out = directory / 'outputs'
    if task['entry'] == 'review':
        path = out / 'audit-summary.json'
        if not path.is_file():
            return 'partial', {'missing_outputs': ['audit-summary.json']}
        report = _json(_regular(path))
        if report.get('candidate_file_sha256') != task['baseline']['candidate_file_sha256'] or report.get('source_sha256') != task['source']['source_sha256']:
            raise ValueError('Review output is not bound to the frozen candidate/source')
        if report.get('scientific_approval') is not False or not isinstance(report.get('unreviewed_scope'), list):
            raise ValueError('Review must preserve approval and scope boundaries')
        from leadtrace.ops.ai_prefill.review_coverage import review_targets, check_review_rows
        candidate = CandidateEnvelope.model_validate_json((directory / 'inputs/current-candidate.json').read_bytes())
        inventory = CompoundInventory.model_validate_json((directory / 'inputs/compound-inventory.json').read_bytes())
        rows = []
        reports = report.get('item_reports', [])
        if not isinstance(reports, list):
            raise ValueError('item_reports must list relative JSON paths')
        for name in reports:
            from leadtrace.ops.ai_prefill.review_coverage import review_report_name
            path = out / review_report_name(name)
            if not path.resolve().is_relative_to(out.resolve()):
                raise ValueError('Invalid item report path')
            items = _json(_regular(path))
            if not isinstance(items, list):
                raise ValueError('Item report must contain detailed rows')
            rows.extend(items)
        coverage = check_review_rows(review_targets(candidate, inventory), rows)
        _write(directory / 'checks/review-coverage.json', coverage)
        complete = report.get('complete_scope') is True and not report['unreviewed_scope'] and not coverage['missing']
        details = {
            'audit_summary': 'outputs/audit-summary.json', 'complete_scope': complete,
            'review_coverage': 'checks/review-coverage.json', 'missing_review_targets': coverage['missing']}
        if task.get('review_with_repair'):
            proposal = _review_repair_postflight(directory, task, candidate)
            details.update(proposal)
            if proposal['repair_proposal_status'] == 'unavailable':
                complete = False
        return ('review_complete' if complete else 'partial'), details
    needed = ['candidate.json', 'compound-inventory.json', 'self-review.json']
    missing = [name for name in needed if not (out / name).is_file()]
    if 'candidate.json' in missing:
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
    if missing:
        return 'partial', {'missing_outputs': missing, 'candidate_file_sha256': _hash(out / 'candidate.json')}
    try:
        inventory = CompoundInventory.model_validate_json(_regular(out / 'compound-inventory.json').read_bytes())
        review = SourceSelfReview.model_validate_json(_regular(out / 'self-review.json').read_bytes())
    except (ValueError, OSError):
        return 'partial', {'diagnostics_unavailable': True, 'candidate_file_sha256': _hash(out / 'candidate.json')}
    if task['entry'] == 'selfcheck':
        from app.ai_prefill.assistance_compare import compare_candidates
        parent = CandidateEnvelope.model_validate_json((directory / 'inputs/current-candidate.json').read_bytes())
        _write(directory / 'checks/candidate-diff.json', compare_candidates(parent, candidate))
    try:
        report = self_check_candidate(candidate, inventory, candidate_file_bytes=raw, self_review=review)
    except ValueError:
        return 'partial', {'diagnostics_unavailable': True, 'candidate_file_sha256': _hash(out / 'candidate.json')}
    _write(directory / 'checks/self-check.json', report)
    return report['status'], {'candidate_file_sha256': _hash(out / 'candidate.json'),
                              'self_check_report': 'checks/self-check.json'}


def _review_repair_postflight(directory: Path, task: dict, baseline: CandidateEnvelope) -> dict:
    """Keep a valid independent audit when its same-session proposal is unfinished."""
    out = directory / 'outputs'
    unavailable = {'repair_proposal_status': 'unavailable'}
    try:
        if not (out / 'candidate.json').exists():
            outcome = _json(_regular(out / 'repair-outcome.json'))
            if (outcome.get('status') != 'no_changes' or not isinstance(outcome.get('reason'), str)
                    or not outcome['reason'].strip()):
                raise ValueError('No-change outcome requires an explicit reason')
            return {'repair_proposal_status': 'no_changes', 'repair_proposal_reason': outcome['reason']}
        # Reuse producer validation and deterministic checks; this does not call a model.
        status, details = _postflight(directory, {**task, 'entry': 'selfcheck'})
        candidate = CandidateEnvelope.model_validate_json(_regular(out / 'candidate.json').read_bytes())
        validate_declared_hashes(candidate)
        from app.ai_prefill.assistance_validation import validate_candidate
        if any(issue.severity == 'error' for issue in validate_candidate(candidate).issues):
            raise ValueError('Revised candidate failed technical validation')
        if not details.get('self_check_report'):
            return {**unavailable, 'repair_proposal_errors': ['Revised candidate self-check or inventory is missing or invalid']}
        return {**details, 'repair_proposal_status': ('no_changes' if candidate.payload == baseline.payload else 'ready'),
                'repair_self_check_status': status}
    except (ValueError, OSError, TypeError, AttributeError):
        # Detailed malformed outputs stay in the task; never discard the valid baseline audit.
        return {**unavailable, 'repair_proposal_errors': ['Repair proposal is missing or does not match the frozen task contract']}


def run_task(directory: Path, *, timeout_seconds: float = 1800, executable: str | None = None,
             lock_root: Path | None = None, should_cancel: Callable[[], bool] | None = None,
             heartbeat: Callable[[], None] | None = None, sandboxed: bool = False) -> dict:
    if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 43200:
        raise ValueError('timeout seconds must be between 0 and 43200')
    directory = directory.resolve()
    _verify_bundle(directory)
    task = _json(directory / 'task.json')
    with _writer_lock(task['source']['paper_key'], lock_root) as lock_fd:
        state = _verify_bundle(directory)
        if state['status'] != 'prepared':
            raise ValueError('Task already attempted; inspect status and prepare a new continuation job')
        from leadtrace.ops.ai_prefill.runtime import RuntimeConfig, build_command, tool_preflight, runtime_environment, observed_runtime
        runtime = RuntimeConfig.model_validate(task.get('runtime', {}))
        resolved_executable = shutil.which(executable or runtime.adapter)
        if not resolved_executable:
            raise ValueError('Configured model executable not available')
        env = {k: v for k, v in os.environ.items()
               if not (k.startswith('LEADTRACE_') or k in {'DATABASE_URL', 'PGPASSWORD', 'PGSERVICEFILE'})}
        tools = tool_preflight(runtime.python_executable)
        _write(directory / 'tool-preflight.json', tools)
        if sandboxed and runtime.adapter == 'codex':
            from leadtrace.ops.ai_prefill.tool_execution_preflight import codex_execution_preflight, ToolExecutionUnavailable, ToolExecutionCleanupPending
            try:
                report = codex_execution_preflight(resolved_executable, runtime.python_executable, env)
            except ToolExecutionCleanupPending as error:
                state.update(error.process_state)
                state.update(status='cleanup_pending', failure_code='TOOL_EXECUTION_CLEANUP_PENDING',
                             process_cleanup_confirmed=False,finished_at_utc=_now(),updated_at_utc=_now())
                _write(directory / 'state.json',state)
                _write(directory / 'execution-preflight.json', {'status':'failed','error_code':'TOOL_EXECUTION_CLEANUP_PENDING','model_calls':0})
                raise
            except ToolExecutionUnavailable:
                _write(directory / 'execution-preflight.json', {'status':'failed','error_code':'TOOL_EXECUTION_UNAVAILABLE','model_calls':0})
                state.update(status='failed', failure_code='TOOL_EXECUTION_UNAVAILABLE', process_cleanup_confirmed=True,
                             finished_at_utc=_now(), updated_at_utc=_now())
                _write(directory / 'state.json', state)
                raise
            _write(directory / 'execution-preflight.json', {'status':'passed', **report})
        env = runtime_environment(runtime, env)
        env['PYTHONPATH'] = str(REPOSITORY) + os.pathsep + str(REPOSITORY / 'leadtrace/backend')
        dsh_home = Path(env.get('DSH_HOME', str(Path.home() / '.dsh'))).resolve()
        # Resolve relative DSH_HOME before changing cwd so launch and inspection agree.
        env['DSH_HOME'] = str(dsh_home)
        prior_sessions = []
        try:
            if runtime.adapter != 'dsh': raise ValueError('No dsh session for this adapter')
            from leadtrace.ops.ai_prefill.harness_sessions import find_sessions_for_cwd
            prior_sessions = [s['session_id'] for s in find_sessions_for_cwd(directory, dsh_home)]
        except Exception:
            pass
        state.update(status='running', started_at_utc=_now(), updated_at_utc=_now(),
                     timeout_seconds=timeout_seconds, executable=resolved_executable,
                     harness_profile='headless' if runtime.adapter == 'dsh' else ('app-server-external' if sandboxed else 'exec'), process_id=None,
                     lock_root=str(_lock_directory(lock_root)),
                     dsh_home=str(dsh_home), prior_session_ids=prior_sessions, process_cleanup_confirmed=False)
        _write(directory / 'state.json', state)
        process = None
        try:
            with (directory / 'stdout.log').open('xb') as stdout, (directory / 'stderr.log').open('xb') as stderr:
                os.chmod(stdout.name, 0o600); os.chmod(stderr.name, 0o600)
                command = build_command(runtime, directory, resolved_executable,
                                        (directory / 'prompt.md').read_text())
                if sandboxed:
                    from leadtrace.ops.ai_prefill.sandbox import sandbox_command
                    command, env = sandbox_command(command, env, job_directory=directory,
                        python_executable=runtime.python_executable, adapter=runtime.adapter)
                    state['sandbox_home'] = env['LEADTRACE_SANDBOX_HOME']
                    state['dsh_home'] = env.get('DSH_HOME', state['dsh_home'])
                    prior_sessions = []
                    state['prior_session_ids'] = []
                    _write(directory / 'state.json', state)
                process = subprocess.Popen(command,
                                           cwd=directory, env=env, stdout=stdout, stderr=stderr,
                                           start_new_session=True, pass_fds=(lock_fd,))
                state['process_id'] = process.pid
                state['process_identity'] = _process_identity(process.pid)
                _write(directory / 'process.json', {'cwd': str(directory), 'pid': process.pid,
                       'started_at_utc': state['started_at_utc'], 'timeout_seconds': timeout_seconds,
                       'adapter': runtime.adapter, 'profile': state['harness_profile'], 'executable': resolved_executable,
                       'process_identity': state['process_identity'], 'sandbox_home': state.get('sandbox_home')})
                _write(directory / 'state.json', state)
                deadline = time.monotonic() + timeout_seconds
                while process.poll() is None:
                    if heartbeat is not None:
                        heartbeat()
                    if should_cancel is not None and should_cancel():
                        state['status'] = 'cancelled'
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        state['status'] = 'timed_out'
                        break
                    try:
                        process.wait(timeout=min(1.0, remaining))
                    except subprocess.TimeoutExpired:
                        continue
                if state['status'] == 'running':
                    state['status'] = 'failed' if process.returncode else 'checking'
                # Reap the whole owned process group before completion/capacity release.
                _terminate_owned_group(process, state.get('process_identity'))
                if sandboxed:
                    from leadtrace.ops.ai_prefill.sandbox import require_sandbox_cleanup
                    require_sandbox_cleanup(env,expected_job_directory=state.get('sandbox_job_directory',directory),supervisor_identity=state.get('process_identity'))
                state['process_cleanup_confirmed'] = True
            state['exit_code'] = process.returncode
            if state['status'] == 'checking':
                _verify_bundle(directory)
                state['status'], details = _postflight(directory, task)
                state.update(details)
        except (Exception, KeyboardInterrupt):
            cleanup_confirmed = process is None
            if process is not None:
                try:
                    # A reaped leader can leave active children; always clean up.
                    _terminate_owned_group(process, state.get('process_identity'))
                    if sandboxed:
                        from leadtrace.ops.ai_prefill.sandbox import require_sandbox_cleanup
                        require_sandbox_cleanup(env,expected_job_directory=state.get('sandbox_job_directory',directory),supervisor_identity=state.get('process_identity'))
                    cleanup_confirmed = True
                except (ValueError, OSError, subprocess.TimeoutExpired):
                    cleanup_confirmed = False
            state.update(status='failed' if cleanup_confirmed else 'cleanup_pending',
                         process_cleanup_confirmed=cleanup_confirmed,
                         exit_code=process.returncode if process else None,
                         failure='Launch, frozen-input or output validation failed; inspect artifacts, not reasoning logs.')
        finally:
            state.update(finished_at_utc=_now(), updated_at_utc=_now())
            try:
                if runtime.adapter != 'dsh': raise ValueError('Session metadata unavailable for this adapter')
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
            if sandboxed and state.get('process_cleanup_confirmed'):
                from leadtrace.ops.ai_prefill.sandbox import cleanup_sandbox
                cleanup_sandbox(env, expected_job_directory=directory)
            observation = observed_runtime(directory, runtime)
            if observation['verification'] == 'mismatch' and state.get('process_cleanup_confirmed'):
                state['output_status'] = state['status']
                state['status'] = 'configuration_mismatch'
            _write(directory / 'runtime-provenance.json', {**observation,
                'stage': task['entry'], 'task_id': task['task_id'], 'source_sha256': task['source']['source_sha256'],
                'candidate_file_sha256': (task['baseline'].get('candidate_file_sha256') if task['entry'] == 'review'
                    else state.get('candidate_file_sha256') or task['baseline'].get('candidate_file_sha256')),
                **({'proposal_candidate_file_sha256': state.get('candidate_file_sha256')}
                   if task.get('review_with_repair') else {}),
                'guide_version': task['guide_version'], 'guide_bundle_sha256': state['bundle_manifest_sha256'],
                'started_at': state['started_at_utc'], 'completed_at': state['finished_at_utc'],
                'outcome': state['status']})
            _write(directory / 'state.json', state)
            process_path = directory / 'process.json'
            if process_path.exists():
                record = _json(process_path)
                record.update(exit_code=state.get('exit_code'), finished_at_utc=state['finished_at_utc'])
                _write(process_path, record)
    return task_status(directory)
