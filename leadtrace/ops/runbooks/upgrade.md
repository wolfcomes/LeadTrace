# LeadTrace Upgrade Runbook

## Before changing the schema or application

1. Announce a write-maintenance window and record the reason, start time, and
   expected end time.
2. Confirm the current release, Alembic head, worker version, and asset root.
3. Run a fresh PostgreSQL backup and a full asset backup. Verify both metadata
   files and store their IDs in the change record.
4. Confirm the latest monthly restore drill is successful and within RPO/RTO.
5. Confirm the old Dashboard fallback remains available read-only.
6. Confirm a rollback target release exists and its assets pass SHA-256 checks.

## Apply the upgrade

Run migrations from the versioned backend checkout, with the database URL
provided only through the protected service environment:

```bash
cd leadtrace/backend
python -m alembic -c alembic.ini upgrade head
```

Start the web, worker, and scheduler processes from the same application
version. Keep PostgreSQL, Redis, and FastAPI bound to internal interfaces; only
the selected Nginx LAN port is exposed. Check `/health/live` and `/health/ready`,
then run release validation before enabling writes.

## Post-upgrade gates

- `alembic check` reports no pending operations.
- Database and asset backup verification succeeds.
- Permission smoke tests pass for Admin, Reviewer, and Visitor.
- Published reads still point at the same release until an explicit publish.
- New writes create traceable changesets and audit events.
- Worker recovery/reconciliation is healthy.

If a gate fails, keep writes disabled and follow the incident runbook. Never
repair a failed migration by deleting tables or manually editing release rows.
