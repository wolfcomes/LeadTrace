# LeadTrace Release 1 Acceptance Record

**Record state:** DRAFT - NOT AUTHORIZED FOR PRODUCTION CUTOVER

**Prepared on:** 2026-09-12

**Application target:** `0.1.0`

**Schema target:** `0015_crop_job_subscriptions`
**Release key:** `TO_BE_SELECTED_FROM_CURRENT_RELEASE`

## Evidence rules

Allowed states are `PASS`, `FAIL`, `NOT_RUN`, and `BLOCKED`. `PASS` requires a
timestamped artifact, operator/reviewer identity, exact target version, and
evidence location or digest. A development test result cannot be used as proof
of a production backup, restore, TLS setup, UAT, route switch, or fallback
exercise. Credentials, tokens, cookies, database URLs, and absolute storage
paths must not be recorded here.

## Development automation

These rows record repository verification only. They do not authorize a
production cutover.

| Gate | State | Evidence |
|---|---|---|
| Protected source regression suite | PASS | 323 passed; bytecode and pytest cache writes disabled; approved source manifest separately reports 0 changed, 0 missing, 0 unexpected |
| Legacy Dashboard regression suite | PASS | 69 passed in a fresh invocation |
| LeadTrace backend suite | PASS | 640 passed, 2 skipped because the optional real Redis/Celery integration URL was not configured; isolated PostgreSQL test URL used |
| Frontend typecheck, unit tests, and build | PASS | Typecheck passed; 68 unit tests passed; Vite production build passed |
| Browser E2E suite | PASS | 5 Chromium tests passed, including accessibility, Visitor, concurrent editor, and approval-gated Reviewer flows |
| Cutover preflight code tests | PASS | 31 ops tests passed, including backup, restore, preflight, worker, CLI, and fallback contracts |
| Static Python and repository checks | PASS | Ruff, compileall, and `git diff --check` passed after the implementation |

## Representative Paper selection

The source keys below are evidence-backed candidates, not claims that the same
record is present in the current production release. Before UAT, an Admin and
Reviewer must resolve every candidate to the published LeadTrace Paper UUID,
record the release key, and confirm that the expected feature is still present.
Rows without a defensible source candidate remain `TO_BE_SELECTED`; do not
invent an ID merely to complete the table.

| Coverage | Candidate source Paper key | Published Paper UUID | Selection state | Required evidence |
|---|---|---|---|---|
| Batch 01 | `3725c30c81e3` | TO_BE_SELECTED | TO_BE_SELECTED | Batch membership and published detail screenshot/report |
| Batch 02; prime label | `381572722037` | TO_BE_SELECTED | TO_BE_SELECTED | Distinct `26a` and `26a-prime` entities, no self-loop |
| Batch 03; unresolved parent | `e04dfea8eedb` or another published Batch 03 Paper | TO_BE_SELECTED | TO_BE_SELECTED | Parent remains unresolved and cannot become pair-ready |
| Batch 04; racemate | `9b9e5d0c40bc` | TO_BE_SELECTED | TO_BE_SELECTED | Compounds 40/41 stay non-unique and have no generated pair image |
| Batch 05; rich activity | `8968e9a60ef9` | TO_BE_SELECTED | TO_BE_SELECTED | Activity values, units, source locator, and lineage are readable |
| Batch 06; multicomponent material; source mismatch | `1994543a9112` | TO_BE_SELECTED | TO_BE_SELECTED | `24b` remains multicomponent; `58c` remains source-mismatch rejected |
| multiple roots | TO_BE_SELECTED from current release query | TO_BE_SELECTED | TO_BE_SELECTED | Every root and its branch ownership are preserved |
| branches | `42ab02822a52` or another published branch-rich Paper | TO_BE_SELECTED | TO_BE_SELECTED | Branch labels, immediate parents, and evidence locators agree |
| one-image/many-label | TO_BE_SELECTED after UAT fixture creation | TO_BE_SELECTED | TO_BE_SELECTED | One stored asset is bound to multiple labels without byte duplication |
| multiple sources | `af1d2e15528b` or another source-backed Paper | TO_BE_SELECTED | TO_BE_SELECTED | Each source locator remains separately attributable |
| no pair-ready edge | TO_BE_SELECTED from current release query | TO_BE_SELECTED | TO_BE_SELECTED | Paper stays visible while pair view is empty and explains why |

Batch 01, Batch 02, Batch 03, Batch 04, Batch 05, and Batch 06 must each be
represented by at least one resolved published Paper UUID. The feature rows may
reuse a Batch row when the evidence demonstrates both requirements.

## Role-based UAT

Required participants: one Admin, two distinct Reviewers, and one Visitor.
Reviewer A creates and submits; Admin requests changes; Reviewer B verifies the
returned assignment and conflict behavior; Admin approves and publishes;
Visitor verifies only the published revision. Each transition must record its
changeset/release/audit identifiers without recording session secrets.

Required flow:

```text
login -> published browse -> assigned PDF review -> Region edit
-> image reuse -> multi-label binding -> structure/lineage edit
-> submit -> request changes -> resubmit -> approve -> publish
-> Visitor verification -> release rollback -> audit verification
```

| Production gate | State | Evidence |
|---|---|---|
| Role-based UAT | NOT_RUN | Admin, two Reviewer, and Visitor evidence not yet collected |
| Backup and restore evidence | NOT_RUN | Real backup IDs and recent isolated restore report required |
| Internal CA and LAN TLS | NOT_RUN | Client trust, SAN, selected port, and internal-port scan required |
| Primary-route cutover | NOT_RUN | Nginx validation, reload, and first smoke report required |
| Fallback exercise | NOT_RUN | Old Dashboard primary GET plus denied writes required |
| Return to LeadTrace and repeat smoke | NOT_RUN | A second, separately timestamped smoke report required |

## UAT assertions

- Visitor cannot read full PDFs, drafts, hidden assets, Admin APIs, or
  unpublished changes.
- Reviewer can read an assigned PDF and edit a draft, but cannot approve,
  publish, manage accounts, or edit another Reviewer's assignment.
- A stale concurrent save returns `409` and preserves both users' work.
- Request changes, resubmit, approve, publish, and release rollback remain
  traceable in the audit chain.
- Region geometry survives zoom/rotation and source pixels are not modified.
- A single structure image may be reused and associated with multiple molecule
  numbers; the asset bytes are stored once.
- Racemate, mixture, multicomponent, source mismatch, and unresolved-parent
  states remain explicit. RDKit parseability is not scientific confirmation.
- Duplicate approve/publish operations are idempotent; failed publication does
  not replace the current release.
- Every published asset exists and matches its manifest SHA-256.

## Cutover decision

**Decision:** `NOT_RUN`

**Admin approver:** `TO_BE_RECORDED`

**Operations operator:** `TO_BE_RECORDED`

**Preflight report:** `TO_BE_RECORDED`

**First smoke report:** `TO_BE_RECORDED`

**Fallback evidence:** `TO_BE_RECORDED`

**Second smoke report:** `TO_BE_RECORDED`

The decision may change to `PASS` only after all production gates above pass
against the same application/schema/release target. Until then, keep the old
Dashboard available read-only and do not describe Release 1 as cut over.
