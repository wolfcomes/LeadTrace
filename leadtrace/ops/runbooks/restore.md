# LeadTrace Restore Drill Runbook

## Purpose

The monthly drill proves that encrypted database and asset backups are
recoverable without changing production. It runs in a new database, a new
asset directory, and a temporary application route. The drill account is
created only in the isolated environment and is disabled after the drill.

## Preconditions

- Select one verified database backup and one verified asset backup from the
  same release window.
- Confirm `verify_backup.py` succeeds for both metadata files.
- Provision an empty PostgreSQL database, add its exact name to the protected
  drill allowlist, and separately provide the production database URL for
  identity comparison. The target must not contain user tables, views, or
  sequences.
- Choose a restore root that does not exist yet; its parent must already exist.
- Provide the age identity through a protected file, never as metadata or a
  command-line value.
- Provision a drill account with least privilege and an HTTPS base URL for the
  isolated application.

## Execution

```bash
export LEADTRACE_RESTORE_ROOT=/srv/leadtrace-drills/2026-09-12
export LEADTRACE_DATABASE_METADATA=/srv/leadtrace-backups/<db-id>/backup-metadata.json
export LEADTRACE_ASSET_METADATA=/srv/leadtrace-backups/<asset-id>/backup-metadata.json
export LEADTRACE_RESTORE_DATABASE_URL=postgresql+psycopg://<drill-db>
export LEADTRACE_PRODUCTION_DATABASE_URL=postgresql+psycopg://<production-db>
export LEADTRACE_RESTORE_DATABASE_ALLOWLIST=leadtrace_restore_drill_202609
export LEADTRACE_AGE_IDENTITY_FILE=/etc/leadtrace/restore-age-identity
export LEADTRACE_DRILL_BASE_URL=https://leadtrace-drill.lan
export LEADTRACE_DRILL_USERNAME=restore-drill
export LEADTRACE_DRILL_PASSWORD='<provided through protected scheduler secret>'
export LEADTRACE_EXPECTED_AGGREGATE=/opt/leadtrace/leadtrace/ops/baseline/expected_aggregate.json
export LEADTRACE_RESTORE_RTO_SECONDS=3600
export LEADTRACE_PYTHON_BIN=/opt/leadtrace/.venv/bin/python

bash leadtrace/ops/restore/restore_drill.sh
```

`LEADTRACE_ASSET_METADATA` names the terminal asset backup; the script verifies
and replays its complete full-to-incremental chain. It refuses an existing
restore root, the production database identity, a non-allowlisted target, and a
target containing user relations. PostgreSQL restore uses one transaction and
exits on the first SQL error. The script optionally runs Alembic migrations and
writes `restore-report.json`. The configured Python interpreter must contain
the LeadTrace backend dependencies; the versioned systemd unit binds it to the
project virtual environment explicitly.

The encrypted asset chain restores a self-contained bundle: managed bytes are
under `${LEADTRACE_RESTORE_ROOT}/assets/managed`, and source roots are under
`${LEADTRACE_RESTORE_ROOT}/assets/sources/<root-key>`. The manifest binds this
layout and every file hash. The verifier derives its source-root mapping only
from that restored manifest. Configure the temporary LeadTrace application
with the same restored managed/source paths before running the HTTP checks; do
not point it at any live production source tree.

Database verification recomputes the current Release aggregate and runs the
complete Release validator against the restored bundle. The report passes only
when counts and integrity equal the protected expected aggregate and Release
validation has no issues. Cutover preflight independently loads that same
expected aggregate and the protected `restore_rto_seconds` target; values
self-declared only by the restore report are not accepted as cutover evidence.

The restore root is created under `umask 077`. Dump, tar, and chain-list
plaintext are removed on every exit; restored assets are also removed on a
failed drill. Keep the sanitized report and command exit status with the monthly
operations record.

## Acceptance checks

The report must show:

- every asset in the manifest exists with the expected size and SHA-256;
- no unexpected asset files exist;
- every fixed aggregate count and integrity expectation matches the approved
  baseline;
- the drill account can log in over HTTPS;
- a Paper list/detail read works;
- an authorized PDF can be read;
- the current release overview is readable;
- audit events are readable according to the drill role;
- no report field contains a password, token, database URL, or absolute
  storage path.
- database and terminal asset backup IDs, metadata hashes, versions, full
  asset chain IDs, elapsed time, and RTO result match the selected evidence.

If any check fails, mark the drill failed, preserve the isolated environment
for investigation, and do not retry in production. Record the safe error code,
backup IDs, schema/release versions, elapsed time, and corrective action.

## Recovery objective

Track RPO and RTO for every drill. The initial target is an RPO of four hours
for PostgreSQL and one day for assets, with an RTO agreed by the operations
owner before production cutover. A drill that succeeds functionally but misses
the target is a policy failure and requires capacity or scheduling changes.
