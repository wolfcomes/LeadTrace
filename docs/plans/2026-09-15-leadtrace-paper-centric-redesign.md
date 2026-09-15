# LeadTrace Paper-Centric Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a usable 20-Paper LeadTrace workflow in which an Admin can catalog and assign Source PDFs, a Reviewer can complete a fixed scientific template manually or from AI-prefilled data, and an Admin can approve an immutable Paper submission for publication.

**Architecture:** PostgreSQL stores one normalized editable aggregate per Paper, while append-only change events preserve every AI and human mutation and immutable JSONB snapshots preserve submissions and published versions. Source PDFs remain read-only assets; PDF locators and derived crops provide evidence, RDKit validates and renders each Compound's single Structure, and typed `/api/v2` product endpoints replace the retired scientific `/api/v1` routes on the redesign branch. The deployed `:8876` service continues running the old branch and schema until the final cutover gate.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16, Pydantic, Celery/Redis, PyMuPDF, RDKit, Vue 3, TypeScript, TanStack Vue Query, Zod, PDF.js, Ketcher, Cytoscape.js, Vitest, Playwright, pytest.

---

## Execution Preconditions

- Work only in `.worktrees/leadtrace-redesign` on branch `codex/leadtrace-redesign`.
- Read `docs/plans/2026-09-15-leadtrace-paper-centric-redesign-design.md` before each milestone.
- Use a dedicated PostgreSQL database whose name ends in `_test`; never point tests or migrations at `leadtrace_acceptance`.
- Do not apply the new migration to the running `:8876` service before Task 19's cutover gate.
- Keep the legacy Dashboard on `:8765` available as read-only comparison; do not import its review overrides as approved data.
- Use `superpowers:test-driven-development` for every implementation task and `superpowers:verification-before-completion` before every commit.
- Run commands below from the worktree root unless a step explicitly changes directory.

Recommended one-time environment setup:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e 'leadtrace/backend[test]'
cd leadtrace/frontend && npm ci && cd ../..
export LEADTRACE_TEST_DATABASE_URL='postgresql+psycopg://<test-user>@127.0.0.1/leadtrace_redesign_test'
export LEADTRACE_PILOT_SOURCE_ROOT="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")/source_pdfs"
test -d "$LEADTRACE_PILOT_SOURCE_ROOT/volume67 issue5"
```

The worktree-local `source_pdfs/` contains only tracked legacy Dashboard code, not the 660 protected PDFs. `LEADTRACE_PILOT_SOURCE_ROOT` therefore resolves the shared main-workspace Source directory. It is a read-only runtime input and must never be persisted in manifests, database rows, API responses, logs, or acceptance results as an absolute path.

## Milestone 1: PostgreSQL Foundation and the Manual Backend Path

### Task 1: Introduce the Paper-Centric Schema Boundary

**Files:**

- Create: `leadtrace/backend/migrations/versions/0019_paper_centric_foundation.py`
- Create: `leadtrace/backend/app/catalog/__init__.py`
- Create: `leadtrace/backend/app/catalog/models.py`
- Replace: `leadtrace/backend/app/papers/models.py`
- Create: `leadtrace/backend/app/workspaces/__init__.py`
- Create: `leadtrace/backend/app/workspaces/models.py`
- Modify: `leadtrace/backend/app/assets/models.py`
- Modify: `leadtrace/backend/app/audit/models.py`
- Modify: `leadtrace/backend/app/db/model_registry.py`
- Modify: `leadtrace/backend/app/main.py`
- Modify: `leadtrace/backend/migrations/env.py`
- Modify: `leadtrace/backend/tests/db/test_migrations.py`
- Modify: `leadtrace/backend/tests/security/test_route_permission_matrix.py`
- Test: `leadtrace/backend/tests/db/test_paper_centric_migration.py`

**Step 1: Write the failing migration inventory test**

Add a test that upgrades an empty database through Alembic head and asserts that the new tables exist:

```python
EXPECTED = {
    "paper_sources",
    "papers",
    "review_tasks",
    "paper_workspaces",
    "paper_section_reviews",
    "change_events",
}

def test_paper_centric_foundation_is_installed(empty_postgresql_database_url):
    command.upgrade(_alembic_config(empty_postgresql_database_url), "head")
    assert EXPECTED <= _public_tables(empty_postgresql_database_url)
```

Also assert that `users`, `auth_sessions`, `login_attempts`, `assets`, `audit_events`, and `audit_chain_head` survive the transition. Add an upgrade fixture at revision `0017_unique_active_review_task` with one enabled Admin and one valid current session, upgrade through `0018` and `0019`, and prove the account/password hash/session remain intact while all new product tables are empty.

**Step 2: Run the test and verify it fails**

```bash
cd leadtrace/backend
../../.venv/bin/pytest tests/db/test_paper_centric_migration.py -v
```

Expected: FAIL because revision `0019_paper_centric_foundation` and the new tables do not exist.

**Step 3: Add the foundation models and current model registry**

Implement typed enums and SQLAlchemy models for:

```text
PaperSource (`app.catalog.models`)
Paper (`app.papers.models`)
ReviewTask
PaperWorkspace
PaperSectionReview
ChangeEvent
```

`PaperSource` owns one unique Source-PDF `asset_id`, logical `source_root_key`, project-relative `source_key`, SHA-256, byte size, page count, integrity state, and timestamps. `Paper` owns the unique human-readable `paper_key`, unique `source_id`, title, journal, publication year, volume, issue, nullable DOI, catalog state, and timestamps. Do not duplicate technical Source fields on `Paper`.

Use application UUIDs, timezone-aware timestamps, explicit check constraints, and composite uniqueness that makes Paper the ownership boundary. `ChangeEvent` must include `paper_id`, `workspace_id`, entity type/id, action, `before_value`, `after_value`, actor kind/id, nullable `ai_run_id`, and timestamp. `ai_run_id` is initially an unconstrained UUID because `ai_extraction_runs` is introduced in `0023`; Task 17 adds its foreign key.

The six and only six section keys are `bibliography`, `compounds`, `structures`, `lineages`, `edge_evidence`, and `activities`; their states are `pending`, `completed`, and `not_reported`. Workspace states are `editing`, `submitted`, and `approved`; Task states are `assigned`, `submitted`, `changes_requested`, and `approved`. Change Event actor kinds are `reviewer`, `admin`, `ai`, and `system`; `actor_id` is required for human actors and null for AI/system actors. Encode these invariants as database checks as well as Python enums.

Do not make `Paper` inherit the legacy `RevisionedObject`.

Update `app.db.model_registry` and `migrations/env.py` so current metadata loads only preserved foundation/operations models plus the new Paper/Workspace models. Remove retired imports from current metadata; historical Alembic revisions remain self-contained and do not require legacy ORM registration.

**Step 4: Implement the controlled transition migration**

The migration must:

1. Refuse to run if legacy scientific/import/review/release tables contain business rows.
2. Preserve users, sessions, login attempts, assets, audit chain, and maintenance state.
3. Detach `assets.import_batch_id` from the retired import tables.
4. Detach obsolete audit foreign keys before retiring legacy Paper/Changeset/Release tables.
5. Retire the empty legacy scientific/import/review/release tables in dependency order.
6. Create the foundation tables and append-only mutation trigger for `change_events`.
7. Rebind optional `audit_events.paper_id` to the new `papers` table.

Keep the nullable `audit_events.changeset_id` and `audit_events.release_id` values for chain compatibility, but remove their retired foreign keys. The migration must not rewrite existing Audit Event content or hashes.

The downgrade must explicitly raise an irreversible-migration error and instruct operators to restore the mandatory pre-cutover PostgreSQL backup. Do not pretend to reconstruct retired data.

**Step 5: Switch the redesign branch to the foundation route surface**

Remove imports and registration of retired import/revision/release/review/science/approval product routers from `app.main` in the same commit that replaces their tables. Keep login, users, assets, audit, health, and metrics operational. Do not deploy this branch to `:8876`; route removal here does not change the running service.

Replace the old migration-head assertions in `tests/db/test_migrations.py` with assertions for the `0019` restore-only transition. Add a route inventory test proving retired scientific `/api/v1` endpoints are absent rather than registered against tables that no longer exist.

**Step 6: Add failure tests for unsafe migration and immutable history**

Test that an upgrade from `0018_reviewer_scientific_workspace` containing one legacy Paper refuses to proceed, and that SQL UPDATE/DELETE against `change_events` raises PostgreSQL error `55000`.

**Step 7: Run migration and preserved-foundation tests**

```bash
cd leadtrace/backend
../../.venv/bin/pytest \
  tests/db/test_database.py \
  tests/db/test_migrations.py \
  tests/db/test_paper_centric_migration.py \
  tests/auth \
  tests/assets \
  tests/security/test_route_permission_matrix.py -v
```

Expected: PASS. No test may claim the retired `0018` business schema is still the current head. Any downgrade-through-head assertion must be replaced with the documented restore-only rollback contract.

**Step 8: Commit**

```bash
git add leadtrace/backend/migrations leadtrace/backend/app/catalog \
  leadtrace/backend/app/papers/models.py leadtrace/backend/app/workspaces \
  leadtrace/backend/app/assets/models.py leadtrace/backend/app/audit/models.py \
  leadtrace/backend/app/db/model_registry.py leadtrace/backend/app/main.py \
  leadtrace/backend/tests/db \
  leadtrace/backend/tests/security/test_route_permission_matrix.py
git commit -m "feat: add paper-centric database foundation"
```

### Task 2: Build and Import the Fixed 20-Paper Pilot Manifest

**Files:**

- Create: `leadtrace/ops/pilot/__init__.py`
- Create: `leadtrace/ops/pilot/build_manifest.py`
- Create: `docs/pilot/2026-09-15-volume67-issue5-first20.json`
- Create: `leadtrace/backend/app/catalog/extraction.py`
- Create: `leadtrace/backend/app/catalog/service.py`
- Create: `leadtrace/backend/app/cli/import_pilot.py`
- Test: `leadtrace/backend/tests/catalog/test_manifest.py`
- Test: `leadtrace/backend/tests/catalog/test_import.py`

**Step 1: Write failing deterministic-selection tests**

Create temporary PDF fixtures and assert that the builder:

- considers only direct `.pdf` files under `volume67 issue5`;
- sorts by Unicode filename;
- selects exactly the first 20;
- stores project-relative paths, SHA-256, byte size, and manifest order;
- produces byte-identical JSON on repeated runs;
- rejects symlinks, duplicate hashes, missing files, and traversal.

**Step 2: Run the manifest tests and verify failure**

```bash
cd leadtrace/backend
../../.venv/bin/pytest tests/catalog/test_manifest.py -v
```

Expected: FAIL because the pilot builder is missing.

**Step 3: Implement the manifest builder**

Use structured JSON and `Path.relative_to`; do not parse filesystem paths with string splitting. The checked-in manifest must contain `schema_version`, `source_root_key`, `source_directory`, a controlled collection block (`journal`, `publication_year`, `volume`, `issue`), `created_on`, and 20 ordered entries. Make `created_on` and collection metadata explicit CLI arguments so identical inputs and arguments produce byte-identical output.

Run it against the shared protected Source root, never the incomplete worktree-local directory:

```bash
.venv/bin/python leadtrace/ops/pilot/build_manifest.py \
  --source-root "$LEADTRACE_PILOT_SOURCE_ROOT" \
  --source-directory 'volume67 issue5' \
  --source-root-key source_pdfs \
  --journal 'Journal of Medicinal Chemistry' \
  --publication-year 2024 \
  --volume 67 \
  --issue 5 \
  --created-on 2026-09-15 \
  --output docs/pilot/2026-09-15-volume67-issue5-first20.json
```

Inspect the diff and verify exactly 20 entries and 20 unique hashes before committing. The JSON may contain only logical root keys and POSIX relative paths, never `$LEADTRACE_PILOT_SOURCE_ROOT` itself.

**Step 4: Write failing catalog extraction tests**

Using small PyMuPDF-generated PDFs, assert:

- journal, publication year, Volume, and Issue come from the controlled manifest collection block and are rejected when contradictory PDF metadata/text is unambiguous;
- title uses usable PDF metadata, then first-page text, then filename fallback;
- DOI is nullable and extracted only by a strict DOI pattern;
- page count and hash match the file;
- absolute paths never enter persisted or returned data.

**Step 5: Implement catalog extraction and transactional import**

`CatalogImportService.apply()` must verify every manifest hash before inserting anything, use `LocalAssetStore.source_storage_key()` to persist only `source/source_pdfs/<relative-key>`, register each PDF as an `Asset`/`PaperSource`, create a stable `paper_key`, and remain idempotent on exact replay. Any mismatch rolls back all 20 records. The CLI receives the physical root only to construct a temporary `LocalAssetStore`; it must not serialize that physical root.

**Step 6: Add the guarded CLI**

Support:

```bash
python -m app.cli.import_pilot --manifest <path> --source-root <path> --dry-run
python -m app.cli.import_pilot --manifest <path> --source-root <path> --apply
```

The dry run prints counts and hash validation without database writes. `--apply` refuses a nonempty Paper catalog unless every record is the same idempotent import.

**Step 7: Run focused tests**

```bash
cd leadtrace/backend
../../.venv/bin/pytest tests/catalog/test_manifest.py tests/catalog/test_import.py -v
```

Expected: PASS with tests for exact replay and all-or-nothing failure.

**Step 8: Commit**

```bash
git add leadtrace/ops/pilot docs/pilot leadtrace/backend/app/catalog \
  leadtrace/backend/app/cli/import_pilot.py leadtrace/backend/tests/catalog
git commit -m "feat: import fixed twenty-paper pilot catalog"
```

### Task 3: Add Admin Catalog and Assignment APIs

**Files:**

- Create: `leadtrace/backend/app/catalog/schemas.py`
- Create: `leadtrace/backend/app/catalog/router.py`
- Create: `leadtrace/backend/app/workspaces/schemas.py`
- Create: `leadtrace/backend/app/workspaces/assignment.py`
- Modify: `leadtrace/backend/app/main.py`
- Modify: `leadtrace/backend/app/security/policies.py`
- Test: `leadtrace/backend/tests/catalog/test_api.py`
- Test: `leadtrace/backend/tests/workspaces/test_assignment.py`
- Test: `leadtrace/backend/tests/security/test_route_permission_matrix.py`

**Step 1: Write failing role and assignment tests**

Test `GET /api/v2/admin/papers`, `GET /api/v2/admin/papers/{id}`, and `POST /api/v2/admin/papers/{id}/assign`. Assert:

- Admin sees all 20 Papers and safe Source metadata;
- Reviewer and Visitor receive 403;
- assignment accepts an enabled Reviewer only;
- assignment creates one ReviewTask, one blank Workspace, and six pending section rows;
- no baseline or Release exists or is required;
- duplicate active assignment returns 409;
- source errors make a Paper unassignable.

**Step 2: Run the tests and verify failure**

```bash
cd leadtrace/backend
../../.venv/bin/pytest tests/catalog/test_api.py tests/workspaces/test_assignment.py -v
```

Expected: FAIL with missing `/api/v2` routes.

**Step 3: Implement typed schemas and assignment transaction**

The service must lock the Paper row, verify the reviewer role and Source integrity, create all assignment records in one transaction, and append a credential-free audit event.

**Step 4: Register routes and permissions**

The redesign branch's retired scientific `/api/v1` routes are already absent after Task 1. Keep the surviving authentication/users/assets/audit routes stable, and ensure every `/api/v2` route has an explicit route-access declaration and CSRF checks on assignment.

**Step 5: Run focused and permission tests**

```bash
cd leadtrace/backend
../../.venv/bin/pytest \
  tests/catalog/test_api.py \
  tests/workspaces/test_assignment.py \
  tests/security/test_route_permission_matrix.py -v
```

Expected: PASS.

**Step 6: Commit**

```bash
git add leadtrace/backend/app/catalog leadtrace/backend/app/workspaces \
  leadtrace/backend/app/main.py leadtrace/backend/app/security/policies.py \
  leadtrace/backend/tests/catalog leadtrace/backend/tests/workspaces \
  leadtrace/backend/tests/security/test_route_permission_matrix.py
git commit -m "feat: add paper catalog assignment API"
```

### Task 4: Implement Workspace Versioning, Section Decisions, and Change Events

**Files:**

- Create: `leadtrace/backend/app/workspaces/history.py`
- Create: `leadtrace/backend/app/workspaces/service.py`
- Create: `leadtrace/backend/app/workspaces/router.py`
- Test: `leadtrace/backend/tests/workspaces/test_history.py`
- Test: `leadtrace/backend/tests/workspaces/test_api.py`
- Test: `leadtrace/backend/tests/workspaces/test_concurrency.py`

**Step 1: Write failing mutation-history tests**

Use a simple bibliography update and section status update to establish the shared mutation contract:

```python
result = service.mutate(
    session,
    workspace_id=workspace.id,
    expected_version=1,
    actor=reviewer,
    mutation=update_title,
)
assert result.workspace.version == 2
assert result.event.before_value["title"] == "Extracted title"
assert result.event.after_value["title"] == "Reviewed title"
```

Assert that the data update, version increment, and Change Event roll back together on error.

**Step 2: Write failing concurrency and authorization tests**

Assert that a stale `expected_workspace_version` returns 409, an unassigned Reviewer sees 404 rather than leaked metadata, and submitted/approved Workspaces reject writes.

**Step 3: Implement the row-locking mutation helper**

Centralize `SELECT ... FOR UPDATE`, ownership checks, editable-state checks, version comparison, mutation, event append, and version increment. Entity services in later tasks must use this helper instead of implementing their own history logic.

**Step 4: Add aggregate read and bibliography/section endpoints**

Implement:

```text
GET   /api/v2/review/tasks
GET   /api/v2/workspaces/{workspaceId}
PATCH /api/v2/workspaces/{workspaceId}/bibliography
PUT   /api/v2/workspaces/{workspaceId}/sections/{section}
```

Return only safe Source locators and the current Workspace version.

**Step 5: Run tests**

```bash
cd leadtrace/backend
../../.venv/bin/pytest tests/workspaces/test_history.py \
  tests/workspaces/test_api.py tests/workspaces/test_concurrency.py -v
```

Expected: PASS.

**Step 6: Commit**

```bash
git add leadtrace/backend/app/workspaces leadtrace/backend/tests/workspaces
git commit -m "feat: add versioned paper workspaces"
```

### Task 5: Add the Scientific Record Schema and Constraints

**Files:**

- Create: `leadtrace/backend/migrations/versions/0020_paper_science_records.py`
- Replace: `leadtrace/backend/app/compounds/models.py`
- Replace: `leadtrace/backend/app/structures/models.py`
- Replace: `leadtrace/backend/app/lineages/models.py`
- Replace: `leadtrace/backend/app/evidence/models.py`
- Replace: `leadtrace/backend/app/activities/models.py`
- Create: `leadtrace/backend/app/structure_images/__init__.py`
- Create: `leadtrace/backend/app/structure_images/models.py`
- Modify: `leadtrace/backend/migrations/env.py`
- Test: `leadtrace/backend/tests/science_v2/test_models.py`
- Test: `leadtrace/backend/tests/db/test_paper_science_migration.py`

**Step 1: Write failing constraint tests**

Cover:

- zero-or-one Structure per Compound;
- same-Paper and same-Workspace ownership;
- unique Compound label within a Workspace;
- unique Lineage membership;
- no self Edge;
- no duplicate directed Edge within one Lineage;
- Edge endpoints must be members of that Lineage;
- normalized bbox bounds satisfy `0 <= x0 < x1 <= 1` and equivalent Y bounds;
- Evidence link cannot cross Paper or Workspace.

**Step 2: Run tests and verify failure**

```bash
cd leadtrace/backend
../../.venv/bin/pytest tests/science_v2/test_models.py \
  tests/db/test_paper_science_migration.py -v
```

Expected: FAIL because science tables are absent.

**Step 3: Implement normalized models**

Create `compounds`, `structures`, `structure_source_images`, `lineages`, `lineage_members`, `lineage_edges`, `evidence`, `edge_evidence_links`, and `activities`. Every mutable row must include `paper_id` and `workspace_id`, with composite unique constraints that allow composite foreign keys to enforce aggregate ownership.

Structure statuses are exactly `draft`, `reviewer_confirmed`, `unresolved`, and `not_reported`. Input methods are exactly `ai_prefill`, `manual_smiles`, and `structure_editor`. Do not add a Proposal or confidence column.

`compounds` carries paper-local label, display name, description, order, and creator kind. `structures.compound_id` is unique and carries raw SMILES/Molfile, backend-generated canonical SMILES/InChI/InChIKey, depiction Asset, status, and input method. `structure_source_images` binds directly to a Compound, not to Structure, and stores one PDF occurrence as source SHA-256, page, normalized bbox, context/label/note, crop status, and nullable crop Asset; one Compound may have many such images.

`lineages` is repeatable per Paper; `lineage_members` assigns each Compound `root`, `intermediate`, `terminal`, or `unspecified`; `lineage_edges` stores directed parent/child, relation type, modification summary, review status, and order. `evidence` stores PDF/text/table/scheme/image locators and quoted context. `edge_evidence_links` carries `supports`, `contradicts`, or `contextual` and is the primary proof for an Edge. `activities` stores Compound, assay name, metric, operator, value, unit, context, order, and optional Evidence without doing unit conversion.

**Step 4: Implement migration `0020`**

Create all tables, indexes, check constraints, and composite foreign keys explicitly. Add query indexes for Workspace Compound order, Lineage order, Edge endpoints, Evidence page, and Activity Compound.

**Step 5: Run migration/model tests**

```bash
cd leadtrace/backend
../../.venv/bin/pytest tests/science_v2/test_models.py \
  tests/db/test_paper_science_migration.py -v
```

Expected: PASS.

**Step 6: Commit**

```bash
git add leadtrace/backend/migrations/versions/0020_paper_science_records.py \
  leadtrace/backend/app/compounds leadtrace/backend/app/structures \
  leadtrace/backend/app/lineages leadtrace/backend/app/evidence \
  leadtrace/backend/app/activities leadtrace/backend/app/structure_images \
  leadtrace/backend/migrations/env.py leadtrace/backend/tests/science_v2 \
  leadtrace/backend/tests/db/test_paper_science_migration.py
git commit -m "feat: add paper-scoped scientific records"
```

### Task 6: Add Typed Compound and Single-Structure Editing

**Files:**

- Create: `leadtrace/backend/app/compounds/schemas.py`
- Replace: `leadtrace/backend/app/compounds/service.py`
- Replace: `leadtrace/backend/app/compounds/router.py`
- Create: `leadtrace/backend/app/structures/schemas.py`
- Replace: `leadtrace/backend/app/structures/service.py`
- Replace: `leadtrace/backend/app/structures/router.py`
- Test: `leadtrace/backend/tests/science_v2/test_compound_api.py`
- Test: `leadtrace/backend/tests/science_v2/test_structure_api.py`

**Step 1: Write failing Compound CRUD tests**

Test add, edit, reorder, and delete endpoints. Each successful mutation must increment Workspace version once and append exactly one Change Event. Deleting a Compound referenced by a Lineage or Activity must return 409 with safe reference counts.

**Step 2: Write failing Structure tests**

Test `PUT /api/v2/compounds/{id}/structure` for:

- AI-prefill, manual SMILES, and structure-editor input methods;
- updating the same row rather than creating candidates;
- preserving old values in Change Events;
- saving invalid text as Draft with no canonical values;
- refusing `reviewer_confirmed` when RDKit cannot parse;
- clearing content only when status becomes `unresolved` or `not_reported`.

**Step 3: Run tests and verify failure**

```bash
cd leadtrace/backend
../../.venv/bin/pytest tests/science_v2/test_compound_api.py \
  tests/science_v2/test_structure_api.py -v
```

Expected: FAIL against missing v2 routes.

**Step 4: Implement typed services through the shared mutation helper**

Reuse `app.chemistry.validation` and `app.chemistry.drawing`. Only the backend creates canonical SMILES, InChI, InChIKey, and standardized depiction bytes. Never accept those fields as authoritative client input.

**Step 5: Run tests**

```bash
cd leadtrace/backend
../../.venv/bin/pytest tests/science_v2/test_compound_api.py \
  tests/science_v2/test_structure_api.py tests/chemistry -v
```

Expected: PASS.

**Step 6: Commit**

```bash
git add leadtrace/backend/app/compounds leadtrace/backend/app/structures \
  leadtrace/backend/tests/science_v2
git commit -m "feat: edit compounds and single structures"
```

### Task 7: Capture Structure Source Images from Protected PDFs

**Files:**

- Create: `leadtrace/backend/app/structure_images/schemas.py`
- Create: `leadtrace/backend/app/structure_images/service.py`
- Create: `leadtrace/backend/app/structure_images/router.py`
- Replace: `leadtrace/backend/app/documents/service.py`
- Replace: `leadtrace/backend/app/documents/router.py`
- Modify: `leadtrace/backend/app/jobs/execution.py`
- Modify: `leadtrace/backend/app/assets/models.py`
- Modify: `leadtrace/backend/app/main.py`
- Test: `leadtrace/backend/tests/science_v2/test_structure_image_api.py`
- Test: `leadtrace/backend/tests/documents/test_range_requests.py`
- Test: `leadtrace/backend/tests/documents/test_pdf_access.py`

**Step 1: Write failing locator and crop tests**

Test valid creation, page out of range, invalid bbox, source hash mismatch, unassigned Reviewer, cross-Paper Compound, crop failure, and deterministic repeated crop. Assert responses never expose an absolute path.

**Step 2: Run tests and verify failure**

```bash
cd leadtrace/backend
../../.venv/bin/pytest tests/science_v2/test_structure_image_api.py -v
```

Expected: FAIL because the route is missing.

**Step 3: Extract a synchronous deterministic crop primitive**

Reuse `render_pdf_crop` and `LocalAssetStore`; do not require Celery for first-use cropping. Store the locator before rendering, write a managed crop asset on success, and leave `crop_asset_id` null plus a safe retryable status on rendering failure.

**Step 4: Replace legacy document resolution and implement source-image CRUD**

Replace candidate/Release-based PDF lookup with `Paper -> PaperSource -> Asset` resolution and expose `GET /api/v2/papers/{paperId}/source-pdf`. Admin and the assigned Reviewer may read the protected Source; unassigned users receive 404. Preserve single-range requests, integrity verification, private cache headers, and the no-absolute-path response contract.

All source-image operations use the Workspace mutation helper and Change Events. The Source PDF, page, and bbox remain authoritative; crop assets are replaceable derivatives.

**Step 5: Run focused tests**

```bash
cd leadtrace/backend
../../.venv/bin/pytest tests/science_v2/test_structure_image_api.py \
  tests/documents/test_range_requests.py tests/documents/test_pdf_access.py \
  tests/security/test_asset_paths.py -v
```

Expected: PASS.

**Step 6: Commit**

```bash
git add leadtrace/backend/app/structure_images leadtrace/backend/app/jobs/execution.py \
  leadtrace/backend/app/documents leadtrace/backend/app/assets/models.py \
  leadtrace/backend/app/main.py \
  leadtrace/backend/tests/science_v2 leadtrace/backend/tests/documents
git commit -m "feat: capture compound structure evidence from PDFs"
```

### Task 8: Add Lineage, Evidence, and Activity Editing APIs

**Files:**

- Create: `leadtrace/backend/app/lineages/schemas.py`
- Replace: `leadtrace/backend/app/lineages/service.py`
- Replace: `leadtrace/backend/app/lineages/router.py`
- Create: `leadtrace/backend/app/evidence/schemas.py`
- Replace: `leadtrace/backend/app/evidence/service.py`
- Replace: `leadtrace/backend/app/evidence/router.py`
- Create: `leadtrace/backend/app/activities/schemas.py`
- Replace: `leadtrace/backend/app/activities/service.py`
- Replace: `leadtrace/backend/app/activities/router.py`
- Modify: `leadtrace/backend/app/main.py`
- Test: `leadtrace/backend/tests/science_v2/test_lineage_api.py`
- Test: `leadtrace/backend/tests/science_v2/test_evidence_api.py`
- Test: `leadtrace/backend/tests/science_v2/test_activity_api.py`

**Step 1: Write failing happy-path tests**

Create two Lineages in one Paper, add shared Compounds as members with distinct roles, create branching Edges, attach one Evidence item to multiple Edges, and add multiple Activities to one Compound.

**Step 2: Write failing boundary tests**

Exercise all cross-Paper, cross-Workspace, non-member endpoint, self-edge, duplicate-edge, invalid Evidence locator, and referenced-delete cases. Assert every mutation produces one history event.

**Step 3: Run tests and verify failure**

```bash
cd leadtrace/backend
../../.venv/bin/pytest tests/science_v2/test_lineage_api.py \
  tests/science_v2/test_evidence_api.py tests/science_v2/test_activity_api.py -v
```

Expected: FAIL against missing implementations.

**Step 4: Implement typed endpoints**

Use explicit schemas; do not accept arbitrary snapshot JSON. Keep role enums fixed and represent absent sections through `paper_section_reviews`, not empty placeholder rows.

**Step 5: Run tests**

```bash
cd leadtrace/backend
../../.venv/bin/pytest tests/science_v2 -v
```

Expected: PASS.

**Step 6: Commit**

```bash
git add leadtrace/backend/app/lineages leadtrace/backend/app/evidence \
  leadtrace/backend/app/activities leadtrace/backend/app/main.py \
  leadtrace/backend/tests/science_v2
git commit -m "feat: edit lineages evidence and activities"
```

### Task 9: Freeze and Validate Reviewer Submissions

**Files:**

- Create: `leadtrace/backend/migrations/versions/0021_paper_submissions.py`
- Modify: `leadtrace/backend/app/workspaces/models.py`
- Create: `leadtrace/backend/app/workspaces/snapshot.py`
- Create: `leadtrace/backend/app/workspaces/validation.py`
- Create: `leadtrace/backend/app/workspaces/submission.py`
- Modify: `leadtrace/backend/app/workspaces/router.py`
- Test: `leadtrace/backend/tests/workspaces/test_snapshot.py`
- Test: `leadtrace/backend/tests/workspaces/test_submission.py`
- Test: `leadtrace/backend/tests/db/test_paper_submission_migration.py`

**Step 1: Write failing canonical snapshot tests**

Build the same Paper aggregate in different insertion orders and assert byte-identical canonical JSON and SHA-256. Ensure snapshots contain safe Source keys but no absolute paths, sessions, passwords, or unpublished data from another Paper.

**Step 2: Write failing validation tests**

Submission must fail with record-addressable blockers when:

- a section remains pending;
- Structure is Draft or falsely confirmed with no canonical SMILES;
- an Edge has no supports Evidence;
- a Lineage lacks explicit root/terminal disposition;
- an entity crosses the Paper/Workspace boundary.

It must allow `unresolved`, `not_reported`, zero-entry sections explicitly marked `not_reported`, multiple roots, multiple terminals, and branching chains.

**Step 3: Implement immutable submission storage**

Create `paper_submissions` with unique `(workspace_id, submission_number)`, idempotency key, immutable snapshot/hash, frozen Workspace version, submitter/note/time, and no mutable workflow-state column. Protect UPDATE/DELETE with a PostgreSQL trigger. Pending/approved/requested-changes status is derived from the presence and type of an immutable Admin Decision plus current Task/Workspace state.

**Step 4: Implement submit transaction**

Lock the Workspace, verify ownership/version, validate, build the snapshot, persist it, and move Task/Workspace to submitted in one transaction. A repeated request with the same idempotency key returns the same Submission.

**Step 5: Run tests**

```bash
cd leadtrace/backend
../../.venv/bin/pytest tests/workspaces/test_snapshot.py \
  tests/workspaces/test_submission.py tests/db/test_paper_submission_migration.py -v
```

Expected: PASS.

**Step 6: Commit**

```bash
git add leadtrace/backend/migrations/versions/0021_paper_submissions.py \
  leadtrace/backend/app/workspaces leadtrace/backend/tests/workspaces \
  leadtrace/backend/tests/db/test_paper_submission_migration.py
git commit -m "feat: freeze reviewer paper submissions"
```

### Task 10: Add Admin Decisions and Published Paper Versions

**Files:**

- Create: `leadtrace/backend/migrations/versions/0022_paper_publications.py`
- Create: `leadtrace/backend/app/publications/__init__.py`
- Create: `leadtrace/backend/app/publications/models.py`
- Create: `leadtrace/backend/app/publications/schemas.py`
- Create: `leadtrace/backend/app/publications/service.py`
- Create: `leadtrace/backend/app/publications/router.py`
- Create: `leadtrace/backend/app/publications/admin_router.py`
- Modify: `leadtrace/backend/app/papers/models.py`
- Modify: `leadtrace/backend/app/main.py`
- Modify: `leadtrace/backend/migrations/env.py`
- Test: `leadtrace/backend/tests/publications/test_decisions.py`
- Test: `leadtrace/backend/tests/publications/test_api.py`
- Test: `leadtrace/backend/tests/publications/test_visibility.py`

**Step 1: Write failing approval-state tests**

Assert:

- Admin reviews a specific Submission hash;
- `request_changes` requires a reason and restores the same Workspace to editable state;
- resubmission creates submission number 2 and leaves number 1 immutable;
- approve creates one current Published Paper Version;
- repeated idempotency key returns the same decision/version;
- Reviewer cannot approve;
- formal Paper endpoints expose only approved snapshots.

**Step 2: Run tests and verify failure**

```bash
cd leadtrace/backend
../../.venv/bin/pytest tests/publications -v
```

Expected: FAIL because publication tables/routes are absent.

**Step 3: Implement models and migration**

Create append-only `admin_decisions` and immutable `published_paper_versions`. One unique Decision is allowed per Submission; it stores `submission_id`, the exact `content_hash`, action, required reason, Admin, Idempotency Key, and time. Published Versions are unique by Submission and by `(paper_id, version_number)`. Store snapshot/hash from the approved Submission without rebuilding it from mutable rows. Add nullable `papers.current_published_version_id` as the only mutable publication pointer; approving a new exact Submission creates an immutable version and atomically swaps that pointer. Do not put an `is_current` flag on immutable version rows.

**Step 4: Implement Admin and formal-data APIs**

Implement:

```text
GET  /api/v2/admin/submissions
GET  /api/v2/admin/submissions/{submissionId}
POST /api/v2/admin/submissions/{submissionId}/decisions
GET  /api/v2/papers
GET  /api/v2/papers/{paperId}
GET  /api/v2/papers/{paperId}/assets/{assetId}
```

The decision request carries the exact `content_hash` and an Idempotency Key. The Admin detail includes the frozen snapshot and a server-derived AI-to-Reviewer Change Event diff. Formal Paper detail is a typed projection of the immutable snapshot reached through `papers.current_published_version_id`, never the editable Workspace. The published-asset endpoint may serve only RDKit/crop assets referenced by that exact current snapshot; it must not expose the full Source PDF or draft/unreferenced assets.

**Step 5: Run tests**

```bash
cd leadtrace/backend
../../.venv/bin/pytest tests/publications tests/audit -v
```

Expected: PASS.

**Step 6: Commit**

```bash
git add leadtrace/backend/migrations/versions/0022_paper_publications.py \
  leadtrace/backend/app/publications leadtrace/backend/app/papers/models.py \
  leadtrace/backend/app/main.py \
  leadtrace/backend/migrations/env.py leadtrace/backend/tests/publications
git commit -m "feat: approve and publish paper submissions"
```

## Milestone 2: Usable Website

### Task 11: Establish the Frontend v2 Contract and Navigation

**Files:**

- Create: `leadtrace/frontend/src/v2/types.ts`
- Create: `leadtrace/frontend/src/v2/api.ts`
- Modify: `leadtrace/frontend/src/app/router.ts`
- Modify: `leadtrace/frontend/src/app/AppShell.vue`
- Modify: `leadtrace/frontend/src/i18n/zh-CN.ts`
- Modify: `leadtrace/frontend/package.json`
- Modify: `leadtrace/frontend/package-lock.json`
- Test: `leadtrace/frontend/tests/v2-contract.spec.ts`
- Test: `leadtrace/frontend/tests/navigation.spec.ts`

**Step 1: Write failing Zod contract tests**

Define fixtures for Paper catalog rows, Task rows, full Workspace aggregates, Change Events, Submissions, and Published Papers. Assert invalid cross-field states and absolute Source paths are rejected by Zod.

**Step 2: Write failing route/navigation tests**

Assert Admin sees Articles and Submissions, Reviewer sees My Tasks, and Visitor sees only approved Articles. Remove visible navigation to legacy Changesets, Imports, and Releases.

**Step 3: Run tests and verify failure**

```bash
cd leadtrace/frontend
npm test -- tests/v2-contract.spec.ts tests/navigation.spec.ts
```

Expected: FAIL because v2 schemas and routes are absent.

**Step 4: Implement schemas, API client wrappers, routes, and icons**

Add `lucide-vue-next` and `cytoscape` as pinned dependencies. Use icon buttons with tooltips for edit/delete/retry/navigation actions. Keep all option sets as selects/menus, binary states as toggles, and section status as a segmented control.

**Step 5: Run tests and typecheck**

```bash
cd leadtrace/frontend
npm test -- tests/v2-contract.spec.ts tests/navigation.spec.ts
npm run typecheck
```

Expected: PASS.

**Step 6: Commit**

```bash
git add leadtrace/frontend/src/v2 leadtrace/frontend/src/app \
  leadtrace/frontend/src/i18n leadtrace/frontend/package.json \
  leadtrace/frontend/package-lock.json leadtrace/frontend/tests
git commit -m "feat: add paper-centric frontend contract"
```

### Task 12: Build the Admin Paper Catalog and Assignment UI

**Files:**

- Replace: `leadtrace/frontend/src/admin/PaperCatalogPage.vue`
- Replace: `leadtrace/frontend/src/admin/PaperCatalogDetailPage.vue`
- Create: `leadtrace/frontend/src/admin/ReviewerAssignmentDialog.vue`
- Modify: `leadtrace/frontend/src/styles/components.css`
- Modify: `leadtrace/frontend/src/styles/layouts.css`
- Test: `leadtrace/frontend/tests/admin-paper-catalog-v2.spec.ts`

**Step 1: Write failing Admin workflow tests**

Mock `/api/v2/admin/papers` and assert the table renders exactly the single-valued catalog fields, source integrity, assignee, section progress, and submission state. Test Reviewer assignment, duplicate conflict, source-error disablement, and retained pagination/search state. AI status/action is deliberately absent until Task 17 provides a real run API.

**Step 2: Run tests and verify failure**

```bash
cd leadtrace/frontend
npm test -- tests/admin-paper-catalog-v2.spec.ts
```

Expected: FAIL against legacy components.

**Step 3: Implement quiet operational pages**

Use a dense table, not decorative cards. Keep stable column widths and mobile row layout. The first-use action is Assign Reviewer; manual review must be complete before any AI integration exists.

**Step 4: Run tests and build**

```bash
cd leadtrace/frontend
npm test -- tests/admin-paper-catalog-v2.spec.ts
npm run build
```

Expected: PASS.

**Step 5: Commit**

```bash
git add leadtrace/frontend/src/admin leadtrace/frontend/src/styles \
  leadtrace/frontend/tests/admin-paper-catalog-v2.spec.ts
git commit -m "feat: build pilot paper assignment console"
```

### Task 13: Build the Reviewer Task List and Workspace Shell

**Files:**

- Replace: `leadtrace/frontend/src/review/tasks/TaskListPage.vue`
- Create: `leadtrace/frontend/src/review/paper/PaperWorkspacePage.vue`
- Create: `leadtrace/frontend/src/review/paper/WorkspaceHeader.vue`
- Create: `leadtrace/frontend/src/review/paper/SectionStatusControl.vue`
- Create: `leadtrace/frontend/src/review/paper/usePaperWorkspace.ts`
- Test: `leadtrace/frontend/tests/paper-workspace.spec.ts`
- Test: `leadtrace/frontend/tests/workspace-concurrency-v2.spec.ts`

**Step 1: Write failing task/workspace tests**

Assert that a blank assigned Paper opens without a baseline or Release, renders the five fixed tabs, shows six pending section decisions, and keeps add controls available. Verify 409 handling reloads the aggregate and never silently retries a stale mutation.

**Step 2: Run tests and verify failure**

```bash
cd leadtrace/frontend
npm test -- tests/paper-workspace.spec.ts tests/workspace-concurrency-v2.spec.ts
```

Expected: FAIL because the new workspace is missing.

**Step 3: Implement Workspace query/mutation coordination**

Keep one authoritative Workspace version in the composable. Invalidate the aggregate after each mutation; preserve active tab, selected entity, page, and filters in URL query parameters.

**Step 4: Implement the responsive shell**

Use fixed-height header/status regions and stable tab dimensions. On narrow screens, stack context above the active editor and keep commands reachable without overlapping content.

**Step 5: Run tests**

```bash
cd leadtrace/frontend
npm test -- tests/paper-workspace.spec.ts tests/workspace-concurrency-v2.spec.ts
npm run typecheck
```

Expected: PASS.

**Step 6: Commit**

```bash
git add leadtrace/frontend/src/review/tasks leadtrace/frontend/src/review/paper \
  leadtrace/frontend/tests/paper-workspace.spec.ts \
  leadtrace/frontend/tests/workspace-concurrency-v2.spec.ts
git commit -m "feat: add blank paper review workspace"
```

### Task 14: Add Compound, Ketcher, RDKit, and PDF Source-Image Editing

**Files:**

- Create: `leadtrace/frontend/src/review/paper/CompoundList.vue`
- Create: `leadtrace/frontend/src/review/paper/CompoundStructureEditor.vue`
- Create: `leadtrace/frontend/src/review/paper/KetcherEditor.vue`
- Create: `leadtrace/frontend/src/review/paper/StructureSourceImages.vue`
- Modify: `leadtrace/frontend/src/pdf-viewer/PdfReviewCanvas.vue`
- Modify: `leadtrace/frontend/package.json`
- Modify: `leadtrace/frontend/package-lock.json`
- Test: `leadtrace/frontend/tests/compound-structure-v2.spec.ts`
- Test: `leadtrace/frontend/tests/structure-source-images.spec.ts`

**Step 1: Validate and pin Ketcher's integration dependencies**

Check `ketcher-react`, `ketcher-core`, `ketcher-standalone`, React, and ReactDOM peer compatibility. Pin a mutually compatible set in `package-lock.json`; do not load an editor from a remote CDN.

**Step 2: Write failing editor contract tests**

Assert:

- one Compound renders at most one Structure editor;
- AI-prefilled Structure is edited in place;
- no confidence or candidate list appears;
- SMILES and Ketcher Molfile both call the same PUT endpoint;
- invalid Draft remains editable and cannot be confirmed;
- before/after history is available to Admin, not duplicated in the editor.

**Step 3: Write failing PDF selection tests**

Test drawing a normalized rectangle, selecting a Compound, submitting page/bbox, retrying a failed crop, and showing Source crop beside the RDKit rendering.

**Step 4: Implement Ketcher as an isolated React island**

Mount/unmount the React editor from a Vue wrapper, expose only `getMolfile`, `setMolecule`, and change events, and keep all scientific validation on the backend. Ensure the wrapper does not resize the surrounding layout while loading.

**Step 5: Implement source-image capture**

Extend the existing PDF.js canvas with an explicit rectangle-selection mode. Do not enable editing gestures during normal PDF navigation.

**Step 6: Run tests and build**

```bash
cd leadtrace/frontend
npm test -- tests/compound-structure-v2.spec.ts \
  tests/structure-source-images.spec.ts
npm run build
```

Expected: PASS.

**Step 7: Commit**

```bash
git add leadtrace/frontend/src/review/paper \
  leadtrace/frontend/src/pdf-viewer/PdfReviewCanvas.vue \
  leadtrace/frontend/package.json leadtrace/frontend/package-lock.json \
  leadtrace/frontend/tests
git commit -m "feat: edit structures with source PDF evidence"
```

### Task 15: Add Lineage, Evidence, Activity, and Submission UI

**Files:**

- Create: `leadtrace/frontend/src/review/paper/LineageEditor.vue`
- Create: `leadtrace/frontend/src/review/paper/LineageGraph.vue`
- Create: `leadtrace/frontend/src/review/paper/EdgeEditor.vue`
- Create: `leadtrace/frontend/src/review/paper/EvidenceEditor.vue`
- Create: `leadtrace/frontend/src/review/paper/ActivityEditor.vue`
- Create: `leadtrace/frontend/src/review/paper/SubmissionChecklist.vue`
- Test: `leadtrace/frontend/tests/lineage-editor-v2.spec.ts`
- Test: `leadtrace/frontend/tests/evidence-activity-v2.spec.ts`
- Test: `leadtrace/frontend/tests/submission-v2.spec.ts`

**Step 1: Write failing variable-entry tests**

Test multiple Lineages, multiple roots/terminals, branching Edges, one Evidence linked to multiple Edges, variable Activity rows, item deletion, and explicit `not_reported` sections.

**Step 2: Write failing submission-blocker tests**

Render record-addressable blockers and assert clicking one opens the correct tab/entity. Verify a valid empty `not_reported` section is not a blocker.

**Step 3: Implement form-based editing and read-only Cytoscape graph**

Use selects for parent/child/role, icon commands for item operations, and stable graph dimensions. Do not implement drag-to-write behavior.

**Step 4: Implement Evidence PDF focus and submit flow**

Evidence selection may reuse the PDF rectangle mode or accept quoted text/page. Submission requires the Reviewer statement and an explicit confirmation checkbox.

**Step 5: Run tests and build**

```bash
cd leadtrace/frontend
npm test -- tests/lineage-editor-v2.spec.ts \
  tests/evidence-activity-v2.spec.ts tests/submission-v2.spec.ts
npm run build
```

Expected: PASS.

**Step 6: Commit**

```bash
git add leadtrace/frontend/src/review/paper leadtrace/frontend/tests
git commit -m "feat: complete reviewer scientific entry workflow"
```

### Task 16: Build Admin Approval and Published Paper Pages

**Files:**

- Replace: `leadtrace/frontend/src/approvals/ApprovalCenterPage.vue`
- Create: `leadtrace/frontend/src/approvals/PaperSubmissionReviewPage.vue`
- Create: `leadtrace/frontend/src/approvals/SubmissionDiff.vue`
- Replace: `leadtrace/frontend/src/papers/PaperLibraryPage.vue`
- Replace: `leadtrace/frontend/src/papers/PaperDetailPage.vue`
- Test: `leadtrace/frontend/tests/paper-approval-v2.spec.ts`
- Test: `leadtrace/frontend/tests/published-paper-v2.spec.ts`
- Test: `leadtrace/frontend/e2e/paper-centric-manual.spec.ts`

**Step 1: Write failing Admin review tests**

Assert the page shows frozen Submission identity/hash, full Lineage, source/RDKit comparisons, AI-to-Reviewer differences, and required decision reason. Test request changes, resubmission number, approve, and duplicate action handling.

**Step 2: Write failing visibility tests**

Assert unapproved Paper data never appears in formal pages and an approved snapshot remains unchanged when the editable Workspace later changes.

**Step 3: Implement approval and formal pages**

Keep the approval surface read-only except decision controls. Formal Paper detail renders only the typed Published Version projection.

**Step 4: Add the manual-path Playwright test**

Exercise login, assignment, blank Workspace, one Compound/Structure, two-node Lineage, Edge Evidence, section completion, submission, Admin approval, and final Paper visibility.

**Step 5: Run tests and build**

```bash
cd leadtrace/frontend
npm test -- tests/paper-approval-v2.spec.ts tests/published-paper-v2.spec.ts
npm run build
npx playwright test e2e/paper-centric-manual.spec.ts
```

Expected: PASS.

**Step 6: Commit**

```bash
git add leadtrace/frontend/src/approvals leadtrace/frontend/src/papers \
  leadtrace/frontend/tests leadtrace/frontend/e2e/paper-centric-manual.spec.ts
git commit -m "feat: approve and publish reviewed papers"
```

## Milestone 3: Optional AI Prefill and Pilot Cutover

### Task 17: Add Transactional AI Prefill Without a Proposal Pool

**Files:**

- Create: `leadtrace/backend/migrations/versions/0023_ai_prefill_runs.py`
- Create: `leadtrace/backend/app/ai_prefill/__init__.py`
- Create: `leadtrace/backend/app/ai_prefill/models.py`
- Create: `leadtrace/backend/app/ai_prefill/contracts.py`
- Create: `leadtrace/backend/app/ai_prefill/extractor.py`
- Create: `leadtrace/backend/app/ai_prefill/legacy_adapter.py`
- Create: `leadtrace/backend/app/ai_prefill/service.py`
- Create: `leadtrace/backend/app/ai_prefill/router.py`
- Create: `leadtrace/backend/app/ai_prefill/celery_tasks.py`
- Modify: `leadtrace/backend/app/worker.py`
- Modify: `leadtrace/backend/app/main.py`
- Modify: `leadtrace/backend/app/config.py`
- Modify: `leadtrace/backend/app/workspaces/models.py`
- Modify: `leadtrace/backend/migrations/env.py`
- Create: `leadtrace/frontend/src/admin/AiPrefillStatus.vue`
- Modify: `leadtrace/frontend/src/admin/PaperCatalogPage.vue`
- Modify: `leadtrace/frontend/src/admin/PaperCatalogDetailPage.vue`
- Modify: `leadtrace/frontend/src/v2/types.ts`
- Modify: `leadtrace/frontend/src/v2/api.ts`
- Test: `leadtrace/backend/tests/ai_prefill/test_contract.py`
- Test: `leadtrace/backend/tests/ai_prefill/test_apply.py`
- Test: `leadtrace/backend/tests/ai_prefill/test_worker.py`
- Test: `leadtrace/frontend/tests/ai-prefill.spec.ts`
- Test: `leadtrace/frontend/e2e/paper-centric-ai-prefill.spec.ts`

**Step 1: Write failing normalized payload tests**

Define a versioned payload containing bibliography corrections, Compounds, one Structure per Compound, structure locators, Lineages, Members, Edges, Evidence, and Activities. Explicitly reject confidence and Structure candidate arrays.

**Step 2: Write failing race/atomicity tests**

Assert:

- prefill applies to a blank untouched Workspace;
- every inserted record has `created_by_kind=ai` and linked Change Events;
- AI Structure writes the same unique Structure row later edited by Reviewer;
- any Reviewer version change between run start and apply aborts the entire result;
- malformed output or one invalid cross-reference writes no scientific rows;
- retry is idempotent.

**Step 3: Implement the extraction boundary**

Define an `AiExtractor` protocol that accepts a protected PDF reference and returns only the normalized payload. Implement a first `legacy_pipeline` adapter for the selected pilot's existing machine-generated artifacts so the storage/UI path can be tested without coupling the database to one model provider. A future live PDF model adapter must implement the same contract.

**Step 4: Implement Run state and Celery execution**

Store `queued`, `running`, `succeeded`, `failed`, or `superseded`, plus engine/version and safe error summary. Do not persist confidence. Migration `0023` also adds the deferred `change_events.ai_run_id -> ai_extraction_runs.id` foreign key. Apply the complete payload under a locked Workspace version in one PostgreSQL transaction.

**Step 5: Implement Admin trigger and status UI**

The button must be disabled after human edits. Display queued/running/succeeded/failed state and safe retry; never present candidate rankings.

**Step 6: Run backend and frontend AI tests**

```bash
cd leadtrace/backend
../../.venv/bin/pytest tests/ai_prefill -v
cd ../frontend
npm test -- tests/ai-prefill.spec.ts
npx playwright test e2e/paper-centric-ai-prefill.spec.ts
```

Expected: PASS, including the no-overwrite race test.

**Step 7: Commit**

```bash
git add leadtrace/backend/migrations/versions/0023_ai_prefill_runs.py \
  leadtrace/backend/app/ai_prefill leadtrace/backend/app/worker.py \
  leadtrace/backend/app/main.py leadtrace/backend/app/config.py \
  leadtrace/backend/app/workspaces/models.py \
  leadtrace/backend/migrations/env.py leadtrace/backend/tests/ai_prefill \
  leadtrace/frontend/src/admin leadtrace/frontend/src/v2 \
  leadtrace/frontend/tests/ai-prefill.spec.ts \
  leadtrace/frontend/e2e/paper-centric-ai-prefill.spec.ts
git commit -m "feat: add non-overwriting AI paper prefill"
```

### Task 18: Retire Legacy Product Surfaces and Run Full Regression

**Files:**

- Modify: `leadtrace/backend/app/main.py`
- Modify: `leadtrace/frontend/src/app/router.ts`
- Modify: `leadtrace/frontend/src/app/AppShell.vue`
- Modify: `leadtrace/backend/tests/security/test_route_permission_matrix.py`
- Delete or replace: obsolete `/api/v1` domain tests under `leadtrace/backend/tests/imports`, `leadtrace/backend/tests/releases`, `leadtrace/backend/tests/revisions`, and legacy review/science route tests superseded by v2 coverage
- Delete or replace: legacy frontend tests for Changesets, Imports, Releases, Molecule Proposals, and generic Visual Objects superseded by v2 tests
- Create: `docs/acceptance/leadtrace-paper-centric-pilot.md`
- Modify: `leadtrace/README.md`

**Step 1: Strengthen the final route-surface test**

Assert that only the intentionally retained authentication, users, generic asset, audit/health/metrics routes and `/api/v2` product/document routes are registered. Legacy scientific `/api/v1` routes have been absent since Task 1 and must still return 404.

**Step 2: Remove dead legacy modules and visible pages**

Delete now-unreferenced import/revision/release/legacy-review/visual-object/proposal code and remove its visible frontend pages. Do not delete the top-level `dashboard/` application or anything under `source_pdfs/`. Remove only dead LeadTrace product surfaces and tests whose contracts are intentionally replaced, and prove replacement coverage exists before deleting each old test.

**Step 3: Re-run the complete backend suite**

```bash
cd leadtrace/backend
../../.venv/bin/pytest -v
```

Expected: PASS with no skipped replacement tests and no import errors from retired models.

**Step 4: Run frontend unit, type, build, and E2E suites**

```bash
cd leadtrace/frontend
npm test
npm run typecheck
npm run build
npx playwright test
```

Expected: PASS.

**Step 5: Run static and migration verification**

```bash
git diff --check
cd leadtrace/backend
../../.venv/bin/python -m alembic -c alembic.ini upgrade head --sql >/tmp/leadtrace-redesign-migration.sql
../../.venv/bin/python -m app.cli.audit verify
```

Expected: commands exit 0. Inspect the offline SQL for unexpected absolute paths, secrets, or data-dependent destructive targets.

**Step 6: Write the acceptance runbook**

Document pilot import dry run/apply, Reviewer creation, assignment, AI prefill option, manual review, Admin approval, backup, rollback by database restore, and the explicit no-migration-on-live guard.

**Step 7: Commit**

```bash
git add -A leadtrace docs/acceptance/leadtrace-paper-centric-pilot.md
git commit -m "refactor: cut over LeadTrace to paper-centric workflow"
```

### Task 19: Verify the Real 20-Paper Pilot and Prepare Cutover

**Files:**

- Modify only if evidence requires correction: `docs/pilot/2026-09-15-volume67-issue5-first20.json`
- Create: `docs/acceptance/leadtrace-paper-centric-pilot-results.md`
- Modify: `leadtrace/ops/cutover/preflight.py`
- Test: `leadtrace/backend/tests/ops/test_paper_centric_preflight.py`

**Step 1: Verify a backup before touching any acceptance database**

Use the existing PostgreSQL/asset backup scripts and verifier. Record backup ID and hashes in the sanitized acceptance results; never record database URLs, passwords, or absolute Source paths.

**Step 2: Create a separate acceptance database and asset root**

Run migrations and import there first. Do not migrate `leadtrace_acceptance` in place for the initial trial.

**Step 3: Dry-run and apply the real Pilot Manifest**

```bash
cd leadtrace/backend
LEADTRACE_DATABASE_URL='<isolated-acceptance-url>' \
  ../../.venv/bin/python -m app.cli.import_pilot \
  --manifest ../../docs/pilot/2026-09-15-volume67-issue5-first20.json \
  --source-root "$LEADTRACE_PILOT_SOURCE_ROOT" --dry-run
LEADTRACE_DATABASE_URL='<isolated-acceptance-url>' \
  ../../.venv/bin/python -m app.cli.import_pilot \
  --manifest ../../docs/pilot/2026-09-15-volume67-issue5-first20.json \
  --source-root "$LEADTRACE_PILOT_SOURCE_ROOT" --apply
```

Expected: 20 verified PDFs, 20 PaperSources, 20 Papers, no duplicate hash/path, and zero scientific rows before assignment.

**Step 4: Execute both required end-to-end workflows**

Complete and record:

1. one fully manual Paper from assignment through approval;
2. one AI-prefilled Paper edited by Reviewer through approval;
3. one Admin request-changes and resubmission cycle;
4. one `not_reported` empty section;
5. one invalid Structure and one missing-Evidence submission blocker;
6. one forced AI/Reviewer version race that leaves human data intact.

**Step 5: Run visual verification**

Use Playwright screenshots at desktop and mobile widths. Check that PDF canvas, Ketcher, RDKit image, Lineage graph, tables, dialogs, status bar, and long titles do not overlap or shift. Verify PDF canvas and structure images have nonblank pixel content.

**Step 6: Verify backup restoration of the pilot**

Restore the acceptance database and managed assets to separate targets. Recompute 20-Paper counts, current Published Paper hashes, Source hashes, Change Event counts, Submission hashes, and AI race result.

**Step 7: Add preflight assertions and results**

Preflight must require schema head, exactly 20 pilot Papers, valid Source hashes, one enabled Admin, no orphan science rows, valid immutable-history triggers, and successful manual/AI acceptance evidence.

**Step 8: Run final verification**

```bash
git diff --check
cd leadtrace/backend && ../../.venv/bin/pytest -v
cd ../frontend && npm test && npm run build && npx playwright test
```

Expected: all commands exit 0. Do not repoint `:8876` until this evidence is recorded and reviewed.

**Step 9: Commit**

```bash
git add docs/acceptance/leadtrace-paper-centric-pilot-results.md \
  docs/pilot/2026-09-15-volume67-issue5-first20.json \
  leadtrace/ops/cutover/preflight.py \
  leadtrace/backend/tests/ops/test_paper_centric_preflight.py
git commit -m "test: verify twenty-paper LeadTrace pilot"
```

## Final Completion Gate

Before proposing production cutover, verify all of the following from fresh command output:

- Backend pytest suite passes against a dedicated PostgreSQL `_test` database.
- Frontend unit tests, TypeScript check, production build, and Playwright suite pass.
- Alembic head matches the application and the migration refuses nonempty legacy business data.
- Pilot dry run and apply both report exactly 20 unique Source PDFs and Papers.
- Manual and AI-prefilled Reviewer-to-Admin paths both complete.
- Each Compound has zero or one current Structure; no Proposal/confidence storage exists.
- All human and AI edits have immutable Change Events.
- Submission and Published Paper hashes survive backup/restore.
- Unassigned Reviewers and formal-data readers cannot access draft Workspaces.
- `source_pdfs/` remains unchanged and the legacy Dashboard is not part of the LeadTrace migration.
- The running `:8876` service is changed only during an explicitly approved cutover window.
