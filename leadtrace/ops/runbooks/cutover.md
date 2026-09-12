# LeadTrace Native Cutover Runbook

## Scope

This procedure is for the current no-Docker deployment. Nginx exposes one LAN
TLS port, `8876`; FastAPI, Redis, PostgreSQL, the Celery worker, and the old
Dashboard remain on loopback or another non-LAN interface. The production
frontend is the versioned output of `npm run build`, not the Vite development
server. `deploy/nginx/nginx.conf` remains the Compose variant;
`deploy/nginx/nginx.native.conf` is the native variant used here.

Only an authorized Admin and an operations operator may conduct the cutover.
Keep Reviewer writes in maintenance mode until every post-cutover gate and the
fallback exercise passes. A failed gate is a stop condition, never a reason to
delete revisions or bypass approval.

## Preconditions

- Record the operator, Admin approver, change window, Git commit, application
  version, Alembic head, target release key, and current route.
- Confirm one Admin, two distinct Reviewers, and one Visitor are available for
  UAT. Store credentials in the protected runtime environment, not this record.
- Confirm the internal CA is trusted by representative LAN clients and the
  certificate contains the deployed hostname/IP in its SAN.
- Confirm PostgreSQL, Redis, FastAPI, and the old Dashboard bind only to
  loopback/internal interfaces. Confirm only the selected Nginx port is LAN
  reachable.
- Confirm the old Dashboard is healthy at `127.0.0.1:8765` and is not writable.
- Confirm the backup destination is a separate disk or controlled network
  destination and a recent isolated restore report exists.
- Read `workspace_root` from the approved source manifest. The import source
  root must be an existing descendant of that directory; a copied corpus at an
  unrelated path cannot satisfy the approved manifest.
- Copy `leadtrace/ops/cutover/preflight.example.json` to a protected operations
  directory and replace every `TO_BE_REPLACED` value with observed evidence.

The protected process environment must define `LEADTRACE_DATABASE_URL`,
`LEADTRACE_REDIS_URL`, and the `LEADTRACE_PREFLIGHT_*` and
`LEADTRACE_SMOKE_*` role credentials. Do not put credentials, database URLs,
tokens, cookies, or absolute source paths in the acceptance document.

## Build and stage

Run the frontend checks and build from the selected commit:

```bash
cd leadtrace/frontend
npm ci --no-audit --no-fund
npm run typecheck
npm test -- --run
npm run build
```

Create a new, commit-specific directory below
`/srv/leadtrace/releases/<git-commit>/frontend`, copy the contents of `dist`
there, and point `/srv/leadtrace/current-frontend` to it with an atomic symlink
replacement. Do not overwrite or delete the previous versioned directory.

Start the version-matched FastAPI process on `127.0.0.1:8000`, the Celery
worker and scheduler against the internal Redis service, and the old Dashboard
on `127.0.0.1:8765`. Run migrations from `leadtrace/backend` before starting
the new web and worker processes:

```bash
python -m alembic -c alembic.ini upgrade head
python -m alembic -c alembic.ini current
```

## Enter maintenance and take final backups

Use the Admin maintenance control backed by `PUT /api/v1/jobs/maintenance`.
Set a specific reason and expected end time. Verify Visitor published reads
continue and Reviewer write attempts are rejected before continuing.

Load the protected backup environment and run final database and full asset
backups. The metadata versions must equal the application, schema, and target
release in the preflight configuration.

```bash
bash leadtrace/ops/backup/backup_postgres.sh
LEADTRACE_ASSET_BACKUP_MODE=full bash leadtrace/ops/backup/backup_assets.sh
python leadtrace/ops/backup/verify_backup.py \
  /srv/leadtrace-backups/<database-backup-id>/backup-metadata.json
python leadtrace/ops/backup/verify_backup.py \
  /srv/leadtrace-backups/<asset-backup-id>/backup-metadata.json
```

Record the finalized backup IDs and destination identity. Stop if verification
fails or the configured age exceeds the four-hour database RPO.

## Apply the final import and validate

Run the exact reconciliation first. `--source-root` is read-only input and must
be the approved source tree; this command must not modify that tree.

```bash
cd leadtrace/backend
python -m app.cli.import_baseline \
  --source-root /absolute/path/inside-manifest-workspace/source_pdfs/approved-corpus \
  --expected-aggregate ../ops/baseline/expected_aggregate.json \
  --source-manifest ../../docs/baseline/2026-09-10-source-manifest.json \
  --report /srv/leadtrace/acceptance/final-reconcile.json \
  --dry-run
```

If and only if the dry run matches exactly, repeat with `--apply`. Admin must
validate the resulting candidate and publish through the approval workflow.
Update the preflight configuration with the actual current release key and
fresh backup metadata paths.

Run the machine-readable gate from the repository root:

```bash
.venv/bin/python leadtrace/ops/cutover/preflight.py \
  --config /srv/leadtrace/acceptance/preflight.json \
  --report /srv/leadtrace/acceptance/preflight-report.json
```

Proceed only when the process exits `0` and every check is `PASS`. This includes
backup and restore recency, exact import counts, zero configured integrity
defects, asset hashes, audit chain, current release, source manifest, database,
Redis, Celery worker, storage, HTTPS, role permissions, and old Dashboard.

## Switch the primary route

Keep a copy of the currently loaded Nginx file outside the included
`conf.d/*.conf` set. Install `leadtrace/deploy/nginx/nginx.native.conf` as the
candidate active file, validate it, then reload. A failed `nginx -t` must be
followed by restoring the prior file without reloading the invalid candidate.

```bash
sudo cp -p /etc/nginx/conf.d/leadtrace.conf /etc/nginx/leadtrace.conf.previous
sudo install -m 0644 leadtrace/deploy/nginx/nginx.native.conf \
  /etc/nginx/conf.d/leadtrace.conf
sudo nginx -t
sudo nginx -s reload
```

From a LAN client that trusts the internal CA, run:

```bash
.venv/bin/python leadtrace/ops/cutover/smoke_test.py \
  --config /srv/leadtrace/acceptance/smoke.json \
  --report /srv/leadtrace/acceptance/smoke-after-cutover.json
```

Also verify the authorized PDF range response, browser login, target release,
and the acceptance Paper matrix. Record timestamps and report hashes.

## Exercise the read-only fallback

Do this before enabling Reviewer writes. Follow `rollback-cutover.md` to install
`nginx.native-fallback.conf`, run `nginx -t`, and reload. Confirm the old
Dashboard is the primary route, a GET succeeds, and POST/PUT/PATCH/DELETE are
denied. The fallback is a route change only: preserve the LeadTrace database,
assets, audit events, and all new revisions.

Restore `nginx.native.conf`, validate, reload, and repeat `smoke_test.py` into a
new report file. A successful first smoke test is not evidence for this second
run. Keep both reports.

## Complete or stop

After the second LeadTrace smoke test and role-based UAT pass, obtain explicit
Admin approval and disable maintenance mode with a recorded reason. Monitor
errors, worker queue depth, audit verification, and backup jobs throughout the
stabilization window. Keep `/legacy-dashboard/` available read-only.

If any gate fails, keep maintenance active, do not publish another release,
and follow `leadtrace/ops/runbooks/rollback-cutover.md`.
