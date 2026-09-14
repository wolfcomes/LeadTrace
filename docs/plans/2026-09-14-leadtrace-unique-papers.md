# LeadTrace Unique Papers Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Migrate LeadTrace to 648 canonical papers and the reorganized volume/issue PDF paths while preserving all downstream scientific data.

**Architecture:** A deterministic migration utility derives the old-to-canonical paper mapping from current PDF hashes, rewrites the authoritative source facts with validation, and emits an audit report. The existing baseline importer then creates a new immutable import candidate and release instead of modifying the published snapshot.

**Tech Stack:** Python 3.12, CSV/JSON standard libraries, SQLAlchemy, PostgreSQL, pytest, existing LeadTrace baseline and release services.

---

### Task 1: Specify canonical paper migration behavior

**Files:**
- Create: `leadtrace/ops/baseline/migrate_unique_papers.py`
- Create: `leadtrace/backend/tests/ops/test_migrate_unique_papers.py`

**Steps:**
1. Write failing tests for hash-based canonical selection, unmatched and ambiguous pairs, path rewriting, downstream paper-ID rewriting, and collision rejection.
2. Run the focused test and verify the expected failures.
3. Implement the smallest pure migration functions needed by the tests.
4. Run the focused test and verify it passes.
5. Commit the migration behavior.

### Task 2: Add dry-run and transactional file application

**Files:**
- Modify: `leadtrace/ops/baseline/migrate_unique_papers.py`
- Modify: `leadtrace/backend/tests/ops/test_migrate_unique_papers.py`

**Steps:**
1. Write failing tests for dry-run reports, atomic replacement, backups, and idempotence.
2. Verify the tests fail for the missing CLI behavior.
3. Implement `--workspace-root`, `--source-root`, `--dry-run`, `--apply`, `--backup-dir`, and `--report` handling.
4. Run focused tests and the CLI against a temporary fixture.
5. Commit the safe application layer.

### Task 3: Migrate the authoritative source facts

**Files:**
- Modify: `source_pdfs/分子修改提取_2024_JMC/01_manifest/all_volume67_papers.csv`
- Modify: baseline CSV/JSON files containing removed paper IDs
- Create: `leadtrace-data/acceptance/reports/unique-paper-migration.json`
- Create: timestamped source backup under `leadtrace-data/acceptance/backups/`

**Steps:**
1. Back up the affected source facts and the acceptance database.
2. Run the migration utility in dry-run mode and inspect all 24 mappings.
3. Apply the migration atomically.
4. Verify 648 rows, 648 filenames, new volume/issue paths, and zero removed-ID references.
5. Run baseline reconciliation and resolve only expected aggregate differences.

### Task 4: Refresh source provenance

**Files:**
- Modify: `docs/baseline/2026-09-10-source-manifest.json`
- Modify: `leadtrace/ops/baseline/expected_aggregate.json` only where approved counts changed

**Steps:**
1. Add or update tests asserting the 648-paper aggregate.
2. Run the focused tests and observe the old 672 expectation fail.
3. Update the aggregate expectation and regenerate the source manifest from current files.
4. Run manifest verification and baseline reconcile; require zero missing, unexpected, corrupt, or ambiguous article references.
5. Commit source provenance updates.

### Task 5: Create and validate a new import candidate

**Files:**
- No production source changes expected
- Create: timestamped database backup under `leadtrace-data/acceptance/backups/`
- Create: reconciliation/apply reports under `leadtrace-data/acceptance/reports/`

**Steps:**
1. Run the backend import and release tests.
2. Back up the running acceptance database.
3. Run a read-only reconcile and verify 648 papers and 648 verified article assets.
4. Apply the baseline through `BaselineImporter` to create a new batch and candidate.
5. Validate that the old published release remains unchanged and the new candidate is complete.

### Task 6: Publish and verify the 648-paper release

**Files:**
- No source changes expected

**Steps:**
1. Publish the validated candidate through the existing release service.
2. Verify the current release contains 648 distinct papers and no removed paper IDs.
3. Inspect all 648 article assets through `LocalAssetStore` and require exact hash, size, and MIME matches.
4. Exercise protected PDF access for one volume67 and one volume68 article.
5. Run backend tests, frontend tests/build, manifest verification, and a database integrity audit.
6. Record the new batch, candidate, and release identifiers in the migration report.
