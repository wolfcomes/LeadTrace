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
- Provision a new PostgreSQL database whose name is not a production name.
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
export LEADTRACE_AGE_IDENTITY_FILE=/etc/leadtrace/restore-age-identity
export LEADTRACE_DRILL_BASE_URL=https://leadtrace-drill.lan
export LEADTRACE_DRILL_USERNAME=restore-drill
export LEADTRACE_DRILL_PASSWORD='<provided through protected scheduler secret>'

bash leadtrace/ops/restore/restore_drill.sh
```

The script refuses an existing restore root, verifies both metadata records,
decrypts into the new environment, restores PostgreSQL and assets, optionally
runs Alembic migrations, and writes `restore-report.json`. It then removes
temporary plaintext dump/archive files. Keep the report and command exit status
with the monthly operations record.

## Acceptance checks

The report must show:

- every asset in the manifest exists with the expected size and SHA-256;
- no unexpected asset files exist;
- baseline database counts match the selected release evidence;
- the drill account can log in over HTTPS;
- a Paper list/detail read works;
- an authorized PDF can be read;
- the current release overview is readable;
- audit events are readable according to the drill role;
- no report field contains a password, token, database URL, or absolute
  storage path.

If any check fails, mark the drill failed, preserve the isolated environment
for investigation, and do not retry in production. Record the safe error code,
backup IDs, schema/release versions, elapsed time, and corrective action.

## Recovery objective

Track RPO and RTO for every drill. The initial target is an RPO of four hours
for PostgreSQL and one day for assets, with an RTO agreed by the operations
owner before production cutover. A drill that succeeds functionally but misses
the target is a policy failure and requires capacity or scheduling changes.
