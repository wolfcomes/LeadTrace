# Initial Baseline Release Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let an Admin explicitly approve an imported baseline candidate and publish it as the first complete, validated, Visitor-visible LeadTrace release.

**Architecture:** Add an append-only candidate decision model and a separate idempotent bootstrap publisher. The publisher builds a deterministic complete Release from imported baseline revisions, validates and snapshots it inside one PostgreSQL transaction, and switches the current pointer only after every gate passes. Extend the Admin import page with approval controls and the Release page with a distinct initial-publication panel.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16, Vue 3, TypeScript, Zod, Vitest, pytest.

---

### Task 1: Persist Immutable Import Candidate Decisions

**Files:**

- Create: `leadtrace/backend/migrations/versions/0016_initial_baseline_release.py`
- Modify: `leadtrace/backend/app/imports/models.py`
- Modify: `leadtrace/backend/app/audit/models.py`
- Modify: `leadtrace/backend/app/audit/service.py`
- Modify: `leadtrace/backend/tests/db/test_migrations.py`
- Create: `leadtrace/backend/tests/imports/test_candidate_decisions.py`

**Step 1: Write the failing model and migration tests**

Add tests that expect an `ImportCandidateDecision` model with one decision per
candidate, `approve|reject` validation, manifest hash validation, and ORM-level
update/delete rejection. Extend migration tests to assert:

- Alembic head is `0016_initial_baseline_release`;
- `import_candidate_decisions` has the required foreign keys and constraints;
- direct SQL update/delete is rejected by a trigger;
- `release_operations.replaced_release_id` accepts NULL for a first release;
- `release_operations.operation_type` accepts `baseline_publish`; and
- `audit_events.paper_id` accepts NULL for corpus-level events.

**Step 2: Run RED**

```bash
cd leadtrace/backend
LEADTRACE_TEST_DATABASE_URL='postgresql+psycopg://zhangzhiyong@127.0.0.1:55440/leadtrace_initial_baseline_test' \
  ../../../.worktrees/leadtrace-platform/.venv/bin/python -m pytest -q \
  tests/imports/test_candidate_decisions.py tests/db/test_migrations.py
```

Expected: collection or assertions fail because the model/table and migration
revision do not exist.

**Step 3: Implement the minimal schema**

Add `ImportCandidateDecision` to `app/imports/models.py` with fields:

```python
candidate_id: UUID
decision: str
actor_id: UUID
reason: str
manifest: dict[str, object]
manifest_hash: str
created_at: datetime
```

Use a unique constraint on `candidate_id`, checks for the decision and 64-byte
hash, an index by candidate/time, and the same ORM append-only listener pattern
as `ApprovalDecision`.

Migration `0016` creates the table and database trigger, makes corpus-level
audit `paper_id` nullable, makes `ReleaseOperation.replaced_release_id`
nullable, and replaces its operation-type constraint with:

```sql
operation_type IN ('baseline_publish', 'publish', 'rollback')
```

Update audit serialization and service typing so `paper_id=None` is canonical
and remains hash-chain verifiable.

**Step 4: Run GREEN and the audit regression tests**

```bash
pytest -q tests/imports/test_candidate_decisions.py tests/db/test_migrations.py tests/audit
```

Expected: all selected tests pass.

**Step 5: Commit**

```bash
git add leadtrace/backend/app/imports/models.py \
  leadtrace/backend/app/audit \
  leadtrace/backend/migrations/versions/0016_initial_baseline_release.py \
  leadtrace/backend/tests/imports/test_candidate_decisions.py \
  leadtrace/backend/tests/db/test_migrations.py
git commit -m "feat: persist baseline candidate decisions"
```

### Task 2: Implement Candidate Approval State Transitions

**Files:**

- Create: `leadtrace/backend/app/imports/approval.py`
- Modify: `leadtrace/backend/tests/imports/test_candidate_decisions.py`

**Step 1: Write failing service tests**

Cover:

- only an enabled Admin can decide;
- the candidate must be `imported_baseline` and its batch `completed`;
- reason is required and limited to 4,000 characters;
- approval stores the PostgreSQL JSONB-normalized manifest and canonical hash;
- approve changes status to `approved`;
- reject changes status to `rejected`;
- an exact retry returns the original decision as idempotent; and
- actor, action, reason, or manifest differences on retry return a conflict.

**Step 2: Run RED**

```bash
pytest -q tests/imports/test_candidate_decisions.py -k service
```

Expected: failure because `ImportCandidateApprovalService` does not exist.

**Step 3: Implement the service**

Implement `decide(session, candidate_id, actor_id, action, reason)` with a
`SELECT ... FOR UPDATE` candidate lock. Reuse `persisted_json_value` and
`canonical_content_hash` so the approved hash matches PostgreSQL JSONB
semantics. Return a typed result with `idempotent`.

**Step 4: Run GREEN**

```bash
pytest -q tests/imports/test_candidate_decisions.py
```

Expected: all candidate model and service tests pass.

**Step 5: Commit**

```bash
git add leadtrace/backend/app/imports/approval.py \
  leadtrace/backend/tests/imports/test_candidate_decisions.py
git commit -m "feat: approve imported baseline candidates"
```

### Task 3: Build and Publish the Initial Release Atomically

**Files:**

- Modify: `leadtrace/backend/app/releases/service.py`
- Modify: `leadtrace/backend/app/releases/aggregate.py`
- Create: `leadtrace/backend/tests/releases/test_baseline_publish.py`
- Modify: `leadtrace/backend/tests/releases/test_task21_red.py`

**Step 1: Write failing bootstrap publisher tests**

Build a small real imported fixture and assert that
`publish_approved_baseline(...)`:

- refuses an unapproved or rejected candidate;
- refuses a non-Admin and a disabled Admin;
- refuses incomplete imports, changed manifests, wrong fixed counts, missing
  revisions, and any existing Release;
- orders every release item deterministically;
- links `Release.source_candidate_id`;
- publishes every baseline revision and marks it current;
- captures the artifact manifest and passes `validate_release`;
- exposes structured overview metrics with explicit denominators;
- records a `baseline_publish` ReleaseOperation;
- is idempotent for an exact retry and rejects key reuse with another request;
- rolls back every state change at injected pre-pointer and pointer stages; and
- leaves the candidate `published` only after finalization succeeds.

Add a regression assertion that later changeset publication and rollback carry
forward or recompute the structured overview metrics instead of replacing them
with operation-only metadata.

**Step 2: Run RED**

```bash
pytest -q tests/releases/test_baseline_publish.py \
  tests/releases/test_task21_red.py -k 'baseline or overview_metrics'
```

Expected: failure because the bootstrap publisher and metrics helper do not
exist.

**Step 3: Implement deterministic construction**

Add a fixed object-kind rank and collect eligible baseline rows from the domain
tables. Sort by Paper key, kind rank, stable domain key, then UUID. Require the
object and revision totals to equal the approved candidate's `revision_count`.

Add a helper that turns fixed aggregate counts into the existing overview
contract:

```python
{
    "corpus": {"numerator": corpus_papers, "denominator": corpus_papers, "unit": "papers"},
    "lineage": {"numerator": lineage_papers, "denominator": corpus_papers, "unit": "papers"},
    "relation": {"numerator": lineage_edges, "denominator": lineage_edges, "unit": "edges"},
    "structure": {"numerator": structure_confirmed, "denominator": compound_entities, "unit": "compounds"},
    "pair": {"numerator": pair_ready_edges, "denominator": lineage_edges, "unit": "edges"},
    "human_review": {"numerator": 0, "denominator": corpus_papers, "unit": "papers"},
}
```

The service must acquire the release advisory lock, recheck all candidate and
decision hashes, create Release items, mark revisions published, capture the
artifact manifest, validate physical assets with `LocalAssetStore`, finalize
the manifest, create the ReleaseOperation, switch `is_current`, and finally set
the candidate status to `published`.

Keep operational metadata under a separate `operation` key while preserving
the six overview metric keys on changeset releases and rollback releases.

**Step 4: Run GREEN and full release regressions**

```bash
pytest -q tests/releases
```

Expected: all release tests pass.

**Step 5: Commit**

```bash
git add leadtrace/backend/app/releases \
  leadtrace/backend/tests/releases/test_baseline_publish.py \
  leadtrace/backend/tests/releases/test_task21_red.py
git commit -m "feat: publish an approved initial baseline"
```

### Task 4: Expose Protected Admin APIs and Audit Events

**Files:**

- Modify: `leadtrace/backend/app/admin/router.py`
- Modify: `leadtrace/backend/app/releases/router.py`
- Modify: `leadtrace/backend/tests/admin/test_admin_api.py`
- Modify: `leadtrace/backend/tests/releases/test_routes.py`
- Modify: `leadtrace/backend/tests/audit/test_audit_api.py`

**Step 1: Write failing API tests**

Test candidate listing, safe manifests, decision response, bootstrap publish
response, CSRF, Admin-only access, required Idempotency-Key, conflict/validation
error mapping, and separate corpus-level audit events. Verify no password,
session token, filesystem path, or raw source row appears in API or audit data.

**Step 2: Run RED**

```bash
pytest -q tests/admin/test_admin_api.py tests/releases/test_routes.py \
  tests/audit/test_audit_api.py -k 'candidate or baseline'
```

Expected: route tests return 404 because the endpoints do not exist.

**Step 3: Add schemas and routes**

Add candidate listing and decision routes under `/api/v1/admin`. Add
`POST /api/v1/releases/publish-baseline` next to the existing publisher. Reuse
the current Admin, CSRF, idempotency, safe error, request ID, and remote-address
helpers. Append one audit event after each successful non-idempotent mutation.

**Step 4: Run GREEN and security regressions**

```bash
pytest -q tests/admin tests/releases/test_routes.py tests/audit \
  tests/security/test_route_permission_matrix.py
```

Expected: all selected tests pass.

**Step 5: Commit**

```bash
git add leadtrace/backend/app/admin/router.py \
  leadtrace/backend/app/releases/router.py \
  leadtrace/backend/tests/admin/test_admin_api.py \
  leadtrace/backend/tests/releases/test_routes.py \
  leadtrace/backend/tests/audit/test_audit_api.py
git commit -m "feat: expose controlled baseline publication APIs"
```

### Task 5: Add Admin Approval and Initial Publication UI

**Files:**

- Modify: `leadtrace/frontend/src/admin/api.ts`
- Modify: `leadtrace/frontend/src/admin/ImportsPage.vue`
- Modify: `leadtrace/frontend/src/releases/api.ts`
- Modify: `leadtrace/frontend/src/releases/ReleasePage.vue`
- Modify: `leadtrace/frontend/tests/admin.spec.ts`
- Modify: `leadtrace/frontend/tests/approval-release.spec.ts`

**Step 1: Write failing frontend tests**

Mock the new endpoints and assert:

- candidate states render in Chinese;
- approve/reject require a reason and send CSRF-protected requests;
- only pending candidates have decision controls;
- approved candidates link to a separate initial-publication panel;
- baseline publishing uses a stable per-attempt idempotency key;
- conflicts and validation failures state that the current version is unchanged;
  and
- normal changeset publication remains available after bootstrap.

**Step 2: Run RED**

```bash
cd leadtrace/frontend
npm test -- --run tests/admin.spec.ts tests/approval-release.spec.ts
```

Expected: assertions fail because the controls and API functions are absent.

**Step 3: Implement typed API and focused UI**

Add Zod schemas for candidate/decision data and baseline publication. Extend
the unframed Admin panels without nesting cards. Use buttons only for explicit
approve, reject, and publish commands, keep reasons labelled, and retain clear
loading/error/terminal states.

**Step 4: Run GREEN, typecheck, and build**

```bash
npm test -- --run tests/admin.spec.ts tests/approval-release.spec.ts
npm run typecheck
npm run build
```

Expected: tests, typecheck, and production build pass.

**Step 5: Commit**

```bash
git add leadtrace/frontend/src/admin leadtrace/frontend/src/releases \
  leadtrace/frontend/tests/admin.spec.ts \
  leadtrace/frontend/tests/approval-release.spec.ts
git commit -m "feat: review and publish the baseline in Admin UI"
```

### Task 6: Verify, Merge, Migrate, and Resume LAN Acceptance

**Files:**

- Modify only if evidence requires it: `docs/acceptance/leadtrace-release-1.md`

**Step 1: Run repository verification**

```bash
cd leadtrace/backend
LEADTRACE_TEST_DATABASE_URL='postgresql+psycopg://zhangzhiyong@127.0.0.1:55440/leadtrace_initial_baseline_test' \
  ../../../.worktrees/leadtrace-platform/.venv/bin/python -m pytest -q
cd ../frontend
npm run typecheck
npm test -- --run
npm run build
cd ../../..
python -m leadtrace.ops.baseline.verify_manifest \
  docs/baseline/2026-09-10-source-manifest.json
git diff --check
```

Expected: all suites pass and the source manifest reports zero differences.

**Step 2: Request code review and address findings**

Use `superpowers:requesting-code-review` against the branch base and fix all
Critical or Important findings with TDD.

**Step 3: Merge locally after user-approved workflow**

Use `superpowers:finishing-a-development-branch`, merge to local `main`, and
repeat focused tests on the merged tree. Do not push.

**Step 4: Upgrade the acceptance database**

Stop only FastAPI and Celery, run Alembic upgrade to `0016`, rebuild the
frontend, and restart the processes with the existing owner-only runtime
secrets. Do not recreate or re-import the acceptance database.

**Step 5: Perform real acceptance smoke checks**

Verify:

- candidate is pending and no Release exists before Admin action;
- Admin can change the one-time password, approve the candidate, and publish it
  in separate requests;
- 672 Papers become Visitor-visible only after publication;
- Reviewer and Visitor cannot reach the Admin endpoints;
- the release validates and assets resolve;
- audit chain contains separate approval and baseline-publication events;
- Redis, worker, Dashboard fallback, and Caddy remain healthy; and
- only Caddy is LAN-facing among LeadTrace services.

Do not perform production TLS, load, backup/restore, route cutover, or fallback
acceptance claims in this task.
