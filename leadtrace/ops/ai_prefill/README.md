# AI Prefill Operator CLI

New conversations and run recovery: [START_HERE](../../../docs/ai-prefill/START_HERE.md).

Run the commands from the repository root with the backend virtualenv:

```bash
cd /data/home/zhangzhiyong/lead_optimization_collection/.worktrees/ai-prefill-tools
.venv/bin/python -m leadtrace.ops.ai_prefill doctor
```

The CLI is offline by default. `doctor`, `contract export`, `input prepare`,
candidate validation, comparison, evaluation summaries, and explicit-payload
`candidate export` do not connect to PostgreSQL or Redis.

For model-led routine work or supervised evaluation, use the
[operating runbook](../../../docs/ai-prefill/model-runbook.md),
[quality checklist](../../../docs/ai-prefill/quality-checklist.md), and
[task/revision prompts](../../../docs/ai-prefill/prompts/producer.md).
They define prefill, selfcheck and review task entries, scientific checks, bounded revisions, fresh independent
review and trusted-operator Preview delivery. The CLI runs a bounded producer job;
it does not schedule independent audits, approve science, provide a durable queue,
or automatically apply a job's output.

## Prepare, run and continue a producer task

Use an existing formal input package whose source locator is an absolute local
path. Supply the current exported candidate and source inventory for repairs:

```bash
.venv/bin/python -m leadtrace.ops.ai_prefill task prefill \
  --input /absolute/input.json --output /absolute/new-job --mode routine
.venv/bin/python -m leadtrace.ops.ai_prefill task selfcheck \
  --input /absolute/input.json --candidate /absolute/current.json \
  --inventory /absolute/inventory.json --feedback /absolute/feedback.json \
  --previous-task /absolute/old-job --output /absolute/new-repair
.venv/bin/python -m leadtrace.ops.ai_prefill task run /absolute/new-job --timeout-seconds 1800
.venv/bin/python -m leadtrace.ops.ai_prefill task status /absolute/new-job
.venv/bin/python -m leadtrace.ops.ai_prefill session inspect \
  --run-dir /absolute/new-job --dsh-home /absolute/dsh-home --output /absolute/new-session-report.json
```

Preparation checks actual source bytes/hash and candidate/inventory identity,
copies current guides and source into a new directory outside the checkout, and
freezes a hash manifest. It does not verify the external catalog or PDF semantics.
`--feedback`, `--previous-task` and `--handoff` are optional. For an existing
workspace, selfcheck accepts `--workspace-id UUID --workspace-version N` together;
they record the supplied baseline, not a live database check. Export current human
edits before preparing and check the version again before any authorized delivery.

`task run` explicitly invokes `dsh --profile headless`. It uses a per-paper local
writer lock, records process identity, enforces wall time, terminates its process
group at completion, and validates output identity plus producer self-check.
Repairs also produce `checks/candidate-diff.json` against the frozen current
candidate so unexpected changes can be reviewed before delivery.
Exit 0 means ready for independent review; exit 4 includes partial, failed,
timed-out or needs-revision results. Every job can be attempted only once. Inspect
existing outputs and prepare a new job to continue; never overwrite a frozen job.
After a supervisor crash, `task recover DIR` can close a stale running checkpoint
only when its writer lock is free and its original process session is inactive.
It preserves artifacts and never launches or kills a model.

Use the same `LEADTRACE_PREFILL_LOCK_ROOT` for all operators (default
`~/.local/state/leadtrace/ai-prefill/locks`). Locks are local cooperation, not a
sandbox or distributed scheduler. The runner strips LeadTrace/database environment
settings, but the harness still has its host user's filesystem/tool privileges;
do not expose this CLI as an untrusted web endpoint.

Current headless has no native resume flag. Continuations start a new session
using structured handoff, while previous session IDs remain provenance.
`session inspect` exports exact-cwd identity and provider-reported cache usage
only; it does not read transcripts. Missing usage is null, seeded/inherited
sessions are excluded from totals, and cache checkpoints are not complete bills.
Runtime inspection uses the actual `DSH_HOME`. No token/monetary hard cap, native
session bridge or reviewer web chat is implemented.

Prepare an input package without publishing a local filesystem path into the
candidate contract:

```bash
.venv/bin/python -m leadtrace.ops.ai_prefill input prepare \
  --experiment-id experiment:pilot \
  --paper-key LT-JMC-2024-67-05-AI1 \
  --source-sha256 <64-lowercase-hex> \
  --byte-size 12345 \
  --page-count 12 \
  --guide-version model-neutral-v4-20261008 \
  --source-path /absolute/source.pdf \
  --output /tmp/prefill-input.json
```

Validate and store a candidate in a managed artifact root:

```bash
.venv/bin/python -m leadtrace.ops.ai_prefill candidate validate candidate.json
.venv/bin/python -m leadtrace.ops.ai_prefill candidate import candidate.json \
  --artifact-root /var/lib/leadtrace/preview-artifacts
```

`needs_review` exits successfully and remains previewable. Technical errors
return a nonzero validation result. Candidate hashes are recalculated by the
receiver.

Check compound coverage independently of technical validation:

```bash
.venv/bin/python -m leadtrace.ops.ai_prefill candidate coverage candidate.json \
  --inventory compound-inventory.json
```

Use a source-based inventory checked by a fresh scientific reader, not a list derived from the
candidate itself. A historical, explicitly table-scoped regression example is
[PfPKG 004 Tables 1–5](../../../docs/ai-prefill/examples/compound-inventory-pfpkg-004.json).
The old candidate had 11 compounds but only 6 of the 39 required assayed labels;
the command reports the 33 missing labels and exits 4. Missing labels cannot be
satisfied by omission notes. Exact labels or explicit unambiguous aliases match;
prefix matching never merges stereoisomers. Exclusions require a reason and are
visible in the report. Source identity mismatch or an invalid inventory exits 2.
Success means `complete_for_declared_scope`, not complete science or verified
structure identity. The report binds canonical candidate and inventory hashes.
Always show `all_inventory_coverage` alongside the required-scope counts: it
reports the total, uniquely matched count, missing labels and ambiguous matches
for every inventory entry, including exclusions. Extra candidate labels never
increase that coverage. Status and exit codes still reflect required entries;
neither denominator certifies an exhaustive source census. Under the current
guides, all source-identifiable numbered/labelled structures (including precursors
without Activity and Methods-only intermediates) and named/lettered controls
belong in the catalogue. Only explicit user scope limits justify excluding an
otherwise eligible identity; unresolved structures remain required. Review all
exclusions rather than accepting a narrowed 100% as paper completeness.
This command does not write to a database or automatically guard the apply API.

Compare two candidates or explicitly export a human-assisted child:

```bash
.venv/bin/python -m leadtrace.ops.ai_prefill candidate compare v1.json v2.json
.venv/bin/python -m leadtrace.ops.ai_prefill candidate export v1.json \
  --payload edited-payload.json \
  --output v2.json \
  --candidate-id candidate:v2 \
  --evaluation-id evaluation:1 \
  --reviewer reviewer@example.test
```

Preview application is exposed through the Preview-only HTTP API under
`/api/v2/admin/ai-prefill`. It requires an authenticated Admin session and
CSRF token. Production does not register these routes.

Native Preview now supports `preview create`, `start`, `status` and `stop`.
Creation needs an explicit protected provisioning profile for a separate cluster;
it creates a fresh restricted runtime role, imports 20 PDFs and seeds two accounts.
See the [native runbook](../runbooks/ai_prefill_preview.md) for executable steps and
credential handling. This path serves the built frontend and backend on one
loopback origin; start at `/review/tasks`. `evaluation record` and
`candidate export-workspace` read an explicitly identified Preview database and
bind feedback to its actual Workspace snapshot. They do not change scientific rows.

Preview inspection, archive and cleanup are explicit and instance-scoped:

```bash
.venv/bin/python -m leadtrace.ops.ai_prefill preview plan \
  --profile /absolute/instance/runtime.json
.venv/bin/python -m leadtrace.ops.ai_prefill preview archive \
  --profile /absolute/instance/runtime.json --archive-root /absolute/archives
.venv/bin/python -m leadtrace.ops.ai_prefill preview destroy \
  --profile /absolute/instance/runtime.json \
  --provisioning-profile /absolute/provisioning.json \
  --confirm-instance EXACT_INSTANCE_UUID
```

The native archive includes a consistent restorable database dump, PDFs, assets,
experiments and complete file hashes. Destroy verifies archived state and deletes
only the matching database/role and copied source/assets; experiment artifacts are
retained. See the runbook for feedback/export commands, recovery and limitations.
The Compose file is an unsupported scaffold; use native provisioning.

## Producer delivery self-check

Use [the source self-check guide](../../../docs/ai-prefill/self-check-guide.md) after extraction:

```bash
.venv/bin/python -m leadtrace.ops.ai_prefill candidate self-check candidate.json \
  --inventory compound-inventory.json --self-review self-review.json \
  --output self-check.json
```

This is offline and does not repair, apply, or approve a candidate. Missing self-review is allowed for preflight but exits4. Exit0 means ready for independent review, exit4 means correction/incomplete review, exit2 means invalid input. The command checks narrow semantic rules and the self-review declaration; it cannot verify original source diagrams or whole-paper measurement completeness. Preview API behavior is unchanged.

`lineage_diagnostics` reports connected components, isolated members, directed
cycles, synthesis topology/role conflicts, and each compound's SAR/synthesis
participation. These are review notices, not automatic scientific errors; the
tool does not add edges, split groups, infer SAR roles or select paper leads.

Candidate entity refs must not contain `/`, which is reserved by receipt paths. Labels and scientific names may contain it; this restriction only applies to internal refs. `candidate export` requires a new output path and never overwrites parent or existing candidates.
