# LeadTrace 20-Paper Pilot Results

**Acceptance state:** PASS for the isolated pilot; production cutover was not performed

**Application baseline:** `5ea030e527c5520d1e791ffb859e5d8280542125`

**Application version:** `0.1.0`

**Alembic head:** `0025_ai_prefill_runs`

**Pilot manifest SHA-256:** `904585589e2b342705a8ba743e80756ff8e83df70bb94023981df84db21a1254`

**Acceptance window:** 2026-09-17 through 2026-09-18 (Asia/Shanghai)

This record covers an isolated PostgreSQL pilot and isolated asset roots. It
does not authorize or record a production cutover.

## Isolation and historical recovery evidence

- The preserved reset backup `site-reset-20260915T221837+0800` passed its
  native `sha256sum -c checksums.sha256` verification for every listed file.
- The historical database remains at schema
  `0017_unique_active_review_task`; it was not migrated to the paper-centric
  schema. Its original and restored table-count records match, including 648
  Papers, 923 Assets, 7 Users, and 50 Audit Events.
- The paper-centric pilot used a separate `_test` database and external pilot
  asset root. The historical/live database was not read as a restore target or
  migrated.
- The protected Source PDF tree was never written. The final source-manifest
  probe re-read all 20 selected PDFs and reported zero byte or hash
  differences.
- The legacy `dashboard/`, the running Dashboard on port `8765`, and the
  existing LeadTrace/Caddy service on port `8876` were not modified, restarted,
  or repointed.

## Deterministic import

The committed manifest contains exactly 20 ordered entries from Journal of
Medicinal Chemistry, volume 67, issue 5. It contains logical source keys,
sizes, and SHA-256 values only; it contains no physical Source root.

| Operation | Verified | Created | Unchanged | Result |
|---|---:|---:|---:|---|
| Dry run | 20 | 0 | 0 | PASS |
| First apply | 20 | 20 | 0 | PASS |
| Exact replay | 20 | 0 | 20 | PASS |

After import and before assignment, the pilot had 20 Papers, 20 Paper Sources,
20 source Assets, no duplicate source path or hash, and no scientific rows.

## Final pilot aggregate

| Record | Count | Record | Count |
|---|---:|---|---:|
| Papers | 20 | Paper Sources | 20 |
| Assets | 22 | Users / enabled Admins | 3 / 1 |
| Review Tasks | 3 | Paper Workspaces | 3 |
| Section Reviews | 18 | Change Events | 39 |
| Submissions | 3 | Admin Decisions | 3 |
| Published Versions | 2 | Current Published Papers | 2 |
| AI Extraction Runs | 2 | Compounds / Structures | 2 / 2 |
| Structure Source Images | 1 | Lineages / Members | 1 / 2 |
| Lineage Edges | 1 | Evidence / Edge Links | 1 / 1 |
| Activities | 1 | Crop Jobs / Maintenance Windows | 0 / 0 |

All six computed integrity counters were zero: Source-to-Asset mismatches,
current-publication pointer mismatches, publication hash mismatches, immutable
snapshot hash mismatches, missing/corrupt assets, and audit-chain failures.
Each Compound had at most one Structure.

## Workflow evidence

### Manual review, request changes, and approval

- Paper: `841d777d-47e2-47a0-8935-90f0106a98fc`
- First rejected Submission:
  `7ec37625-a5f3-42eb-86e2-38d2259b53d7`
- Final Submission: `068065d9-c2de-4923-b3c2-299e7d355df8`
- Published Version: `054abe07-7ee7-4bf8-bbe3-e57548a6a170`
- Submission and publication content SHA-256:
  `f2e2d4ddcd3426402940c5951e18756f7f62547d8b4201a42c3038eb03c4071b`

The first immutable Submission received an Admin request-changes decision. The
Reviewer revised and resubmitted the same Workspace; Admin approval created the
second immutable Submission's Published Version. At least one published
section was explicitly `not_reported`.

### AI prefill, Reviewer edit, and approval

- Paper: `a68b50da-7777-43c5-8fad-2c5ffef918d3`
- AI run: `c99a5acf-9a72-4b43-af29-6062c400d37b` (`succeeded`)
- Stable edited Structure: `dac197e4-566d-4add-8cf8-4eefebe9169b`
- Reviewer Change Events excluding submission: 11
- Submission: `0cc2a70c-0dda-48b0-bc50-4dbce93a32a4`
- Published Version: `36f65901-f2b8-4308-bd19-b044691324f3`
- Submission and publication content SHA-256:
  `bd8455e8af6b8be0e90617dbccf5f71cd942274438911cf7ae71c2f9e914b4fe`

The workflow first demonstrated submission blockers for an unconfirmed
Structure and incomplete sections, then a missing-Edge-Evidence blocker. The
Reviewer edited the AI-created Structure in place, completed the variable
records, submitted, and received Admin approval.

### AI and Reviewer race

- Paper: `93e5f5b7-d836-4c8b-aabd-af8807bb7b5e`
- AI run: `dbe59bf6-a2e0-4329-b41e-13c9784496f9` (`superseded`)
- Reviewer Change Event: `d9dbeeff-1fee-48a9-bada-afed35eb2b99`

The forced stale AI apply inserted zero scientific rows and preserved the
Reviewer's value. The Reviewer event remains in immutable history.

## Visual acceptance

The production frontend build was exercised at desktop width 1440 and mobile
width 390 against an isolated copy of the pilot. PDF.js, Ketcher, RDKit
depictions, the Lineage graph, long titles, tables, dialogs, and Admin review
rendered without horizontal overflow or incoherent overlap. Pixel sampling
confirmed nonblank PDF and RDKit canvases. Browser errors and failed responses
were both empty.

Visual report SHA-256:
`3ece4db59ca63d2b4af58270e6d679c5283aa53fa9f55bf1a1a4bdcf52cc602d`

| Screenshot | SHA-256 |
|---|---|
| Desktop Compound, Ketcher, and PDF | `8c9e842ee54a98d3c9bb1305269bd56c0b80cc8aeca4a766aac86356b6301044` |
| Desktop Lineage | `6cd48e124b8bdc277f32277715585ccd64a2d230996ff92cbcfd15100237758d` |
| Mobile Compounds | `4b5b09658fd05303fab200e3824a8f117bfe4bf00ec63e847435a19c329ed6b1` |
| Desktop Admin Submission | `fb5423970e5e4bbb794fd0a131c4f054ae9825ee5290960250dc8392e65d7393` |
| Mobile Admin Submission | `8035d061a506b8ea9f9d719e01685bdadaf72613a2be6e3033838b656afe32b7` |

## Encrypted pilot backup and restore

Both backups use `age-x25519`, contain encrypted payloads, and passed the
committed metadata verifier immediately before the restore drill.
They were copied to the independent root-filesystem LVM device before the
drill; the active pilot assets remain on the separate `/data` device. The
protected backup directories and files use permissions `0700` and `0600`.

| Artifact | Backup ID | Metadata SHA-256 | Payload SHA-256 |
|---|---|---|---|
| PostgreSQL | `task19-pilot-20260918-database` | `1b358979be2ccd878a5b596d1f6d93f434240521dd86dd010405aac296a51821` | `15a209538a6a7d8ef7fb7ef06dd86c31c609e25974e4d6a40ba8fe9f78281916` |
| Assets | `task19-pilot-20260918-assets` | `3af846b68834025d93540268042ae9eb93ea9a1f8bc92422602b19e47c26bf73` | `d481a9db48988d88e9daa46e7ab5796d78424133085393304272b009caa222f9` |

Asset manifest SHA-256:
`0e2dfb8f4916799e59fc2de7d807c28948cd309f2e712d881f81022c5fa50507`.
It binds 22 files: all database-referenced managed assets and exactly the 20
manifest Source PDFs in a self-contained logical Source namespace.

The backups were restored into a fresh allowlisted `_test` database and a new
restore root. The restored system reproduced all aggregate counts after
excluding the HTTP drill Reviewer from the user total, all six integrity
counters remained zero, and all 22 restored files matched size and SHA-256.
Login, Paper list/detail, authorized PDF range read, and Audit API checks all
passed. The drill completed in 5 seconds against a 3600-second RTO target.

Restore report SHA-256:
`84786851d2ac4c78c4c4302b3ad0c86b8f6e0504d44da6552616477694a6832c`.

The first independent-destination invocation restored the database and assets,
but its HTTP verification failed because the protected password file name was
passed instead of the file contents. That diagnostic report is not acceptance
evidence. The corrected retry read the protected secret, restored into a second
fresh allowlisted `_test` database/root, and completed successfully.

## Cutover preflight

The real preflight ran against the isolated pilot database with isolated
Redis, Celery, HTTPS, and storage endpoints. All eight gates passed:

1. encrypted PostgreSQL backup;
2. encrypted asset backup;
3. isolated restore drill and RTO;
4. manual, AI, blocker, race, visual, and restore evidence;
5. schema, exact 20-Paper catalog, immutable triggers, audit, assets, and
   workflow identities;
6. HTTPS, Redis, Celery, writable managed storage, and legacy fallback;
7. Visitor, Reviewer, and Admin permission matrix; and
8. all 20 protected Source PDFs with zero differences.

Preflight report SHA-256:
`939844681314066d8a50bdbd157e983c7705ca4c42ba1b49d83533086b532889`.

The runtime permission gate accepted only safe Visitor draft denials (`403` or
`404`), required `404` for an unassigned Reviewer's Source PDF, and confirmed
that the assigned Reviewer could read the configured draft Workspace.

## Repository verification

Fresh verification immediately before the Task 19 review produced:

| Check | Result |
|---|---|
| `git diff --check` | PASS |
| Backend pytest against the dedicated PostgreSQL `_test` database | 679 passed, 1 skipped in 856.82 seconds |
| Frontend unit tests | 18 files, 87 tests passed |
| TypeScript `vue-tsc --noEmit` | PASS |
| Vite production build | PASS |
| Chromium Playwright | 2 end-to-end workflows passed |

The one skipped backend case is the opt-in real Redis/Celery broker test, which
requires `LEADTRACE_TEST_REDIS_URL`. The acceptance preflight independently
started isolated real Redis and Celery processes and received a worker `pong`,
so the required runtime broker/worker check was executed outside pytest.

## Cutover decision

The isolated 20-Paper pilot evidence is complete. Production remains unchanged,
and a live cutover still requires an explicitly approved maintenance window and
fresh confirmation of the final completion gate.
