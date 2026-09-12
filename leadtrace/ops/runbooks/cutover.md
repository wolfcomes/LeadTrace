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

## Enter maintenance and take rollback backups

Use the Admin maintenance control backed by `PUT /api/v1/admin/maintenance`.
Set a specific reason and expected end time. Verify Visitor published reads
continue and Reviewer write attempts are rejected before continuing.

Use the authenticated Admin session cookie and the CSRF token returned by
login. Keep both values in protected shell variables and out of shell history:

```bash
curl --fail-with-body --request PUT \
  --cookie "leadtrace_session=${LEADTRACE_ADMIN_SESSION}" \
  --header "X-CSRF-Token: ${LEADTRACE_ADMIN_CSRF}" \
  --header 'Content-Type: application/json' \
  --data '{"active":true,"reason":"Release 1 cutover","expected_end":"2026-09-13T02:00:00Z"}' \
  https://127.0.0.1:8877/api/v1/admin/maintenance
```

Load the protected backup environment and capture database and full asset
backups of the state that exists before the final import. These are rollback
backups: their metadata must identify the currently deployed application,
schema, and release, and they must not be substituted for the later cutover
candidate evidence.

```bash
bash leadtrace/ops/backup/backup_postgres.sh
LEADTRACE_ASSET_BACKUP_MODE=full bash leadtrace/ops/backup/backup_assets.sh
python leadtrace/ops/backup/verify_backup.py \
  /srv/leadtrace-backups/<database-backup-id>/backup-metadata.json
python leadtrace/ops/backup/verify_backup.py \
  /srv/leadtrace-backups/<asset-backup-id>/backup-metadata.json
```

Record the rollback backup IDs and destination identity. Stop if verification
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
Record the actual current release key and keep maintenance mode active.

## Back up and restore the cutover candidate

After the final import is applied, validated, approved, and published, create a
second database backup and a second full asset backup. Set the protected backup
environment to the candidate application version, schema revision, and actual
current release key. Use new backup IDs; do not overwrite or relabel the
rollback backups.

```bash
bash leadtrace/ops/backup/backup_postgres.sh
LEADTRACE_ASSET_BACKUP_MODE=full bash leadtrace/ops/backup/backup_assets.sh
python leadtrace/ops/backup/verify_backup.py \
  /srv/leadtrace-backups/<candidate-database-backup-id>/backup-metadata.json
python leadtrace/ops/backup/verify_backup.py \
  /srv/leadtrace-backups/<candidate-asset-backup-id>/backup-metadata.json
```

Provision a new allowlisted empty drill database, a new restore root, and the
isolated HTTPS drill application described in `restore.md`. Point
`LEADTRACE_DATABASE_METADATA` and `LEADTRACE_ASSET_METADATA` at the selected
candidate backup IDs and run the complete restore drill:

```bash
LEADTRACE_PYTHON_BIN=/opt/leadtrace/.venv/bin/python \
  bash leadtrace/ops/restore/restore_drill.sh
```

Stop unless `restore-report.json` is `PASS`, meets the agreed RTO, and its
database ID, terminal asset ID, full asset chain, metadata hashes, and versions
match the selected candidate backup IDs exactly. Update the protected preflight
configuration with these candidate metadata paths, the new restore report, and
the actual current release key. The earlier monthly report and rollback backup
IDs are not valid substitutes.

## Preflight the staged candidate

Before running the machine-readable gate, stage the new site on a loopback-only
TLS listener. This does not change the LAN primary route. Install the committed
preflight server alongside the current route, validate the complete Nginx
configuration, and reload:

```bash
sudo install -m 0644 leadtrace/deploy/nginx/nginx.native-preflight.conf \
  /etc/nginx/conf.d/leadtrace-preflight.conf
sudo nginx -t
sudo nginx -s reload
```

The certificate must include `127.0.0.1` in its SAN for the example config, or
the protected config must use a loopback-resolving hostname present in the SAN.
Set preflight `base_url` to this listener and `old_dashboard_url` directly to
`http://127.0.0.1:8765`. Then run the machine-readable gate from the repository
root:

```bash
.venv/bin/python leadtrace/ops/cutover/preflight.py \
  --config /srv/leadtrace/acceptance/preflight.json \
  --report /srv/leadtrace/acceptance/preflight-report.json
```

Proceed to the LAN route switch only when the process exits `0` and every check
is `PASS`. This includes
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

The public `/legacy-dashboard/` check belongs to the post-switch smoke test;
the preflight uses the direct loopback Dashboard health URL. Keep the
loopback-only preflight server until the second LeadTrace smoke test succeeds,
then remove `/etc/nginx/conf.d/leadtrace-preflight.conf`, run `nginx -t`, and
reload.

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
