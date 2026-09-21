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

For multi-paper DeepSeek extraction, use the
[supervised runbook](../../../docs/ai-prefill/deepseek-supervised-runbook.md),
[quality checklist](../../../docs/ai-prefill/deepseek-quality-checklist.md), and
[task/revision prompts](../../../docs/ai-prefill/prompts/deepseek-task.md).
They document survey checkpoints, scientific checks, bounded revisions and
supervisor-controlled Preview apply. The current CLI provides candidate and
Preview operations; it does not yet provide a durable multi-harness scheduler,
automatic chemical identity verification, or complete usage/cost accounting.

Prepare an input package without publishing a local filesystem path into the
candidate contract:

```bash
.venv/bin/python -m leadtrace.ops.ai_prefill input prepare \
  --experiment-id experiment:pilot \
  --paper-key LT-JMC-2024-67-05-AI1 \
  --source-sha256 <64-lowercase-hex> \
  --byte-size 12345 \
  --page-count 12 \
  --guide-version guide-v1 \
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

Use a source-based, supervisor-reviewed inventory, not a list derived from the
candidate itself. A real scoped example is
[PfPKG 004 Tables 1–5](../../../docs/ai-prefill/examples/compound-inventory-pfpkg-004.json).
The old candidate had 11 compounds but only 6 of the 39 required assayed labels;
the command reports the 33 missing labels and exits 4. Missing labels cannot be
satisfied by omission notes. Exact labels or explicit unambiguous aliases match;
prefix matching never merges stereoisomers. Exclusions require a reason and are
visible in the report. Source identity mismatch or an invalid inventory exits 2.
Success means `complete_for_declared_scope`, not complete science or verified
structure identity. The report binds canonical candidate and inventory hashes.
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

Use [the source self-check guide](../../../docs/ai-prefill/deepseek-self-check-guide.md) after extraction:

```bash
.venv/bin/python -m leadtrace.ops.ai_prefill candidate self-check candidate.json \
  --inventory compound-inventory.json --self-review self-review.json \
  --output self-check.json
```

This is offline and does not repair, apply, or approve a candidate. Missing self-review is allowed for preflight but exits4. Exit0 means ready for independent review, exit4 means correction/incomplete review, exit2 means invalid input. The command checks narrow semantic rules and the self-review declaration; it cannot verify original source diagrams or whole-paper measurement completeness. Preview API behavior is unchanged.

Candidate entity refs must not contain `/`, which is reserved by receipt paths. Labels and scientific names may contain it; this restriction only applies to internal refs. `candidate export` requires a new output path and never overwrites parent or existing candidates.
