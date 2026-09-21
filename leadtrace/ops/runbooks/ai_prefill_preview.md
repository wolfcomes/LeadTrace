# AI Prefill Preview Runbook

This runbook applies only to an isolated Preview instance. Do not point it at
the production database or production asset root.

## Native Preview create / start / status / stop

The implemented native path creates a new database and restricted runtime role,
imports exactly 20 catalog PDFs, creates Preview Admin/Reviewer accounts, and
starts a loopback backend serving the built frontend on the same origin. Run
`npm ci && npm run build` in `leadtrace/frontend` before starting it. Open
`/review/tasks`, sign in as `preview-reviewer`, and select an assigned Paper.
The Preview banner is shown on login and workspace pages. The Compose file is
still an unsupported deployment scaffold: its web
service currently shares the PostgreSQL owner credentials and must not be
presented as the restricted deployment verified below.

Use a **separate disposable PostgreSQL cluster** and an existing provisioning
database ending in `_preview_admin`. The provisioning login must be able to
create databases and roles and own migration objects. A name suffix cannot prove
cluster isolation; verify the endpoint and data directory before use. No default
application DSN is used. Prefer SCRAM authentication for runtime connections.

From the worktree root, create a private provisioning profile without putting its
password on the command line. Enter the dedicated cluster's SQLAlchemy PostgreSQL
URL at the hidden prompt (for Unix sockets, specify `host` and `port` query keys).
Use an absolute profile path outside the repository for actual credentials.

```bash
.venv/bin/python - <<'PY_PROFILE'
from getpass import getpass
import json
import os
from pathlib import Path
path = Path.home() / '.leadtrace-preview-provisioning.json'
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as handle:
    json.dump({'database_url': getpass('Isolated _preview_admin database URL: ')}, handle)
PY_PROFILE
```

The next commands use operator-selected absolute paths. The source manifest must
be the existing catalog v1 format with exactly 20 entries and matching PDF hashes.
`--commit` identifies the code revision; `--lockfile-sha256` identifies the actual
dependency snapshot used for this run. The backend currently has no checked-in
lockfile: export `pip freeze` locally and record that limitation. Neither digest
identifies uncommitted changes, which must be documented separately during
development.

```bash
task_preview_id=$(.venv/bin/python -c 'import uuid; print(uuid.uuid4())')
task_preview_root=/absolute/path/to/preview-instances
task_preview_lock=/absolute/path/to/backend-requirements.lock
.venv/bin/python -m pip freeze > "$task_preview_lock"
.venv/bin/python -m leadtrace.ops.ai_prefill preview create \
  --registry-root "$task_preview_root" --instance-id "$task_preview_id" \
  --provisioning-profile "$HOME/.leadtrace-preview-provisioning.json" \
  --manifest /absolute/path/to/catalog-manifest.json \
  --source-root /absolute/path/to/source-pdfs \
  --origin http://127.0.0.1:18080 \
  --commit "$(git rev-parse HEAD)" \
  --lockfile-sha256 "$(sha256sum "$task_preview_lock" | cut -d ' ' -f 1)"
.venv/bin/python -m leadtrace.ops.ai_prefill preview start \
  --profile "$task_preview_root/$task_preview_id/runtime.json"
.venv/bin/python -m leadtrace.ops.ai_prefill preview status \
  --profile "$task_preview_root/$task_preview_id/runtime.json"
.venv/bin/python -m leadtrace.ops.ai_prefill preview stop \
  --profile "$task_preview_root/$task_preview_id/runtime.json"
```

Only canonical literal IPv4 loopback origins, such as
`http://127.74.2.2:18080`, are supported in this native version. Choose a different
loopback IP per instance to isolate cookies (different ports alone do not);
`localhost` is rejected because IPv4/IPv6 resolution can select another service.
Start reserves the socket before spawning, verifies registry and database
identity, and waits up to 30 seconds for `/health/ready`. Status reports process
liveness and ownership, not a fresh health result. Stop verifies PID birth time
and command/profile identity and signals through Linux pidfd; unknown processes
and occupied ports are never reclaimed. The code supports libc pidfd calls when
Python lacks wrappers. stdout/stderr from the backend are currently discarded;
startup failures return a safe generic error rather than potentially secret DSNs.

Create returns `registry_path`, `profile_path`, `credentials_path`, the API origin
and `/api/v1/auth/login` endpoint. Retrieve the randomly generated
`preview-admin` / `preview-reviewer` passwords locally from `credentials.json`;
they are not printed by the CLI. Both that file and `runtime.json` are owned mode
`0600` files inside a mode `0700` instance directory. Do not provide either file
to a Producer. Runtime receives only its own restricted database credentials and
an independent session secret; provisioning credentials are never copied there.

The instance contains a fixed manifest and a dedicated copy of the 20 PDFs
(mode `0444`), separate assets/artifacts, and no Celery/beat process. Native file
permissions are not a read-only container mount or a sandbox against the OS
owner. Runtime cannot create tables/databases/roles, change marker identity,
delete markers, or alter Alembic revisions. Account/catalog seed and marker are
one transaction. A failed create leaves `initializing` with a `phase` for
diagnosis, never adopts an existing directory/database/role, and never deletes
resources automatically. Use a new UUID after inspecting a failed initialization.

After login, the Preview operator API under `/api/v2/admin/ai-prefill` accepts
candidates and applies them with an idempotency key and CSRF token. Record
candidate/report/receipt hashes and structured Evaluation with the experiment.
`candidate export` accepts an explicitly edited payload. Prefer the database-bound
`evaluation record` and `candidate export-workspace` sequence below for UI edits.
Preview write requests are capped at 2 MiB of actual streamed bytes and each
Candidate at 5000 scientific objects, including nested members and edges. Apply
and receipt responses include the actual relative `reviewer_url`.

## Feedback, Workspace export and iteration

Read the actual Workspace version and ApplicationReceipt after UI review. Supply
all six coverage keys: `bibliography`, `compounds`, `structures`, `lineages`,
`edge_evidence`, `activities`; values are `reviewed`, `partial`, `not_reviewed`,
or `not_applicable`. Automated display checks do not constitute scientific review.

```bash
.venv/bin/python -m leadtrace.ops.ai_prefill evaluation record /absolute/parent.json \
  --profile /absolute/instance/runtime.json --report /absolute/validation.json \
  --application-id APPLICATION_UUID --expected-workspace-version 3 \
  --evaluation-id review:1 --reviewer REVIEWER_ID --decision needs_revision \
  --coverage /absolute/coverage.json --notes 'Describe reviewed scope and gaps' \
  --output /absolute/evaluation.json
.venv/bin/python -m leadtrace.ops.ai_prefill candidate export-workspace /absolute/parent.json \
  --profile /absolute/instance/runtime.json --application-id APPLICATION_UUID \
  --expected-workspace-version 3 --candidate-id candidate:v2 \
  --evaluation /absolute/evaluation.json --reviewer REVIEWER_ID \
  --output /absolute/child.json
.venv/bin/python -m leadtrace.ops.ai_prefill candidate compare \
  /absolute/parent.json /absolute/child.json
```

Evaluation binds candidate/payload/source hashes, report, receipt, actual/applied
versions and a coherent database snapshot. Export rejects stale versions and
unrepresentable scientific fields, preserves stable references and decimal
values, and records review metadata separately. An edited Workspace cannot be
accepted as the original AI result. Approval state is never inherited by a child.
Validate/import/apply the child in a fresh instance sharing the same PDF identity.
Parent, report, evaluation, child and snapshots are kept in the selected artifact
store. Existing output paths are refused; if publication was interrupted after
artifact persistence, retry using the same IDs and inputs with an unused output
path. Matching artifacts reuse their original timestamps; conflicts are refused.

## Native archival and cleanup

Archive after exporting feedback. Native archive stops only the owned backend,
verifies identity, captures a consistent custom-format `pg_dump`, row/schema
snapshot, PDFs, assets and experiment artifacts, and hashes every archived file.
The archive contains user records and session material: keep its private directory
permissions and do not share it with a Producer. Archive transitions the instance
to `archived`, which blocks Web restart/writes.

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

Destroy requires a complete unchanged archive and exact instance UUID, checks
marker/database/role OIDs and row/schema/file hashes, then removes only that
instance's database, runtime role and copied source/asset directories. Artifacts,
registry, profile and archives remain. A changed database or archive blocks
destruction. Unsupported non-public schemas, materialized/foreign tables and
large objects require reconciliation instead of silently escaping the fingerprint.
Interrupted database/file removal is retryable, including a partially removed
directory; unknown or changed files are rejected. Legacy filesystem commands
without `--profile` still refuse native instances.

To inspect a dump, restore with `pg_restore --no-owner --no-privileges
--exit-on-error --dbname NEW_DISPOSABLE_DATABASE database.dump` in a separate
owned cluster, never over a live Preview or production database. The archived
marker belongs to the old instance: restored data is for recovery/inspection,
not a ready new Preview. For another active Preview, create fresh resources and
reapply the preserved candidates. Keep provisioning credentials outside argv.

Required evidence for a handoff:

- Preview instance UUID, baseline hash, commit and lockfile digest.
- Database marker and migration head.
- Candidate, validation report, receipt, Evaluation, and child-candidate hashes.
- Read-only verify result and any `changed_since_apply` or integrity findings.
- Explicit list of checks not possible without the isolated PostgreSQL and
  browser environment.

## Isolated PostgreSQL integration tests without Docker

Backend integration tests can use a fresh user-owned PostgreSQL cluster. This
checks HTTP routes through FastAPI TestClient, real PostgreSQL transactions, and
real native backend subprocesses. Synthetic 20-PDF fixtures exercise provisioning;
this does not validate the real scientific catalog or a browser deployment.
The `_test` database below is disposable: the pytest fixture resets its schema.
Preview acceptance uses the separate `preview_database_url` fixture: it creates
a UUID-named `_preview` database, migrates it, and drops only that database when
the test ends. The explicit test connection therefore needs database/role provisioning privileges
inside this disposable cluster. Preview never reuses the schema-reset fixture.

Run from the repository/worktree root. PostgreSQL 16 binaries must already be
installed. The socket lives in a newly created private directory; TCP listening
is disabled. The trap stops only this cluster and leaves its log/data directory
available for diagnosis.

```bash
(
  set -eu
  task_pg_bin=/usr/lib/postgresql/16/bin
  task_pg_root=$(mktemp -d /tmp/leadtrace-prefill-pg.XXXXXX)
  chmod 700 "$task_pg_root"
  trap '"$task_pg_bin/pg_ctl" -D "$task_pg_root/data" -m fast -w stop >/dev/null 2>&1 || true' EXIT
  "$task_pg_bin/initdb" -D "$task_pg_root/data" -U prefill_test_admin \
    --auth-local=trust --auth-host=reject > "$task_pg_root/initdb.log"
  printf "listen_addresses = ''\nunix_socket_directories = '%s'\nport = 55439\n" \
    "$task_pg_root" >> "$task_pg_root/data/postgresql.conf"
  printf 'local all prefill_test_admin trust\nlocal all all scram-sha-256\nhost all all 0.0.0.0/0 reject\nhost all all ::0/0 reject\n' \
    > "$task_pg_root/data/pg_hba.conf"
  "$task_pg_bin/pg_ctl" -D "$task_pg_root/data" -l "$task_pg_root/server.log" -w start
  "$task_pg_bin/createdb" -h "$task_pg_root" -p 55439 \
    -U prefill_test_admin ai_prefill_test
  "$task_pg_bin/psql" -h "$task_pg_root" -p 55439 \
    -U prefill_test_admin -d ai_prefill_test \
    -c "SELECT current_database(), current_setting('data_directory');"
  export LEADTRACE_TEST_DATABASE_URL="postgresql+psycopg://prefill_test_admin@/ai_prefill_test?host=$task_pg_root&port=55439"
  cd leadtrace/backend
  ../../.venv/bin/python -m pytest \
    tests/ai_prefill \
    tests/ops/test_ai_prefill_cli.py \
    tests/ops/test_ai_prefill_cli_smoke.py \
    tests/ops/test_ai_prefill_preview_cleanup.py \
    tests/ops/test_ai_prefill_preview_runtime.py \
    tests/security/test_route_permission_matrix.py \
    tests/db \
    tests/workspaces/test_assignment.py \
    tests/ops/test_prefill_four_production_examples.py -q
)
```

See [the current acceptance record](../../../docs/ai-prefill/verification-2026-09-20.md)
for verified behavior and remaining M1 work. The presence of a CLI command or a
Compose configuration is not evidence that the whole Preview lifecycle passed.


## Runtime identity contract

`LEADTRACE_PREVIEW_REGISTRY_PATH` is required in Preview. The registry must be a
regular JSON file, at most 64 KiB, with `schema_version: 1`, `state: "ready"`,
`instance_id`, `database_name`, `database_host`, `database_port`, `baseline_sha256`,
`schema_revision`, `asset_root`, `source_root`, `artifact_root`, `commit`, and
`lockfile_sha256`. It contains no database password or session secret.
`PreviewRuntime.create()` records `artifact_root`; callers should pass it
explicitly (the compatibility default is an `artifacts` sibling of `asset_root`).
Existing registries lacking this field need operator reconciliation before use.

Paths in the registry identify the runtime namespace. For the current Compose
file they must match:

| Field | Runtime value |
| --- | --- |
| `database_host` / `database_port` | `postgres` / `5432` |
| `asset_root` | `/var/lib/leadtrace/preview/assets` |
| `source_root` | `/srv/leadtrace/source-pdfs` |
| `artifact_root` | `/var/lib/leadtrace/preview/artifacts` |
| registry path | `/var/lib/leadtrace/preview/registry/<instance UUID>/registry.json` |

For a native process, use its actual absolute paths and configured database
endpoint. Registry, source, asset, and artifact paths cannot contain symlinks;
source/assets/artifacts cannot overlap, and the registry must be outside them.
Preview v1 supports exactly the registered `source_pdfs` source root.

Startup checks the connected database name, configured and connected host/port,
exactly one marker, baseline, schema head, and these directories. Every request
transaction repeats the identity check, including authentication. Direct
`PreviewApplicationService` callers must pass `settings`; apply checks on its own
connection and locks the marker before receipt/scientific writes. Identity drift
returns `503 PREVIEW_IDENTITY_MISMATCH` without exposing registry content or
credentials. An archived/incomplete registry cannot continue serving Preview
requests; export evidence before archiving.

The identity gate itself does not provision resources. The native commands above
now handle database/catalog/accounts/roles and process lifecycle. Native frontend serving, archival, restore verification and exact database/role
cleanup are covered by integration and browser acceptance. Compose provisioning
and host-to-container resource mapping remain unsupported. Compose parsing is
not deployment acceptance; native is the accepted M1 execution path.
