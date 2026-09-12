# LeadTrace Incident Runbook

## First response

1. Record the time, operator, symptom, current release, and request ID if one
   is available. Do not copy passwords, cookies, tokens, upload contents, or
   absolute storage paths into the incident record.
2. If scientific writes may be unsafe, enable maintenance mode for Reviewer
   writes. Visitor reads of the current release should remain available.
3. Check liveness, readiness, database connectivity, Redis/worker health,
   storage capacity, schema revision, current release, and latest backup IDs.
4. Preserve logs and audit events. Do not restart every component at once.

## Data or publication risk

If a publication is suspect, stop further publishing, verify the release
manifest and asset hashes, and compare the audit chain. The current release is
immutable; use the Admin rollback operation to move the pointer to an existing
validated release. Never delete revisions or assets to hide an incident.

If a changeset is corrupted or a concurrent edit is reported, keep both
revisions, mark the changeset for review, and use the traceable rollback path.

## Service degradation

- Database unavailable: keep the old read-only Dashboard fallback available;
  do not switch to an unverified local database.
- Redis/worker unavailable: keep published reads available and defer Reviewer
  writes with a clear maintenance response until reconciliation is healthy.
- Asset integrity failure: deny the affected asset, preserve the release, and
  restore the asset from a verified backup in an isolated directory first.
- Suspected credential compromise: disable the account, rotate the session
  secret and age key under the security procedure, and invalidate sessions.

## Recovery and close-out

Use the restore drill process to validate a recovery candidate before any
production restore. Obtain Admin approval for the cutover, take a final backup,
and record exact backup IDs and schema/release versions. After service is
stable, verify role permissions, published reads, audit-chain integrity, and
the old Dashboard fallback. Close the incident only with a timeline, root
cause, impact, evidence links, and preventive actions.
