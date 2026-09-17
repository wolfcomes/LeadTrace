# LeadTrace Restore Drill Runbook

## Purpose

The monthly drill proves that encrypted database and asset backups are
recoverable without changing production. It runs in a new database, a new
asset directory, and a temporary application route. The drill account is
created only in the isolated environment and is disabled after the drill.

## Preconditions

- Select one verified database backup and one verified asset backup from the
  same maintenance window.
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
export LEADTRACE_EXPECTED_AGGREGATE=/etc/leadtrace/paper-centric-expected-aggregate.json
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

Database verification computes a paper-centric schema-v2 aggregate. It counts
Papers, Sources, section progress, review/workspace history, submissions and
Admin decisions, published versions, AI runs, scientific records, Assets,
Crop Job history, maintenance history, users, and Admin accounts. It also verifies
the Paper Source-to-Asset metadata contract, current publication pointers,
submission/decision/publication hashes, immutable snapshot hashes, the audit
chain, and every restored source or managed asset byte. The report passes only
when those counts and zero-error integrity expectations equal a separately
protected expected aggregate.

The drill username must identify exactly one Reviewer account absent from the
protected backup. The verifier rejects a missing account or any other role,
excludes that one temporary Reviewer from the restored total-user count, and
still requires the complete Admin count to match.

Create that expected aggregate while writes are frozen, immediately before the
matching database and asset backups. Run this read-only command from the
repository root with the production `LEADTRACE_DATABASE_URL`,
`LEADTRACE_ASSET_ROOT`, and `LEADTRACE_SOURCE_ROOTS` already configured, then
move the output to protected read-only storage outside the repository:

```bash
PYTHONPATH=leadtrace/backend:. .venv/bin/python - \
  >paper-centric-expected-aggregate.json <<'PY'
import json
from datetime import UTC, datetime

from app.config import Settings
from leadtrace.ops.restore.verify_restored_system import _safe_database_counts

settings = Settings()
actual = _safe_database_counts(
    settings.database_url,
    asset_root=settings.asset_root,
    source_roots=settings.source_roots,
)
print(json.dumps({
    "schema_version": 2,
    "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    "counts": actual["counts"],
    "integrity_expectations": actual["integrity"],
}, indent=2, sort_keys=True))
PY
```

Do not reuse the legacy Release aggregate at
`leadtrace/ops/baseline/expected_aggregate.json`; it is retained only for the
pre-cutover history until the separate cutover preflight is converted. Review
the generated file and require every integrity expectation to be zero before
accepting it. The file contains counts and error totals only, not database URLs
or storage paths.

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
- the `/api/v2/papers` list and detail reads work;
- an authorized PDF can be read;
- audit events are readable according to the drill role;
- no report field contains a password, token, database URL, or absolute
  storage path.
- database and terminal asset backup IDs, metadata hashes, versions, full
  asset chain IDs, elapsed time, and RTO result match the selected evidence.

If any check fails, mark the drill failed, preserve the isolated environment
for investigation, and do not retry in production. Record the safe error code,
backup IDs, schema/application versions, elapsed time, and corrective action.

## Recovery objective

Track RPO and RTO for every drill. The initial target is an RPO of four hours
for PostgreSQL and one day for assets, with an RTO agreed by the operations
owner before production cutover. A drill that succeeds functionally but misses
the target is a policy failure and requires capacity or scheduling changes.
