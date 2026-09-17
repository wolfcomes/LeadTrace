# LeadTrace Paper-Centric Pilot Acceptance

**Record state:** DRAFT - NOT AUTHORIZED FOR LIVE DATABASE MIGRATION

**Pilot size:** exactly 20 source PDFs

**Application commit:** `TO_BE_RECORDED`

**Alembic head:** `0025_ai_prefill_runs`

**Pilot database:** `TO_BE_RECORDED`

**Manifest SHA-256:** `TO_BE_RECORDED`

## Evidence rules

Allowed states are `PASS`, `FAIL`, `NOT_RUN`, and `BLOCKED`. A PASS
requires a timestamp, operator identity, exact commit and schema, and an evidence
path or digest. Never record passwords, session cookies, CSRF tokens, database
URLs, or absolute protected source paths in this document.

## Hard stop rules

- Do not run `alembic upgrade` against the live database.
- Do not convert, truncate, clean, or reuse the live database for this pilot.
- Do not target the historical database with `import_pilot --apply`.
- Do not write into `source_pdfs`; Web and Worker mounts must remain read-only.
- Do not continue after a manifest hash, PDF hash, Paper count, audit-chain, or
  restore verification failure.
- Do not interpret an AI run marked succeeded as proof that scientific records
  were extracted. Record actual inserted counts for every Paper.
- Preserve the complete timestamped pre-reset database backup until the pilot,
  rollback drill, and sign-off are complete.

A live cutover is a later operation. This pilot proves the new workflow only in
an empty, isolated PostgreSQL database.

## 1. Verify the preserved backup

Record the timestamped directory containing the complete historical PostgreSQL
backup and corresponding managed-asset backup. Source PDFs remain protected
read-only source material and must not be moved or rewritten.

Run the committed metadata verifier for both backup records:

```bash
python leadtrace/ops/backup/verify_backup.py \
  /srv/leadtrace-backups/<database-backup-id>/backup-metadata.json
python leadtrace/ops/backup/verify_backup.py \
  /srv/leadtrace-backups/<asset-backup-id>/backup-metadata.json
```

| Check | State | Evidence |
|---|---|---|
| Database backup metadata and digest | NOT_RUN | `TO_BE_RECORDED` |
| Asset backup metadata and digest | NOT_RUN | `TO_BE_RECORDED` |
| Backup timestamp predates reset | NOT_RUN | `TO_BE_RECORDED` |
| Backup storage is separate from active data | NOT_RUN | `TO_BE_RECORDED` |
| Protected source-PDF manifest unchanged | NOT_RUN | `TO_BE_RECORDED` |

## 2. Prove rollback before importing

Restore the historical database backup into a new isolated restore database,
not into the pilot or live database. Restore assets into a new empty restore
root. Read the application commit/schema from the verified backup metadata,
then check out that exact historical commit into a separate restore worktree.
Run the restore tooling, dependencies, and expected aggregate from that
historical checkout:

```bash
git worktree add --detach /srv/leadtrace-restore-tooling/<backup-id> \
  <application-commit-from-backup-metadata>
cd /srv/leadtrace-restore-tooling/<backup-id>
LEADTRACE_PYTHON_BIN=/opt/leadtrace-history/.venv/bin/python \
  bash leadtrace/ops/restore/restore_drill.sh
```

The report must identify the selected backup IDs, pass digest and row-count
checks, and remain isolated from LeadTrace Web and Worker processes. Do not run
the current schema-v2 verifier against an unmigrated historical database: the
current verifier is only for the paper-centric backup in section 11. Do not
advance the restored historical database to the paper-centric head.

| Check | State | Evidence |
|---|---|---|
| Historical PostgreSQL restore | NOT_RUN | `TO_BE_RECORDED` |
| Historical asset restore | NOT_RUN | `TO_BE_RECORDED` |
| Restore report and elapsed time | NOT_RUN | `TO_BE_RECORDED` |
| No migration executed on restored historical DB | NOT_RUN | `TO_BE_RECORDED` |

## 3. Prepare a new isolated pilot database

Create a new empty PostgreSQL database dedicated to the pilot. Confirm its
identity and credentials cannot resolve to the live database. Apply migrations
only to this empty pilot database:

```bash
cd leadtrace/backend
python -m alembic -c alembic.ini upgrade head
python -m alembic -c alembic.ini current
```

Expected head: `0025_ai_prefill_runs`.

Render the full offline chain and inspect it for secrets, absolute source paths,
and unexpected targets:

```bash
python -m alembic -c alembic.ini upgrade head --sql \
  >/protected/acceptance/leadtrace-paper-centric.sql
```

The generated chain refuses a nonempty legacy `releases` table at migration
`0013`. That guard prevents offline use from silently omitting the historical
release-artifact backfill.

| Check | State | Evidence |
|---|---|---|
| Database identity is isolated | NOT_RUN | `TO_BE_RECORDED` |
| Empty database migrated to exact head | NOT_RUN | `TO_BE_RECORDED` |
| Offline SQL reviewed | NOT_RUN | `TO_BE_RECORDED` |
| Web and Worker use the pilot database only | NOT_RUN | `TO_BE_RECORDED` |

## 4. Build the deterministic 20-Paper manifest

Mount the full source-PDF root read-only. The selected source directory must
contain at least 20 direct lowercase `.pdf` files. The builder selects the first
20 by filename and rejects symlinks and duplicate hashes.

```bash
python leadtrace/ops/pilot/build_manifest.py \
  --source-root /read-only/source_pdfs \
  --source-directory '<pilot-source-directory>' \
  --source-root-key source_pdfs \
  --journal 'Journal of Medicinal Chemistry' \
  --publication-year 2024 \
  --volume 67 \
  --issue 5 \
  --created-on 2026-09-17 \
  --output /protected/acceptance/pilot-manifest.json
sha256sum /protected/acceptance/pilot-manifest.json
```

Review all 20 ordered entries. Each must have one relative source key, filename,
byte count, and SHA-256. No physical source root may appear in the JSON.

## 5. Dry run and apply the catalog

Run preview first:

```bash
cd leadtrace/backend
python -m app.cli.import_pilot \
  --manifest /protected/acceptance/pilot-manifest.json \
  --source-root /read-only/source_pdfs \
  --dry-run
```

Required output: `verified=20 created=0 unchanged=0`.

Only after preview passes, apply the exact same manifest and source root:

```bash
python -m app.cli.import_pilot \
  --manifest /protected/acceptance/pilot-manifest.json \
  --source-root /read-only/source_pdfs \
  --apply
```

Required first-apply output: `verified=20 created=20 unchanged=0`. Repeat the
apply once to prove exact replay; it must report
`verified=20 created=0 unchanged=20`. Any partial or nonexact existing catalog
is a hard failure.

Verify in PostgreSQL and the Admin Paper Catalog that there are exactly 20
Assets, 20 Paper Sources, and 20 Papers for the manifest, with a one-to-one
mapping and no duplicate DOI or source reference.

## 6. Create accounts and assign a Paper

Create the first Admin only in the empty pilot database, then use that enabled
Admin to create Reviewer accounts. Credentials come from the protected runtime
environment and must not appear in command history or evidence.

```bash
python -m app.cli.users create admin \
  --display-name 'LeadTrace Admin' --role admin --bootstrap
python -m app.cli.users create pilot-reviewer \
  --display-name 'Pilot Reviewer' --role reviewer \
  --actor-id <admin-uuid>
```

Acceptance flow:

1. Sign in as Admin.
2. Open `/admin/papers` and verify exactly 20 catalog rows.
3. Open one Paper and confirm title, journal, year, volume, issue, DOI when
   present, page count, PDF digest, and source integrity.
4. Assign it to the enabled Reviewer.
5. Confirm one blank Workspace and one active Review Task were created.
6. Sign in as Reviewer and confirm only assigned Papers appear in My Tasks.
7. Open the source PDF through the protected `/api/v2` document route.

## 7. Exercise optional AI prefill

On a blank untouched Workspace, the Admin may start AI prefill. Verify
`queued -> running -> succeeded` or a safely reported failure. The apply must
be all-or-nothing and every AI-created scientific row must record
`created_by_kind=ai` with linked Change Events.

For each of the 20 Papers, record:

| Paper key | Run state | Compounds | Structures | Lineages | Edges | Evidence | Activities | Notes |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `TO_BE_RECORDED` | NOT_RUN | - | - | - | - | - | - | - |

A zero-record payload is currently a valid successful adapter result. It still
increments the Workspace version and disables another prefill run. Treat this
as a pilot observation, not as successful scientific extraction; the Reviewer
must complete the Paper manually. This known limitation will inform the later
extraction protocol and evaluation standard.

Verify that:

- AI cannot start after a Reviewer edit;
- a Reviewer version race supersedes the run without partial writes;
- retry does not duplicate records;
- a Reviewer edits an AI-created Structure in place and its UUID stays stable;
- no confidence, candidate pool, or proposal rows exist; and
- source-image crops link to the single Structure without modifying PDFs.

## 8. Complete the variable-length template manually

As the assigned Reviewer:

1. Verify or edit the single-valued bibliography fields.
2. Add as many Compounds as the Paper reports; do not add placeholders.
3. Give each Compound zero or one Structure. Use SMILES or the structure editor,
   and attach source-PDF image occurrences when useful.
4. Build zero or more Lineages with variable numbers of Members and Edges.
5. Mark Lineage roots and terminal optimized products explicitly.
6. Add Edge Evidence from text, tables, or image crops.
7. Add Activities when reported and link them to Compound and Evidence.
8. Mark records or sections unresolved or not reported when appropriate.
9. Verify every edit remains in Workspace history with actor, before/after
   values, version, and timestamp.
10. Resolve all submission blockers and submit an immutable snapshot.

The Reviewer may vary record counts and skip unreported content, but may not
change the shared template or create arbitrary database columns.

## 9. Admin request changes and approval

As Admin:

1. Open the frozen Submission from `/admin/submissions`.
2. Compare source PDF, source structure images, the single current Structure,
   complete Lineage, Edge Evidence, Activities, and Reviewer history.
3. Request changes with a required reason.
4. Confirm the Reviewer can revise the same Workspace and submit a new immutable
   snapshot while the earlier Submission remains unchanged.
5. Review the new Submission and approve with a required reason.
6. Confirm duplicate decision requests are idempotent and stale content hashes
   are rejected.

Approval must create an immutable Published Paper Version and update only that
Paper's current-published pointer. No global Release operation exists in the
paper-centric product flow.

## 10. Verify published and operations surfaces

As Visitor, Reviewer, and Admin, verify the approved Paper appears in
`/papers` with the same content hash and that unpublished Workspace data is not
exposed. Verify structure depictions and Evidence crops through protected asset
routes.

As Admin, verify retained operations pages:

- Users
- Files and current reverse references
- Crop Jobs at `/admin/jobs`
- Audit
- System health with `publication`, not legacy `release`

Verify the thin operations APIs separately: Maintenance status/toggle and
failed Crop Job retry. Maintenance is intentionally API-only in this pilot.

Run audit-chain verification:

```bash
cd leadtrace/backend
python -m app.cli.audit verify
```

Confirm retired URLs return 404, including legacy Imports, Import Candidates,
Changesets, Releases, Approvals, published overview, and v1 Paper routes.

## 11. Back up and restore the completed pilot

Create new database and full managed-asset backups after approval. Do not
replace the historical rollback backups from step 1.

```bash
bash leadtrace/ops/backup/backup_postgres.sh
LEADTRACE_ASSET_BACKUP_MODE=full bash leadtrace/ops/backup/backup_assets.sh
python leadtrace/ops/backup/verify_backup.py \
  /srv/leadtrace-backups/<pilot-database-backup-id>/backup-metadata.json
python leadtrace/ops/backup/verify_backup.py \
  /srv/leadtrace-backups/<pilot-asset-backup-id>/backup-metadata.json
```

Restore both into a second empty, isolated pilot-restore environment. Verify:

- Alembic head is `0025_ai_prefill_runs`;
- catalog, Workspace, Change Event, Submission, Admin Decision, and Published
  Paper counts match;
- current Published Paper hashes match;
- every managed asset exists and matches its SHA-256;
- source PDFs are read from the protected read-only source root; and
- audit verification passes.

Rollback means stopping pilot Web and Worker processes, selecting a verified
backup, restoring PostgreSQL and managed assets together into an isolated
target, and pointing a matching application version at that target. Do not
attempt a reverse Alembic migration through the irreversible paper-centric
boundary.

## 12. Final acceptance matrix

| Gate | State | Evidence |
|---|---|---|
| Historical backup verified | NOT_RUN | `TO_BE_RECORDED` |
| Historical restore drill passed | NOT_RUN | `TO_BE_RECORDED` |
| Live DB was not migrated or targeted | NOT_RUN | `TO_BE_RECORDED` |
| Source-PDF tree unchanged | NOT_RUN | `TO_BE_RECORDED` |
| New isolated DB at exact Alembic head | NOT_RUN | `TO_BE_RECORDED` |
| Manifest contains exactly 20 verified PDFs | NOT_RUN | `TO_BE_RECORDED` |
| Dry run, apply, and idempotent replay passed | NOT_RUN | `TO_BE_RECORDED` |
| Admin and Reviewer account flow passed | NOT_RUN | `TO_BE_RECORDED` |
| Assignment and blank Workspace passed | NOT_RUN | `TO_BE_RECORDED` |
| Optional AI prefill behavior recorded | NOT_RUN | `TO_BE_RECORDED` |
| Reviewer manual completion and history passed | NOT_RUN | `TO_BE_RECORDED` |
| Request changes and resubmission passed | NOT_RUN | `TO_BE_RECORDED` |
| Admin approval and publication passed | NOT_RUN | `TO_BE_RECORDED` |
| Retained operations pages and APIs passed | NOT_RUN | `TO_BE_RECORDED` |
| Retired product URLs return 404 | NOT_RUN | `TO_BE_RECORDED` |
| Audit chain passed | NOT_RUN | `TO_BE_RECORDED` |
| Completed pilot backup and restore passed | NOT_RUN | `TO_BE_RECORDED` |

**Decision:** `NOT_RUN`

**Admin approver:** `TO_BE_RECORDED`

**Reviewer:** `TO_BE_RECORDED`

**Operations operator:** `TO_BE_RECORDED`

Change the decision to PASS only when every gate passes against the same commit,
isolated database, 20-Paper manifest, and backup set.
