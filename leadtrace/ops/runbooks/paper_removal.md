# Recoverable paper removal

Use this operation for explicitly authorized article exclusions. It removes an
article and its draft/published content from ordinary user and Admin paper entry
points. Immutable audit events remain accessible through Admin-only audit endpoints
and complete chain verification. Scientific rows, submissions, publication snapshots,
AI records, assets and source metadata remain physically retained for recovery.

## Deployment

Follow current cutover/backup runbooks: verify a protected backup, restore it to an
isolated candidate database, upgrade that candidate to `0034_paper_removal`, and
validate before routing production to it. Preserve the original database and files
for rollback. This additive migration adds nullable `removed_at`, `removed_by_id`
and `removal_reason` columns to `papers`; it imports no scientific data. Merging
source alone does not authorize deployment.

## API contract

Authenticate through the existing Admin login flow, then read
`GET /api/v2/admin/papers/{paper_id}/management`. Verify the article identity against
the approved exclusion list. Send `DELETE /api/v2/admin/papers/{paper_id}` with the
authenticated session cookie, `X-CSRF-Token`, and this JSON body:

```json
{
  "reason": "Confirmed nonprimary review; outside original optimization scope",
  "confirm_paper_key": "EXACT-PAPER-KEY",
  "expected_workspace_id": "CURRENT-WORKSPACE-UUID",
  "expected_workspace_version": 1,
  "expected_task_version": 1
}
```

Copy the three identity/version values from management. If management reports no
active working draft, explicitly send all three as `null`. The paper key must match
exactly. The trimmed reason must contain 1–2000 characters. Unknown fields are rejected.
Do not put credentials in command history, Git or logs.

HTTP 200 returns `paper_id`, `removed_at`, and `audit_event_id`. The transaction locks
paper, workspace, assignment and AI jobs in order, checks identity, marks removal,
archives the active assignment with one task-version increment, and appends the
immutable `paper.remove` audit event. Workspace versions/content and reviewer
identity are retained; approved/historical assignments remain unchanged. The endpoint
does not delete source files.

- 401: authentication required.
- 403: permission denied or missing/invalid CSRF.
- 404: unknown or already removed article, including repeated deletion.
- 409 `PAPER_VERSION_CONFLICT`: refresh management and reevaluate identity.
- 409 `PAPER_TASK_ACTIVE`: queued/preparing/running/validating/cancel-requested
  console task, or queued/running legacy extraction. Wait or explicitly cancel
  through the existing operation, then retry with fresh identity.
- 422: invalid request, including blank reason.

After removal, check absence from catalog/search, assigned tasks, publication and AI
lists. Direct paper/workspace/submission/task/source/derived-asset URLs return 404.
New assignments, edits, approvals including idempotent replay, extraction, review,
repair and delivery are blocked. Check the returned removal event in Admin audit and
verify the complete audit chain. Corpus PDF cleanup remains a separate authorized,
hash-verified operation with a retained recovery copy.

## Recovery

There is no public restore endpoint. An authorized operator must take a fresh backup
and run a controlled transaction against the intended database. Inspect the retained
Paper and exact `paper.remove` audit event: `details.before` records the task ID,
previous state, reviewer and version. Verify no intervening lifecycle changes. Lock
paper, workspace and task in that order; clear all three removal fields together.
Restore only the active task state recorded in that event if resuming the assignment
is explicitly authorized. Increment its current version; never reset versions.
Preserve scientific rows, snapshots, old ChangeEvents and audit events. Append a new
`paper.restore` event through `AuditService.append_event` in the same transaction,
with reason and before/after state. Verify chain and article access after commit.
If source PDFs were separately removed, restore approved originals from their verified
backup and check registered hash and size before reopening source access.

## Verification

DB suites reset `public`: use a separate disposable PostgreSQL cluster with
`LEADTRACE_TEST_DATABASE_URL` ending `_test`, never production or Preview. Run suites
serially. Regression coverage includes Admin/CSRF, stale identities, active jobs,
legacy queue prevention, draft and publication visibility, PDFs/derived files,
scientific row retention, approval replay prevention, audit integrity and other papers.
