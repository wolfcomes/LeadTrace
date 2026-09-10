# LeadTrace Professional Platform Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a LAN-hosted, professional LeadTrace platform that preserves the current scientific dataset, separates Visitor/Reviewer/Admin access, supports protected PDF and molecule-image review, and publishes only approved, versioned, auditable changes.

**Architecture:** Add a new `leadtrace/` modular monolith beside the existing read-only Dashboard. FastAPI and PostgreSQL own authentication, revisions, reviews, releases, audit data, and controlled asset metadata; Vue 3 provides published-data and review interfaces; Redis/Celery performs idempotent PDF/RDKit/import/export work; Nginx exposes one HTTPS LAN port and transfers authorized files. The existing CSV/JSON/PDF/PNG tree remains immutable migration input and the old Dashboard remains a read-only fallback until cutover.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy 2, Alembic, Psycopg 3, PostgreSQL 16, Celery 5, Redis 7, RDKit, Vue 3, TypeScript, Vite, Vue Router, Pinia, TanStack Query for Vue, Zod, PDF.js, SVG/Konva, Vitest, Playwright, Nginx, Docker Compose.

---

## Execution Rules and Safety Gates

1. Do not begin implementation until the user explicitly approves execution.
2. The workspace is not currently a Git repository. Task 1 establishes a safe
   baseline before feature work. Do not initialize Git or move source data
   during the planning turn.
3. After the baseline commit, create a dedicated Git worktree for implementation
   using `superpowers:using-git-worktrees`.
4. Use `superpowers:test-driven-development` for every feature or bug fix.
5. Use `superpowers:systematic-debugging` for any unexpected failure.
6. Before claiming a milestone complete, use
   `superpowers:verification-before-completion` and capture fresh output.
7. Before merging or cutting over, use `superpowers:requesting-code-review` and
   `superpowers:finishing-a-development-branch`.
8. Never write tests or application output into
   `source_pdfs/分子修改提取_2024_JMC`.
9. Never move, rename, overwrite, or delete existing PDF/CSV/JSON/PNG files as
   part of baseline import.
10. Never lower the current scientific rules to make a migration or test pass.
11. Each task ends with its focused tests, the relevant regression suite, and a
    small commit. Do not combine unrelated tasks into one commit.

## Fixed Baseline and Acceptance Counts

The initial imported release must reconcile through real CSV/JSON parsing, not
line counts:

```text
Corpus Papers                  672
Lineage Papers                 138
Lineages                       193
Compound entities            4,301
Lineage edges                4,144
Activity rows                  620
Complete structures          4,012
structure_confirmed          4,011
Missing/non-unique             289
Pair-ready edges             1,730
Papers with pair-ready          131
```

Integrity expectations:

```text
self-loops                         0
duplicate directed edges          0
unresolved pair-ready edges       0
dangling entity references        0
dangling evidence references      0
invalid pair endpoints            0
published missing/corrupt assets  0
```

## Planned Repository Layout

```text
leadtrace/
├── backend/
│   ├── app/
│   ├── migrations/
│   ├── tests/
│   ├── alembic.ini
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   ├── tests/
│   ├── e2e/
│   └── package.json
├── deploy/
│   ├── compose.yaml
│   ├── nginx/
│   └── env/
├── ops/
│   ├── baseline/
│   ├── backup/
│   └── restore/
└── README.md
```

## Milestone A: Protect the Existing System

### Task 1: Freeze, inventory, and version the current baseline

**Files:**

- Create: `.gitignore`
- Create: `leadtrace/ops/baseline/build_manifest.py`
- Create: `leadtrace/ops/baseline/verify_manifest.py`
- Create: `leadtrace/ops/baseline/expected_aggregate.json`
- Create: `leadtrace/ops/baseline/README.md`
- Create: `leadtrace/backend/tests/baseline/test_source_manifest.py`
- Create: `docs/baseline/2026-09-10-source-manifest.json` (generated)
- Reference: `source_pdfs/分子修改提取_2024_JMC/09_paper_review/auto_fill/compound_lineage_summary.json`

**Step 1: Write a failing source-manifest test**

Test that the manifest builder:

- accepts explicit source roots;
- records relative path, byte size, modification timestamp, SHA-256, and media
  category;
- excludes virtual environments, caches, logs, and temporary files;
- never writes below an input source root;
- emits a deterministic ordering.

```python
def test_manifest_is_deterministic_and_read_only(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    original = source / "paper.pdf"
    original.write_bytes(b"%PDF-test")
    output = tmp_path / "manifest.json"

    build_manifest([source], output)
    first = output.read_bytes()
    before = original.stat()
    build_manifest([source], output)

    assert output.read_bytes() == first
    assert original.stat().st_mtime_ns == before.st_mtime_ns
    assert original.read_bytes() == b"%PDF-test"
```

**Step 2: Run the test and verify failure**

Run:

```bash
pytest -q leadtrace/backend/tests/baseline/test_source_manifest.py
```

Expected: collection or import failure because the baseline tooling does not
exist.

**Step 3: Implement the manifest builder and verifier**

Use streaming SHA-256 reads, explicit allowlisted roots, normalized relative
keys, and atomic output. `verify_manifest.py` must return nonzero and print a
machine-readable difference when a source is missing, changed, or unexpected.

**Step 4: Create a production-safe `.gitignore`**

Ignore at minimum:

```gitignore
.venv*/
__pycache__/
.pytest_cache/
node_modules/
dist/
.env
*.log
leadtrace-data/
leadtrace-backups/
source_pdfs/**/*.pdf
source_pdfs/**/molecule_pair_structures/
source_pdfs/**/generated_structures/
```

Before the first commit, run `git status --short` and verify that no original
PDF, secret, virtual environment, generated image tree, database directory, or
backup is staged.

**Step 5: Record expected aggregate counts**

Write `expected_aggregate.json` with the fixed baseline counts and integrity
expectations from this plan. Read the current summary with `json.load`; do not
derive evidence counts with `wc -l`.

**Step 6: Generate and verify the source manifest**

Run:

```bash
python leadtrace/ops/baseline/build_manifest.py \
  --workspace-root /data/home/zhangzhiyong/lead_optimization_collection \
  --output docs/baseline/2026-09-10-source-manifest.json
python leadtrace/ops/baseline/verify_manifest.py \
  docs/baseline/2026-09-10-source-manifest.json
```

Expected: verifier prints `changed=0 missing=0 unexpected=0`.

**Step 7: Run the legacy verification before versioning**

Run:

```bash
PYTHONPATH=source_pdfs/分子修改提取_2024_JMC/scripts \
  pytest -q source_pdfs/分子修改提取_2024_JMC/tests
PYTHONPATH=. pytest -q dashboard/tests/test_dashboard_server.py
```

Expected baseline from the latest source-audit report: 323 lineage/structure
tests and 69 Dashboard tests pass. If counts have legitimately changed since
the report, stop and reconcile them rather than editing the plan silently.

**Step 8: Initialize and commit only after user execution approval**

Run:

```bash
git init
git add .gitignore dashboard docs leadtrace/ops leadtrace/backend/tests \
  source_pdfs/分子修改提取_2024_JMC/README.md \
  source_pdfs/分子修改提取_2024_JMC/scripts \
  source_pdfs/分子修改提取_2024_JMC/tests
git status --short
git commit -m "chore: establish LeadTrace migration baseline"
```

Expected: no large original or derived data files are staged. After the commit,
create a dedicated worktree before Task 2.

### Task 2: Prevent tests from writing to production data

**Files:**

- Modify: `dashboard/tests/test_dashboard_server.py`
- Modify: `source_pdfs/分子修改提取_2024_JMC/tests/conftest.py`
- Modify: affected tests under `source_pdfs/分子修改提取_2024_JMC/tests/`
- Create: `leadtrace/backend/tests/baseline/test_legacy_test_isolation.py`

**Step 1: Write a failing isolation guard**

Record hashes of the authoritative summary, entity, edge, evidence, activity,
and confirmed-structure outputs before invoking a representative legacy test.
Assert that all hashes remain identical afterward.

**Step 2: Run the guard and identify every production write**

Run:

```bash
pytest -q leadtrace/backend/tests/baseline/test_legacy_test_isolation.py -vv
```

Expected: fail if a test writes to `09_paper_review/auto_fill`, including the
known risk around `molecule_ocr_variant_summary.json`.

**Step 3: Inject temporary output roots into legacy tests**

Add fixtures that monkeypatch every default output path to `tmp_path`. Change
production scripts only when necessary to accept an explicit output root;
preserve existing CLI defaults for normal pipeline use.

**Step 4: Run the full old suites behind manifest checks**

Run:

```bash
python leadtrace/ops/baseline/verify_manifest.py \
  docs/baseline/2026-09-10-source-manifest.json
PYTHONPATH=source_pdfs/分子修改提取_2024_JMC/scripts \
  pytest -q source_pdfs/分子修改提取_2024_JMC/tests
PYTHONPATH=. pytest -q dashboard/tests/test_dashboard_server.py
python leadtrace/ops/baseline/verify_manifest.py \
  docs/baseline/2026-09-10-source-manifest.json
```

Expected: both manifest checks report zero changes and all legacy tests pass.

**Step 5: Commit**

```bash
git add dashboard/tests source_pdfs/分子修改提取_2024_JMC/tests \
  source_pdfs/分子修改提取_2024_JMC/scripts \
  leadtrace/backend/tests/baseline
git commit -m "test: isolate legacy suites from production data"
```

## Milestone B: Application and Security Foundation

### Task 3: Scaffold the new application and local deployment

**Files:**

- Create: `leadtrace/backend/pyproject.toml`
- Create: `leadtrace/backend/app/__init__.py`
- Create: `leadtrace/backend/app/main.py`
- Create: `leadtrace/backend/app/config.py`
- Create: `leadtrace/backend/app/health/router.py`
- Create: `leadtrace/backend/tests/health/test_health.py`
- Create: `leadtrace/frontend/package.json`
- Create: `leadtrace/frontend/tsconfig.json`
- Create: `leadtrace/frontend/vite.config.ts`
- Create: `leadtrace/frontend/src/main.ts`
- Create: `leadtrace/frontend/src/App.vue`
- Create: `leadtrace/deploy/compose.yaml`
- Create: `leadtrace/deploy/nginx/nginx.conf`
- Create: `leadtrace/deploy/env/example.env`
- Create: `leadtrace/README.md`

**Step 1: Write failing liveness and readiness tests**

Require `/health/live` to return 200 when the process runs. Require
`/health/ready` to return 503 when the database or required asset root is
unavailable, rather than returning a false healthy result.

**Step 2: Run focused tests**

```bash
cd leadtrace/backend
pytest -q tests/health/test_health.py
```

Expected: fail because the application is absent.

**Step 3: Implement the minimal application and typed configuration**

`config.py` must reject production startup when database URL, session secret,
allowed hosts, or asset root is missing or unsafe. Do not put usable production
secrets in `example.env`.

**Step 4: Scaffold Vue and a typed API health call**

Render application, loading, ready, unavailable, 403, 404, and generic error
states. Do not build business pages yet.

**Step 5: Add Compose and Nginx**

Compose services: `nginx`, `web`, `worker`, `postgres`, `redis`, `frontend-dev`
for development. Only Nginx publishes a host port. PostgreSQL 5432, Redis 6379,
and FastAPI 8000 remain internal.

**Step 6: Verify the stack**

```bash
docker compose -f leadtrace/deploy/compose.yaml config
docker compose -f leadtrace/deploy/compose.yaml up -d --build
curl -fsS http://127.0.0.1:8876/health/live
curl -fsS http://127.0.0.1:8876/health/ready
```

Expected during development: valid Compose config and both health endpoints
return structured JSON. Port 8876 is the temporary development port; the final
LAN port is selected at deployment without colliding with the old port 8765.

**Step 7: Commit**

```bash
git add leadtrace
git commit -m "feat: scaffold LeadTrace application stack"
```

### Task 4: Add PostgreSQL, migrations, and transaction infrastructure

**Files:**

- Create: `leadtrace/backend/app/database.py`
- Create: `leadtrace/backend/app/db/base.py`
- Create: `leadtrace/backend/migrations/env.py`
- Create: `leadtrace/backend/migrations/script.py.mako`
- Create: `leadtrace/backend/alembic.ini`
- Create: `leadtrace/backend/tests/db/test_database.py`
- Create: `leadtrace/backend/tests/db/test_migrations.py`

**Step 1: Write failing PostgreSQL integration tests**

Test transaction rollback, connection health, UTC timestamps, UUID/typed IDs,
JSONB support, and migration from an empty database to `head`. Mark the suite
as PostgreSQL-only; do not substitute SQLite.

**Step 2: Run the tests against the Compose test database**

```bash
cd leadtrace/backend
pytest -q tests/db/test_database.py tests/db/test_migrations.py
```

Expected: fail because database infrastructure and migrations are absent.

**Step 3: Implement database sessions and Alembic**

Provide request-scoped SQLAlchemy sessions, explicit transaction contexts, a
bounded connection pool, and startup schema-version validation.

**Step 4: Verify migrations in both directions where safe**

```bash
cd leadtrace/backend
alembic upgrade head
alembic current
pytest -q tests/db
```

Expected: schema at head and all database tests pass.

**Step 5: Commit**

```bash
git add leadtrace/backend
git commit -m "feat: add PostgreSQL migration foundation"
```

### Task 5: Implement users, passwords, sessions, and Admin CLI

**Files:**

- Create: `leadtrace/backend/app/security/passwords.py`
- Create: `leadtrace/backend/app/security/sessions.py`
- Create: `leadtrace/backend/app/security/csrf.py`
- Create: `leadtrace/backend/app/auth/models.py`
- Create: `leadtrace/backend/app/auth/schemas.py`
- Create: `leadtrace/backend/app/auth/service.py`
- Create: `leadtrace/backend/app/auth/router.py`
- Create: `leadtrace/backend/app/users/models.py`
- Create: `leadtrace/backend/app/users/service.py`
- Create: `leadtrace/backend/app/users/router.py`
- Create: `leadtrace/backend/app/cli/users.py`
- Create: `leadtrace/backend/migrations/versions/0001_identity.py`
- Create: `leadtrace/backend/tests/auth/`

**Step 1: Write failing password and session tests**

Test Argon2id hashing, no plaintext persistence, first-login password change,
session rotation, eight-hour idle expiry, 24-hour absolute expiry, revocation,
disablement, role change, CSRF, and generic login errors.

**Step 2: Write failing Admin lifecycle tests**

Test creation of Visitor/Reviewer/Admin, no self-registration route, reset via
one-time password, forced logout, disabled login rejection, and prevention of
disabling the last active Admin.

**Step 3: Run tests**

```bash
cd leadtrace/backend
pytest -q tests/auth
```

Expected: fail before implementation.

**Step 4: Implement identity tables and services**

Use an opaque, random session token; persist only a keyed hash of the token.
Set the cookie `HttpOnly` and `SameSite=Strict`; set `Secure` whenever HTTPS is
enabled. Do not return password hashes or session records from user schemas.

**Step 5: Implement safe CLI commands**

Commands must accept passwords through an interactive prompt or protected
secret file, never a visible command-line argument.

**Step 6: Verify**

```bash
cd leadtrace/backend
pytest -q tests/auth
python -m app.cli.users --help
```

Expected: all auth tests pass and CLI documents create/reset/disable/revoke
operations.

**Step 7: Commit**

```bash
git add leadtrace/backend
git commit -m "feat: add secure local accounts and sessions"
```

### Task 6: Enforce role and resource-level permissions

**Files:**

- Create: `leadtrace/backend/app/security/permissions.py`
- Create: `leadtrace/backend/app/security/policies.py`
- Create: `leadtrace/backend/tests/security/test_permissions.py`
- Create: `leadtrace/backend/tests/security/test_hidden_resources.py`

**Step 1: Encode the approved permission matrix as parameterized failing tests**

Cover anonymous, Visitor, Reviewer, and Admin for published data, full PDFs,
assigned drafts, other Reviewers' drafts, submission, approval, publication,
rollback, user management, unpublished export, and audit access.

**Step 2: Run tests and verify failure**

```bash
cd leadtrace/backend
pytest -q tests/security/test_permissions.py tests/security/test_hidden_resources.py
```

**Step 3: Implement policy objects and FastAPI dependencies**

Resource policies must consider role, Paper assignment, changeset owner, object
state, and published visibility. Unauthorized unpublished IDs should usually
return a safe 404; authenticated but disallowed known actions return 403.

**Step 4: Verify no route relies on frontend hiding**

Run the route-permission matrix test across every registered `/api/v1` route.

**Step 5: Commit**

```bash
git add leadtrace/backend/app/security leadtrace/backend/tests/security
git commit -m "feat: enforce role and resource authorization"
```

## Milestone C: Assets, Domains, and Baseline Migration

### Task 7: Build the controlled asset registry and read-only source scanner

**Files:**

- Create: `leadtrace/backend/app/assets/models.py`
- Create: `leadtrace/backend/app/assets/schemas.py`
- Create: `leadtrace/backend/app/assets/repository.py`
- Create: `leadtrace/backend/app/assets/service.py`
- Create: `leadtrace/backend/app/assets/storage.py`
- Create: `leadtrace/backend/app/assets/scanner.py`
- Create: `leadtrace/backend/app/assets/router.py`
- Create: `leadtrace/backend/migrations/versions/0002_assets.py`
- Create: `leadtrace/backend/tests/assets/`

**Step 1: Write failing classification and integrity tests**

Cover article PDFs, SI PDFs/tables/archives, external sources, page renders,
evidence crops, OCSR inputs/proposals, reviewed crops, RDKit structures, pair
panels, import reports, exports, staging, and quarantine.

**Step 2: Write failing traversal and immutability tests**

Reject arbitrary paths, `..`, symlink escapes, MIME mismatches, and changed
hashes. Assert scanning never alters source bytes or metadata.

**Step 3: Implement `LocalAssetStore` and registry**

Use an internal `storage_key`, never a client-supplied absolute path. Store
SHA-256, byte size, MIME, dimensions/page count, access level, import batch,
derivation metadata, and integrity status.

**Step 4: Implement resumable scanning**

The scanner must checkpoint by source key and content hash, tolerate Chinese
paths, spaces, parentheses, Unicode filenames, and duplicates, and emit a
machine-readable report.

**Step 5: Run focused tests**

```bash
cd leadtrace/backend
pytest -q tests/assets
```

Expected: all asset tests pass.

**Step 6: Commit**

```bash
git add leadtrace/backend/app/assets leadtrace/backend/tests/assets \
  leadtrace/backend/migrations
git commit -m "feat: register and protect file assets"
```

### Task 8: Add Papers, scientific entities, and immutable revisions

**Files:**

- Create: `leadtrace/backend/app/revisions/models.py`
- Create: `leadtrace/backend/app/revisions/service.py`
- Create: `leadtrace/backend/app/papers/models.py`
- Create: `leadtrace/backend/app/compounds/models.py`
- Create: `leadtrace/backend/app/structures/models.py`
- Create: `leadtrace/backend/app/evidence/models.py`
- Create: `leadtrace/backend/app/activities/models.py`
- Create: `leadtrace/backend/app/lineages/models.py`
- Create: `leadtrace/backend/app/visual_objects/models.py`
- Create: `leadtrace/backend/migrations/versions/0003_scientific_domains.py`
- Create: `leadtrace/backend/tests/domains/`

**Step 1: Write failing schema constraint tests**

Require stable object IDs, unique Paper-local identities, immutable published
revisions, unique per-object revision numbers, one current published revision,
valid foreign keys, normalized Region bounds, non-self lineage edges, and
separate structure/evidence/activity states.

**Step 2: Write failing label regression tests**

Preserve `26a`, `26a′`, `26a'`, stereochemical qualifiers, and letter suffixes
as distinct Paper-local identities according to the existing rules.

**Step 3: Implement domain tables and revision primitives**

Every versioned object gets a stable identity table plus an immutable revision
table with predecessor, changeset, actor, reason, content hash, searchable
columns, and JSONB snapshot.

**Step 4: Verify migrations and constraints**

```bash
cd leadtrace/backend
alembic upgrade head
pytest -q tests/domains
```

**Step 5: Commit**

```bash
git add leadtrace/backend/app leadtrace/backend/tests/domains \
  leadtrace/backend/migrations
git commit -m "feat: model versioned scientific domains"
```

### Task 9: Implement the staged baseline importer and exact reconciliation

**Files:**

- Create: `leadtrace/backend/app/imports/models.py`
- Create: `leadtrace/backend/app/imports/service.py`
- Create: `leadtrace/backend/app/imports/readers/manifest.py`
- Create: `leadtrace/backend/app/imports/readers/lineages.py`
- Create: `leadtrace/backend/app/imports/readers/structures.py`
- Create: `leadtrace/backend/app/imports/readers/visuals.py`
- Create: `leadtrace/backend/app/imports/reconcile.py`
- Create: `leadtrace/backend/app/cli/import_baseline.py`
- Create: `leadtrace/backend/migrations/versions/0004_imports.py`
- Create: `leadtrace/backend/tests/imports/`

**Step 1: Write failing fixture-level importer tests**

For small fixtures, assert preservation of original IDs, source file, source
row locator, raw values, normalized values, import batch, and source hash.
Assert rerunning the same batch is idempotent.

**Step 2: Write failing full-baseline reconciliation test**

Run the importer against the current workspace in read-only mode and compare
all fixed counts and all zero-integrity expectations. Parse CSV with
`csv.DictReader` so quoted newlines do not inflate logical rows.

**Step 3: Implement staging-first import**

Each reader writes to import staging, validates IDs and relationships, produces
a difference report, and only then creates immutable baseline revisions and an
`imported_baseline` release candidate. Failure must leave the current release
pointer unchanged.

**Step 4: Implement exact asset linkage**

Link existing PDFs, SI files, crops, and generated structures through registered
asset IDs. Missing or ambiguous files are reported; they are not guessed from
basenames alone.

**Step 5: Run the full dry run**

```bash
cd leadtrace/backend
python -m app.cli.import_baseline \
  --source-root ../../source_pdfs/分子修改提取_2024_JMC \
  --dry-run \
  --report ../../docs/baseline/leadtrace-import-dry-run.json
pytest -q tests/imports
```

Expected: the report matches every fixed count and reports all integrity
violations as zero.

**Step 6: Apply into a disposable database and compare twice**

```bash
cd leadtrace/backend
python -m app.cli.import_baseline \
  --source-root ../../source_pdfs/分子修改提取_2024_JMC \
  --apply
python -m app.cli.import_baseline \
  --source-root ../../source_pdfs/分子修改提取_2024_JMC \
  --apply
```

Expected: first run creates one baseline candidate; second run creates no
duplicate identities or revisions.

**Step 7: Commit**

```bash
git add leadtrace/backend/app/imports leadtrace/backend/tests/imports \
  leadtrace/backend/migrations docs/baseline
git commit -m "feat: import and reconcile the scientific baseline"
```

## Milestone D: Published API and Visitor Experience

### Task 10: Add release-scoped published query APIs

**Files:**

- Create: `leadtrace/backend/app/releases/models.py`
- Create: `leadtrace/backend/app/releases/service.py`
- Create: `leadtrace/backend/app/papers/repository.py`
- Create: `leadtrace/backend/app/papers/service.py`
- Create: `leadtrace/backend/app/papers/router.py`
- Create: `leadtrace/backend/app/search/service.py`
- Create: `leadtrace/backend/app/api/errors.py`
- Create: `leadtrace/backend/migrations/versions/0005_releases.py`
- Create: `leadtrace/backend/tests/api/test_published_papers.py`
- Create: `leadtrace/backend/tests/api/test_overview.py`

**Step 1: Write failing release-isolation tests**

Create a published revision and a newer draft. Assert Visitor APIs return only
the published revision and ignore caller-supplied draft/revision parameters.

**Step 2: Write failing overview and pagination tests**

Require explicit denominators, current release ID, stable manifest order, 20
Papers per default page, URL-compatible filters, and separate corpus, lineage,
relation, structure, pair, and human-review metrics.

**Step 3: Implement repositories and services**

Use database views or release-item joins that make current-release resolution
explicit. Add PostgreSQL indexes for DOI, Paper ID, normalized title, compound
label, relation status, structure status, task/review status, and full-text
search.

**Step 4: Standardize API responses and errors**

Every response includes a request ID; list responses include pagination and
release metadata. Errors never contain tracebacks or absolute paths.

**Step 5: Verify**

```bash
cd leadtrace/backend
pytest -q tests/api/test_published_papers.py tests/api/test_overview.py
```

Expected: Visitor receives current release data only and baseline counts match.

**Step 6: Commit**

```bash
git add leadtrace/backend
git commit -m "feat: expose release-scoped published APIs"
```

### Task 11: Build the frontend shell, login flow, and role navigation

**Files:**

- Create: `leadtrace/frontend/src/api/client.ts`
- Create: `leadtrace/frontend/src/api/schema.ts`
- Create: `leadtrace/frontend/src/auth/store.ts`
- Create: `leadtrace/frontend/src/auth/LoginPage.vue`
- Create: `leadtrace/frontend/src/auth/ChangePasswordPage.vue`
- Create: `leadtrace/frontend/src/app/router.ts`
- Create: `leadtrace/frontend/src/app/AppShell.vue`
- Create: `leadtrace/frontend/src/i18n/zh-CN.ts`
- Create: `leadtrace/frontend/src/styles/tokens.css`
- Create: `leadtrace/frontend/tests/auth.spec.ts`
- Create: `leadtrace/frontend/tests/navigation.spec.ts`

**Step 1: Write failing component tests**

Test generic login errors, first-login password routing, expired-session return
to login, and exact navigation differences for Visitor, Reviewer, and Admin.

**Step 2: Run tests**

```bash
cd leadtrace/frontend
npm test -- --run tests/auth.spec.ts tests/navigation.spec.ts
```

Expected: fail because pages and stores are absent.

**Step 3: Implement generated/validated API types**

Generate TypeScript types from OpenAPI and validate high-value runtime payloads
with Zod. Centralize 401, 403, 409, 422, and 503 handling.

**Step 4: Implement professional shell and accessible login**

Use semantic labels, visible keyboard focus, WCAG AA contrast, explicit loading
and error states, and Chinese UI strings from the i18n module rather than
hard-coded component strings.

**Step 5: Verify**

```bash
cd leadtrace/frontend
npm run typecheck
npm test -- --run
npm run build
```

Expected: typecheck, component tests, and production build pass.

**Step 6: Commit**

```bash
git add leadtrace/frontend
git commit -m "feat: add authenticated role-aware frontend shell"
```

### Task 12: Build professional Visitor overview, Paper library, and details

**Files:**

- Create: `leadtrace/frontend/src/papers/OverviewPage.vue`
- Create: `leadtrace/frontend/src/papers/PaperLibraryPage.vue`
- Create: `leadtrace/frontend/src/papers/PaperDetailPage.vue`
- Create: `leadtrace/frontend/src/lineages/LineageView.vue`
- Create: `leadtrace/frontend/src/structures/MoleculePairCard.vue`
- Create: `leadtrace/frontend/src/evidence/EvidenceCard.vue`
- Create: `leadtrace/frontend/src/papers/QualitySummary.vue`
- Create: `leadtrace/frontend/tests/published-pages.spec.ts`
- Create: `leadtrace/frontend/e2e/visitor.spec.ts`

**Step 1: Write failing UI tests for metric semantics**

Assert the overview displays `138 / 672` lineage coverage and separate
relation/structure/pair/review metrics. Assert it does not use the legacy
16-path pilot as the project headline and does not show one aggregate
completion percentage.

**Step 2: Write failing Visitor end-to-end tests**

Test Paper search/filter persistence in the URL, Paper details, lineage
branches, explicit unresolved styling, confirmed RDKit drawings, evidence crop
viewing, and denial of full PDF access.

**Step 3: Implement the published pages**

Use server pagination. Display stable IDs and DOI in copyable form. Label image
types and statuses. Do not render a source screenshot as a final structure.
Do not render a fake pair for unresolved or invalid endpoints.

**Step 4: Verify**

```bash
cd leadtrace/frontend
npm test -- --run tests/published-pages.spec.ts
npx playwright test e2e/visitor.spec.ts
```

Expected: Visitor can browse the current release but cannot retrieve full PDFs
or unpublished revisions.

**Step 5: Commit**

```bash
git add leadtrace/frontend
git commit -m "feat: deliver professional published-data pages"
```

## Milestone E: Review and Approval Foundation

### Task 13: Implement review tasks and the immutable changeset state machine

**Files:**

- Create: `leadtrace/backend/app/reviews/models.py`
- Create: `leadtrace/backend/app/reviews/schemas.py`
- Create: `leadtrace/backend/app/reviews/state_machine.py`
- Create: `leadtrace/backend/app/reviews/service.py`
- Create: `leadtrace/backend/app/reviews/router.py`
- Create: `leadtrace/backend/migrations/versions/0006_reviews.py`
- Create: `leadtrace/backend/tests/reviews/test_state_machine.py`
- Create: `leadtrace/backend/tests/reviews/test_concurrency.py`

**Step 1: Write the complete state-transition matrix as failing tests**

Allow only:

```text
draft -> submitted
submitted -> changes_requested | rejected | approved
changes_requested -> new draft revision
approved -> published
published -> superseded
```

Submitted, rejected, approved, published, and superseded snapshots are
immutable.

**Step 2: Write failing ownership and scope tests**

Test assigned Reviewer access, own draft access, denial for unrelated drafts,
Admin reassignment, one-Paper changeset scope, and prohibition on Reviewer
self-approval.

**Step 3: Write failing optimistic-concurrency tests**

Two requests save the same expected version. Exactly one succeeds; the other
returns 409 with expected/current versions. No data is silently overwritten.

**Step 4: Implement models and transactional services**

Submission must lock the changeset, validate base release and state, generate
an immutable submitted snapshot, update the task, and write audit data in one
transaction.

**Step 5: Verify**

```bash
cd leadtrace/backend
pytest -q tests/reviews
```

Expected: all transition, ownership, and concurrency tests pass.

**Step 6: Commit**

```bash
git add leadtrace/backend
git commit -m "feat: add versioned review task and changeset workflow"
```

### Task 14: Add structured diffs, comments, and append-only audit events

**Files:**

- Create: `leadtrace/backend/app/revisions/diff.py`
- Create: `leadtrace/backend/app/reviews/comments.py`
- Create: `leadtrace/backend/app/audit/models.py`
- Create: `leadtrace/backend/app/audit/service.py`
- Create: `leadtrace/backend/app/audit/router.py`
- Create: `leadtrace/backend/migrations/versions/0007_audit.py`
- Create: `leadtrace/backend/tests/revisions/test_diff.py`
- Create: `leadtrace/backend/tests/audit/test_audit.py`

**Step 1: Write failing diff tests**

Cover scalar fields, long text, create/update/tombstone, bindings, Region
coordinates, SMILES, and lineage endpoints. Diff output must be deterministic
and must retain object IDs and revision IDs.

**Step 2: Write failing audit tests**

Require actor, action, target, Paper, changeset/release, timestamp, IP, request
ID, result, reason, and before/after hashes. Reject UPDATE and DELETE through
the application. Assert secrets are redacted.

**Step 3: Implement comments and resolution history**

Comments may target a changeset, change item, field, Region, compound,
structure, or edge. Resolving and reopening creates events; it does not erase
the original comment.

**Step 4: Add an audit hash chain**

Calculate each event hash from the prior hash and canonical event payload.
Provide an Admin-only verification command.

**Step 5: Verify and commit**

```bash
cd leadtrace/backend
pytest -q tests/revisions tests/audit
git add app tests migrations
git commit -m "feat: add structured review diffs and audit history"
```

### Task 15: Build Reviewer task, changeset, and submission UI

**Files:**

- Create: `leadtrace/frontend/src/review/tasks/TaskListPage.vue`
- Create: `leadtrace/frontend/src/review/changesets/ChangesetPage.vue`
- Create: `leadtrace/frontend/src/review/changesets/ChangesetDiff.vue`
- Create: `leadtrace/frontend/src/review/changesets/SubmissionPage.vue`
- Create: `leadtrace/frontend/src/review/autosave.ts`
- Create: `leadtrace/frontend/src/review/conflicts/ConflictResolver.vue`
- Create: `leadtrace/frontend/tests/review-workflow.spec.ts`

**Step 1: Write failing Reviewer workflow tests**

Test create/resume draft, visible autosave states, offline recovery buffer,
blocking validation, summary by domain, immutable submission, and 409 conflict
resolution.

**Step 2: Implement the smallest metadata/evidence vertical slice**

First support Paper metadata and evidence text edits through the entire draft,
submit, diff, and request-changes cycle. Do not start PDF tools until this slice
works end-to-end.

**Step 3: Verify with a two-Reviewer browser scenario**

```bash
cd leadtrace/frontend
npm test -- --run tests/review-workflow.spec.ts
npx playwright test e2e/review-minimal.spec.ts
```

Expected: draft changes do not affect Visitor; conflicts are explicit.

**Step 4: Commit**

```bash
git add leadtrace/frontend
git commit -m "feat: add Reviewer changeset workspace"
```

## Milestone F: Protected PDF and Visual Object Review

### Task 16: Add protected PDF streaming and document APIs

**Files:**

- Create: `leadtrace/backend/app/documents/service.py`
- Create: `leadtrace/backend/app/documents/router.py`
- Modify: `leadtrace/deploy/nginx/nginx.conf`
- Create: `leadtrace/backend/tests/documents/test_pdf_access.py`
- Create: `leadtrace/backend/tests/documents/test_range_requests.py`
- Create: `leadtrace/backend/tests/security/test_asset_paths.py`

**Step 1: Write failing permission and Range tests**

Visitor receives 403 for article/SI PDF bytes. Assigned Reviewer and Admin
receive valid metadata and byte ranges. Responses include safe ETag, length,
range, disposition, cache, and `nosniff` headers. No absolute path appears.

**Step 2: Implement authorize-then-transfer**

FastAPI validates Session, role, assignment, asset type, and integrity before
setting an internal Nginx transfer header. The internal storage location is not
externally routable.

**Step 3: Add sensitive access audit**

Record full-PDF views/downloads with actor, Paper, asset, IP, and request ID,
without logging the storage path.

**Step 4: Verify**

```bash
cd leadtrace/backend
pytest -q tests/documents tests/security/test_asset_paths.py
```

Expected: permissions, ranges, and path non-disclosure pass.

**Step 5: Commit**

```bash
git add leadtrace/backend leadtrace/deploy/nginx
git commit -m "feat: serve protected source PDFs"
```

### Task 17: Implement versioned PDF Regions and idempotent crop jobs

**Files:**

- Create: `leadtrace/backend/app/visual_objects/regions.py`
- Create: `leadtrace/backend/app/visual_objects/router.py`
- Create: `leadtrace/backend/app/jobs/models.py`
- Create: `leadtrace/backend/app/jobs/service.py`
- Create: `leadtrace/backend/app/jobs/tasks/crops.py`
- Create: `leadtrace/backend/migrations/versions/0008_regions_jobs.py`
- Create: `leadtrace/backend/tests/visual_objects/test_regions.py`
- Create: `leadtrace/backend/tests/jobs/test_crop_jobs.py`
- Create: `leadtrace/frontend/src/pdf-viewer/PdfReviewCanvas.vue`
- Create: `leadtrace/frontend/src/pdf-viewer/RegionOverlay.vue`
- Create: `leadtrace/frontend/tests/regions.spec.ts`

**Step 1: Write failing Region domain tests**

Test normalized coordinates, page bounds, positive size, rotation, creation,
move, resize, duplicate, split, tombstone, restore, and old/new overlay data.

**Step 2: Write failing crop-idempotency tests**

The same PDF hash, page, bounds, rotation, padding, DPI, and renderer version
must reuse one asset. A parameter change must create a new asset. Failure must
leave no registered valid partial asset.

**Step 3: Implement transactional Region revisions**

Region changes belong to a draft changeset and use expected versions. Original
PDFs and prior crop assets are immutable.

**Step 4: Implement the PDF.js canvas and SVG overlay**

Provide page thumbnails, search, page jump, zoom, rotation, rectangular Region
create/move/resize/duplicate, filters, selection, and normalized coordinate
conversion. Polygon support may follow only after rectangle acceptance passes.

**Step 5: Verify backend and frontend**

```bash
cd leadtrace/backend && pytest -q tests/visual_objects tests/jobs/test_crop_jobs.py
cd ../frontend && npm test -- --run tests/regions.spec.ts
```

Expected: Region history and crop reuse pass at multiple zoom levels.

**Step 6: Commit**

```bash
git add leadtrace/backend leadtrace/frontend
git commit -m "feat: add non-destructive PDF region review"
```

### Task 18: Implement molecule objects and many-to-many image/compound bindings

**Files:**

- Create: `leadtrace/backend/app/visual_objects/objects.py`
- Create: `leadtrace/backend/app/visual_objects/bindings.py`
- Create: `leadtrace/backend/app/visual_objects/relationships.py`
- Create: `leadtrace/backend/migrations/versions/0009_molecule_objects.py`
- Create: `leadtrace/backend/tests/visual_objects/test_objects.py`
- Create: `leadtrace/backend/tests/visual_objects/test_bindings.py`
- Create: `leadtrace/frontend/src/visual-objects/ObjectInspector.vue`
- Create: `leadtrace/frontend/src/visual-objects/CompoundBindings.vue`
- Create: `leadtrace/frontend/src/visual-objects/ImageBindings.vue`
- Create: `leadtrace/frontend/tests/molecule-objects.spec.ts`

**Step 1: Write the approved cardinalities as failing tests**

Require:

```text
one Region -> many objects
one object -> many Regions/assets
one object -> many compounds
one compound -> many objects
many objects -> one shared crop asset
```

Reject duplicate bindings but allow overlapping Regions and repeated display.

**Step 2: Write failing object-type and relation tests**

Cover all controlled object types and relations. Assert `shares_scaffold_with`,
`substituent_of`, or proximity does not create a lineage edge.

**Step 3: Implement explicit user actions**

Backend and UI distinguish:

- reuse image to create a new object;
- copy and adjust Region;
- attach another image to an object;
- bind several compounds to one object;
- create a new Paper-local compound with a reason.

**Step 4: Preserve labels exactly**

Binding data stores one label per row, optional label bbox, role, confidence,
note, and primary flag. Never flatten labels into a comma-separated field.

**Step 5: Verify and commit**

```bash
cd leadtrace/backend && pytest -q tests/visual_objects
cd ../frontend && npm test -- --run tests/molecule-objects.spec.ts
git add ../backend ../frontend
git commit -m "feat: support reusable molecule images and label bindings"
```

## Milestone G: Scientific Editors and Chemistry Quality

### Task 19: Add RDKit validation, drawing, and immutable structure assets

**Files:**

- Create: `leadtrace/backend/app/chemistry/validation.py`
- Create: `leadtrace/backend/app/chemistry/drawing.py`
- Create: `leadtrace/backend/app/jobs/tasks/structures.py`
- Create: `leadtrace/backend/app/structures/service.py`
- Create: `leadtrace/backend/app/structures/router.py`
- Create: `leadtrace/backend/tests/chemistry/`
- Create: `leadtrace/frontend/src/structures/StructureEditor.vue`
- Create: `leadtrace/frontend/src/structures/StructureComparison.vue`
- Create: `leadtrace/frontend/tests/structure-editor.spec.ts`

**Step 1: Port critical chemistry rules into failing tests**

Include valid/invalid parse, multiple components, salts, dummy atoms, radicals,
stereochemistry, non-unique experimental material, source mismatch, exact
component selection, and deterministic drawing keys. Copy intent from the
current lineage tests; do not depend on importing production scripts forever.

**Step 2: Implement typed validation output**

Return canonical/isomeric SMILES, formula, molecular weight, component count,
dummy/radical/stereo flags, parse messages, and structure-state eligibility.
Never return `structure_confirmed` based on parsing alone.

**Step 3: Implement idempotent drawing jobs**

Key drawings by canonical isomeric SMILES, drawing options, RDKit version, and
render version. Store source/drawing metadata and SHA-256.

**Step 4: Implement the SMILES editor**

Show parse status as "parseable" rather than "confirmed". Require source and
reason for changed structures. Show published/draft drawings side by side and
support non-unique, multi-component, constitution-only, mismatch, and rejected
states without forcing one isomeric SMILES.

**Step 5: Verify**

```bash
cd leadtrace/backend && pytest -q tests/chemistry
cd ../frontend && npm test -- --run tests/structure-editor.spec.ts
```

**Step 6: Commit**

```bash
git add leadtrace/backend leadtrace/frontend
git commit -m "feat: add source-aware RDKit structure review"
```

### Task 20: Add Evidence, Activity, Compound, and Lineage editors

**Files:**

- Create: `leadtrace/backend/app/evidence/service.py`
- Create: `leadtrace/backend/app/evidence/router.py`
- Create: `leadtrace/backend/app/activities/service.py`
- Create: `leadtrace/backend/app/activities/router.py`
- Create: `leadtrace/backend/app/compounds/service.py`
- Create: `leadtrace/backend/app/compounds/router.py`
- Create: `leadtrace/backend/app/lineages/validation.py`
- Create: `leadtrace/backend/app/lineages/service.py`
- Create: `leadtrace/backend/app/lineages/router.py`
- Create: `leadtrace/backend/tests/science/`
- Create: `leadtrace/frontend/src/evidence/EvidenceEditor.vue`
- Create: `leadtrace/frontend/src/activities/ActivityEditor.vue`
- Create: `leadtrace/frontend/src/compounds/CompoundEditor.vue`
- Create: `leadtrace/frontend/src/lineages/LineageEditor.vue`
- Create: `leadtrace/frontend/tests/scientific-editors.spec.ts`

**Step 1: Write failing scientific invariants**

Require explicit relations to bind evidence, unresolved relations to omit a
unique immediate parent, distinct parent/derived endpoints, valid Paper-local
references, no duplicate edge, no dangling deletion, and separate assay/metric/
value/unit/qualifier fields with original evidence text retained.

**Step 2: Implement pair readiness as a derived service**

It must return `eligible` plus a list of blocking codes. No request schema may
accept a client-controlled `pair_ready=true` value.

**Step 3: Implement draft CRUD through changesets**

All creates, updates, and tombstones require a draft changeset, expected
version, reason, and permission check. Direct update of published rows is
impossible at repository level.

**Step 4: Build table and graph Lineage editing**

Table view is the reliable bulk review tool; graph view is a synchronized
visual editor. Unresolved edges use non-confirmatory rendering. Bind evidence
through stable IDs.

**Step 5: Verify with legacy rules**

```bash
cd leadtrace/backend
pytest -q tests/science tests/chemistry tests/domains
PYTHONPATH=../../source_pdfs/分子修改提取_2024_JMC/scripts \
  pytest -q ../../source_pdfs/分子修改提取_2024_JMC/tests
cd ../frontend
npm test -- --run tests/scientific-editors.spec.ts
```

Expected: all new and legacy scientific tests pass.

**Step 6: Commit**

```bash
git add leadtrace/backend leadtrace/frontend
git commit -m "feat: add typed scientific review editors"
```

## Milestone H: Approval, Publication, Rollback, and Administration

### Task 21: Implement approval, atomic release, export, and rollback

**Files:**

- Create: `leadtrace/backend/app/approvals/service.py`
- Create: `leadtrace/backend/app/approvals/router.py`
- Create: `leadtrace/backend/app/releases/validation.py`
- Create: `leadtrace/backend/app/releases/export.py`
- Modify: `leadtrace/backend/app/releases/service.py`
- Create: `leadtrace/backend/tests/releases/`
- Create: `leadtrace/frontend/src/approvals/ApprovalCenterPage.vue`
- Create: `leadtrace/frontend/src/releases/ReleasePage.vue`
- Create: `leadtrace/frontend/src/releases/RollbackPage.vue`
- Create: `leadtrace/frontend/tests/approval-release.spec.ts`

**Step 1: Write failing approval tests**

Test Admin-only approval, no self-approval by Reviewer, required reasons for
request-changes/reject/rollback, immutable approved snapshots, and idempotent
duplicate requests.

**Step 2: Write failing publication atomicity tests**

Inject failure before and after asset preparation and inside the final
transaction. The current release must remain unchanged until the final pointer
switch. Concurrent publication attempts must serialize with an advisory lock.

**Step 3: Write failing rollback tests**

Rollback creates a new release matching selected historical content while
retaining all intervening revisions and audit events.

**Step 4: Implement release validation**

Recompute all scientific and asset integrity checks against current database
state. Do not reuse stale submission validation. Block missing/corrupt assets,
invalid endpoints, source mismatch confirmations, dangling references, and
unresolved pair-ready edges.

**Step 5: Implement deterministic release export**

Export Papers, compounds, structures, lineages, edges, evidence, activities,
Regions, objects, bindings, asset manifest, vocabularies, schema version,
release notes, and SHA-256 manifest. Verify an export can re-import into an
empty disposable database.

**Step 6: Build Admin comparison and publication UI**

Show categorized diffs, PDF Region overlays, RDKit comparisons, lineage diffs,
validation, comments, release delta, and explicit approve/request/reject/
publish/rollback actions.

**Step 7: Verify and commit**

```bash
cd leadtrace/backend && pytest -q tests/releases tests/reviews tests/audit
cd ../frontend && npm test -- --run tests/approval-release.spec.ts
git add ../backend ../frontend
git commit -m "feat: publish and roll back approved revisions atomically"
```

### Task 22: Build Admin users, files, imports, audit, jobs, and system pages

**Files:**

- Create: `leadtrace/frontend/src/admin/UsersPage.vue`
- Create: `leadtrace/frontend/src/admin/FilesPage.vue`
- Create: `leadtrace/frontend/src/admin/ImportsPage.vue`
- Create: `leadtrace/frontend/src/admin/AuditPage.vue`
- Create: `leadtrace/frontend/src/admin/JobsPage.vue`
- Create: `leadtrace/frontend/src/admin/SystemPage.vue`
- Create: `leadtrace/backend/app/admin/router.py`
- Create: `leadtrace/backend/app/health/service.py`
- Create: `leadtrace/backend/tests/admin/`
- Create: `leadtrace/frontend/tests/admin.spec.ts`

**Step 1: Write failing Admin API and UI tests**

Test user lifecycle, Session revocation, asset reverse references, import dry
run/apply, audit filters, failed-job retry, database/storage/worker/disk/backup/
schema/release health, and non-disclosure of secrets/absolute paths.

**Step 2: Implement file reverse lookup**

From asset, list related Paper, Regions, objects, structures, evidence,
derivatives, import batch, access class, and integrity. From a business object,
link back to its asset metadata.

**Step 3: Implement staged import operations**

Admin selects or uploads a snapshot, validates into staging, reviews the diff,
creates a system changeset, and follows normal approval/publication. Pipeline
imports never update published rows directly.

**Step 4: Implement safe task retry and health visibility**

Retries reuse the same idempotency key when appropriate. The system page shows
actionable failure summaries and request/job IDs, not terminal-only errors.

**Step 5: Verify and commit**

```bash
cd leadtrace/backend && pytest -q tests/admin
cd ../frontend && npm test -- --run tests/admin.spec.ts
git add ../backend ../frontend
git commit -m "feat: add LeadTrace administration console"
```

## Milestone I: Operations, Hardening, and Cutover

### Task 23: Add durable background-job recovery and maintenance mode

**Files:**

- Create: `leadtrace/backend/app/jobs/reconciler.py`
- Create: `leadtrace/backend/app/jobs/router.py`
- Create: `leadtrace/backend/app/maintenance/service.py`
- Create: `leadtrace/backend/tests/jobs/test_recovery.py`
- Modify: `leadtrace/deploy/compose.yaml`

**Step 1: Write failing worker/Redis recovery tests**

Test `queued_not_dispatched`, worker death while running, duplicate delivery,
retry limits, superseded work, and Redis restart. PostgreSQL records must make
each state recoverable.

**Step 2: Implement reconciliation**

The reconciler safely redelivers missing jobs, marks stale attempts, and never
creates duplicate logical assets or releases.

**Step 3: Implement read-only maintenance mode**

Visitor current-release reads remain available. Reviewer writes return a clear
maintenance response. Admin sees reason, start time, expected end, and safe
operations.

**Step 4: Verify and commit**

```bash
cd leadtrace/backend
pytest -q tests/jobs
git add app tests ../deploy/compose.yaml
git commit -m "feat: recover background jobs and support maintenance mode"
```

### Task 24: Automate backup, restore, integrity, and operational runbooks

**Files:**

- Create: `leadtrace/ops/backup/backup_postgres.sh`
- Create: `leadtrace/ops/backup/backup_assets.sh`
- Create: `leadtrace/ops/backup/verify_backup.py`
- Create: `leadtrace/ops/restore/restore_drill.sh`
- Create: `leadtrace/ops/restore/verify_restored_system.py`
- Create: `leadtrace/ops/runbooks/backup.md`
- Create: `leadtrace/ops/runbooks/restore.md`
- Create: `leadtrace/ops/runbooks/upgrade.md`
- Create: `leadtrace/ops/runbooks/incident.md`
- Create: `leadtrace/backend/tests/ops/test_backup_metadata.py`

**Step 1: Write failing backup metadata tests**

Require encrypted backup metadata, database dump hash, asset-manifest hash,
application/schema/release versions, start/end time, outcome, and independent
destination identity. Ensure secrets are not embedded in metadata.

**Step 2: Implement explicit-target backup scripts**

Scripts must refuse broad or unresolved paths, use fixed validated data roots,
write to staging, verify output, and atomically finalize. Never use `$HOME`, `~`,
or a broad workspace root as a destructive target.

**Step 3: Implement the isolated restore drill**

Restore PostgreSQL and a representative/full asset set into a new temporary
environment, run migrations if appropriate, verify hashes and baseline counts,
log in with a drill account, read a Paper, access an authorized PDF, inspect a
release and audit event, and save a report.

**Step 4: Schedule and document policy**

Configure four-hour database backups, pre-migration and pre-release backups,
daily incremental asset backup, weekly full asset backup, 30-day retention, and
monthly restore drill. Use a physically separate disk or controlled network
destination.

**Step 5: Verify and commit**

```bash
pytest -q leadtrace/backend/tests/ops
python leadtrace/ops/backup/verify_backup.py --help
bash -n leadtrace/ops/backup/backup_postgres.sh
bash -n leadtrace/ops/backup/backup_assets.sh
bash -n leadtrace/ops/restore/restore_drill.sh
git add leadtrace/ops leadtrace/backend/tests/ops
git commit -m "ops: add tested backup and restore workflows"
```

### Task 25: Add security, observability, accessibility, and performance gates

**Files:**

- Create: `leadtrace/backend/app/observability/logging.py`
- Create: `leadtrace/backend/app/observability/metrics.py`
- Create: `leadtrace/backend/tests/security/test_web_security.py`
- Create: `leadtrace/backend/tests/performance/test_query_plans.py`
- Create: `leadtrace/frontend/e2e/accessibility.spec.ts`
- Create: `leadtrace/frontend/e2e/concurrency.spec.ts`
- Create: `leadtrace/tests/load/locustfile.py`
- Modify: `leadtrace/deploy/nginx/nginx.conf`
- Create: `leadtrace/deploy/nginx/tls/README.md`

**Step 1: Write security regression tests**

Cover CSRF, XSS rendering, SQL injection attempts, path traversal, guessed
asset/changeset IDs, MIME spoofing, archive size/depth/count limits, SSRF
allowlisting, Session fixation/reuse, rate limiting, error redaction, and
absolute-path/secret leakage.

**Step 2: Add structured logs and metrics**

Log request ID, safe actor ID, role, route, result, duration, Paper/changeset/
release/job IDs, and error code. Exclude passwords, cookies, tokens, secrets,
raw uploads, and storage paths. Expose liveness, readiness, and restricted
metrics separately.

**Step 3: Configure internal HTTPS**

Document internal CA issuance and client trust. Nginx exposes only the selected
fixed TLS port; database, Redis, and FastAPI remain internal. HTTP development
mode is not accepted for production cutover.

**Step 4: Run accessibility tests**

Verify keyboard navigation, visible focus, labels, contrast, non-color status
cues, error association, zoom layout, and shortcut suppression inside inputs.

**Step 5: Run realistic load and concurrency tests**

Test 20 concurrent readers, five concurrent editors, PDF ranges, draft saves,
RDKit queues, search, release validation, Redis restart, and worker restart.
Targets:

```text
login p95                    < 500 ms
Paper list p95               < 500 ms
Paper detail metadata p95    < 1 s
changeset save p95           < 750 ms
search p95                   < 1 s
PDF first visible content    < 2 s on LAN
cached PDF page              < 500 ms
single structure preview     normally < 2 s
```

**Step 6: Verify and commit**

```bash
cd leadtrace/backend && pytest -q tests/security tests/performance
cd ../frontend && npx playwright test e2e/accessibility.spec.ts e2e/concurrency.spec.ts
cd .. && locust -f tests/load/locustfile.py --headless -u 20 -r 5 -t 5m
git add backend frontend deploy tests
git commit -m "test: enforce production security and performance gates"
```

### Task 26: Run full migration acceptance and parallel cutover

**Files:**

- Create: `leadtrace/ops/cutover/preflight.py`
- Create: `leadtrace/ops/cutover/smoke_test.py`
- Create: `leadtrace/ops/runbooks/cutover.md`
- Create: `leadtrace/ops/runbooks/rollback-cutover.md`
- Create: `docs/acceptance/leadtrace-release-1.md`
- Modify: `leadtrace/deploy/nginx/nginx.conf`

**Step 1: Write a machine-readable cutover preflight**

It must verify backups, restore-drill recency, schema/app versions, current
release, exact baseline/import counts, zero integrity defects, asset hashes,
worker/database/storage readiness, HTTPS, permission matrix smoke tests, and
old Dashboard health.

**Step 2: Select representative acceptance Papers**

Include Batch 01-06 coverage and cases for multiple roots, branches, unresolved
parent, racemate, multicomponent material, source mismatch, prime label,
one-image/many-label, multiple sources, no pair-ready edge, and rich activity.

**Step 3: Run full verification from clean processes**

```bash
PYTHONPATH=source_pdfs/分子修改提取_2024_JMC/scripts \
  pytest -q source_pdfs/分子修改提取_2024_JMC/tests
PYTHONPATH=. pytest -q dashboard/tests/test_dashboard_server.py
cd leadtrace/backend && pytest -q
cd ../frontend && npm run typecheck && npm test -- --run && npm run build
npx playwright test
cd .. && python ops/cutover/preflight.py
```

Expected: all suites pass, baseline reconciles exactly, and production source
manifest is unchanged.

**Step 4: Conduct role-based user acceptance**

At minimum one Admin, two Reviewers, and one Visitor perform:

```text
login -> published browse -> assigned PDF review -> Region edit
-> image reuse -> multi-label binding -> structure/lineage edit
-> submit -> request changes -> resubmit -> approve -> publish
-> Visitor verification -> rollback -> audit verification
```

Record pass/fail evidence in `docs/acceptance/leadtrace-release-1.md`.

**Step 5: Perform the controlled cutover**

Enter maintenance mode for writes, take final database/config/asset backups,
apply the last incremental import, rerun reconciliation and release validation,
switch the Nginx primary route, and run smoke tests. Keep the old Dashboard
read-only on an internal fallback route/port.

**Step 6: Exercise the cutover fallback**

Before declaring completion, demonstrate that Nginx can return to the old
read-only Dashboard without deleting new revisions. Then restore the new route
and repeat smoke tests.

**Step 7: Commit the acceptance record**

```bash
git add leadtrace/ops docs/acceptance leadtrace/deploy/nginx/nginx.conf
git commit -m "docs: record LeadTrace production acceptance and cutover"
```

## Final Verification Checklist

Before claiming the project complete, collect fresh evidence for every item:

- [ ] Source manifest unchanged from the approved baseline or every intended
      source change explicitly reconciled.
- [ ] 672 Papers and all fixed aggregate counts match.
- [ ] Scientific integrity defect counts are all zero.
- [ ] All legacy scientific and Dashboard tests pass.
- [ ] All new backend, frontend, integration, and E2E tests pass.
- [ ] Visitor cannot access full PDFs, drafts, hidden assets, or Admin APIs.
- [ ] Reviewer can access assigned PDFs and cannot approve or publish.
- [ ] Admin account, approval, release, rollback, and audit flows pass.
- [ ] Draft changes remain invisible before publication.
- [ ] A stale concurrent edit returns 409 and preserves both users' work.
- [ ] A failed publication leaves the current release unchanged.
- [ ] Duplicate approve/publish requests are idempotent.
- [ ] Region geometry survives zoom/rotation and remains non-destructive.
- [ ] One image can be shown for several objects and compound labels while the
      underlying asset is stored once.
- [ ] RDKit parseability is not represented as scientific confirmation.
- [ ] Racemate, mixture, multicomponent, and source-mismatch states remain
      explicit and cannot become invalid pairs.
- [ ] Every published asset exists and matches its SHA-256.
- [ ] Database and asset backup completed.
- [ ] An isolated restore drill succeeded within the RPO/RTO target.
- [ ] LAN HTTPS works on the selected fixed port.
- [ ] PostgreSQL, Redis, and FastAPI internal ports are not exposed to the LAN.
- [ ] Logs contain request IDs but no passwords, cookies, tokens, secrets, or
      absolute storage paths.
- [ ] Old Dashboard fallback is available throughout stabilization.

## Execution Handoff

This plan deliberately ends before implementation. After the user gives an
explicit start instruction:

1. run Task 1 in the current workspace to create the safe baseline and first
   Git commit;
2. create a dedicated worktree;
3. execute tasks in order with review checkpoints at the end of each milestone;
4. do not proceed past baseline import, first publication, backup/restore, or
   cutover gates without presenting verification evidence.
