# Initial Baseline Release Design

**Date:** 2026-09-13

**Status:** Approved

## Problem

The baseline importer creates immutable scientific objects, approved import
revisions, and an `imported_baseline` candidate, but it does not create a
published release. The normal changeset publisher cannot bootstrap the system
because every changeset requires an existing current release. As a result, an
Admin can inspect the imported batch but cannot approve and publish the first
Visitor-visible version.

The bootstrap path must not bypass the platform's central publication
invariants. Imported data stays invisible until an Admin records an explicit
decision and then performs a separate publication action.

## Chosen Approach

Add a dedicated two-stage initial-release workflow:

1. A completed import creates an `imported_baseline` candidate that is shown as
   pending review.
2. An enabled Admin reviews the candidate's immutable manifest, counts,
   integrity results, and asset-linkage summary.
3. The Admin records either an `approve` or `reject` decision with a required
   reason. This writes an append-only decision record and changes only the
   candidate workflow status.
4. An approved candidate can be published by a separate Admin action. The
   publisher creates and validates the first complete Release before switching
   the current pointer.

Subsequent releases continue to use the existing Reviewer changeset, Admin
approval, and changeset publication flow. The bootstrap API refuses to run
after any finalized release exists.

## Alternatives Rejected

### Combined approve-and-publish action

This is smaller, but it collapses two distinct decisions and makes it harder to
show that the imported facts were approved before publication.

### Operator-only bootstrap CLI

This could populate the first release, but it would bypass the Admin website
workflow that must be exercised during acceptance and would produce weaker
human-review evidence.

## Data Model

Create `import_candidate_decisions` with:

- a UUID primary key;
- a foreign key to one import release candidate;
- `approve` or `reject` as the decision;
- the deciding Admin ID;
- a required reason;
- the canonical SHA-256 of the candidate manifest at decision time;
- a complete immutable copy of the candidate manifest; and
- a server timestamp.

Only one decision is permitted for each candidate. ORM listeners and a
PostgreSQL trigger reject update and delete operations so the record remains
append-only even outside the application.

Candidate statuses are:

```text
imported_baseline -> approved -> published
                  `-> rejected
```

`rejected` and `published` are terminal. A rejected source snapshot must be
corrected and imported as a new fingerprint rather than mutating the rejected
candidate.

## Admin API

Extend the existing protected Admin surface with:

- `GET /api/v1/admin/import-candidates` to return safe candidate manifests and
  any recorded decision;
- `POST /api/v1/admin/import-candidates/{candidate_id}/decision` to record
  `approve` or `reject`; and
- `POST /api/v1/releases/publish-baseline` to publish an approved candidate.

Both mutations require an authenticated Admin, a completed first-password
change, and CSRF validation. Publication also requires an `Idempotency-Key`.
The existing login, session, and route-permission layers remain authoritative.

The decision endpoint is idempotent only for an exact retry of the same
decision, actor, reason, and candidate-manifest hash. Conflicting retries
return `409`.

## Initial Release Construction

Publication acquires the existing PostgreSQL release-pointer advisory lock and
then rechecks all preconditions:

- the actor is an enabled Admin;
- the candidate and completed import batch exist;
- the candidate has one valid approval decision;
- its current manifest hash matches the approved manifest hash;
- no finalized current or historical release exists;
- the fixed baseline counts and integrity values still match the candidate;
- every imported object has exactly one eligible baseline revision; and
- referenced publishable assets exist and match their registered hashes.

Release items are ordered deterministically by Paper key, a fixed object-kind
rank, stable domain identity, and object UUID as the final tie-breaker. The
publisher creates a Release linked through `source_candidate_id`, creates all
Release items, captures the release-scoped artifact manifest, runs the existing
release validator, and only then marks revisions published, finalizes the
Release, marks the candidate `published`, and switches the current pointer.

The Release metrics include the source candidate and batch IDs, source
fingerprint, baseline counts, integrity results, and release item count. The
release key is deterministic from the candidate ID so idempotent retries
return the same release.

Any exception rolls back the complete transaction. No partial Release, current
pointer, candidate transition, or published revision state may remain.

## Audit

The API appends separate audit-chain events for:

- `import_candidate.approved` or `import_candidate.rejected`; and
- `release.baseline_published`.

Events contain IDs, canonical before/after hashes, request ID, actor, result,
and the human reason or release notes. They never contain credentials,
filesystem paths, or raw source records.

## Frontend

The Admin import page adds a candidate table with counts, integrity summary,
asset-linkage summary, decision state, and decision reason. Pending candidates
offer approve and reject controls. An approved candidate offers a separate
publish control with title and notes. Rejected and published candidates are
read-only.

The page distinguishes these states in Chinese:

```text
imported_baseline  待审批
approved           已批准，待发布
rejected           已拒绝
published          已发布
```

Visitors and Reviewers never receive these Admin endpoints or controls. Until
publication completes, the existing Visitor empty-release state remains.

## Failure Handling

- Missing candidate, batch, or decision: `404` or `409` without mutation.
- Non-Admin actor: `403` without revealing candidate details.
- Stale or changed candidate manifest: `409`.
- Invalid counts, revisions, bindings, or assets: `422` with a safe validation
  error and no current-pointer change.
- Reused idempotency key with a different request: `409`.
- Bootstrap attempt after a Release exists: `409`.

## Verification

Tests cover:

- migration upgrade and downgrade plus database-level immutability;
- Admin-only candidate listing and decisions;
- required reason, CSRF, terminal states, and conflicting/idempotent retries;
- publication refusal before approval and after an existing Release;
- deterministic complete Release construction;
- fixed baseline metrics and asset validation;
- atomic rollback at injected failure stages;
- publication idempotency;
- audit events for decision and publication;
- Visitor visibility only after publication; and
- frontend state, controls, and API error handling.

The final acceptance verification repeats the protected source-manifest check,
focused backend and frontend tests, typecheck/build, browser smoke test, and
runtime database/release checks before handing the LAN URL to the user.
