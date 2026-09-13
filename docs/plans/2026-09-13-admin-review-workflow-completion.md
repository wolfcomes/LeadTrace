# LeadTrace Admin Review Workflow Completion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let an Admin inspect all imported Papers, distinguish five human-review states independently from publication, publish an explicitly unverified AI-extracted baseline, manage account roles, assign review tasks, and use simple passwords of six or more characters.

**Architecture:** Keep immutable Release publication and human-review workflow as separate dimensions. Associate every imported revision with its import batch, reuse stable domain identities on corrected imports, derive Admin Paper states from revisions/tasks/changesets, and expose a protected Admin query surface while leaving Visitor APIs Release-scoped. Add missing typed Vue controls over the existing user and review-task APIs.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, PostgreSQL, Alembic, Argon2id, pytest, Vue 3, TypeScript, Zod, Vitest, Vite.

---

### Task 1: Relax the local password policy to six characters

**Files:**
- Modify: `leadtrace/backend/tests/auth/test_passwords.py`
- Modify: `leadtrace/backend/tests/auth/test_auth_api.py`
- Modify: `leadtrace/backend/app/security/passwords.py`
- Modify: `leadtrace/frontend/src/auth/ChangePasswordPage.vue`
- Modify: `leadtrace/frontend/src/admin/UsersPage.vue`

**Step 1: Write the failing backend policy test**

Replace the weak-password matrix with assertions that six-character
single-class passwords pass, while values shorter than six fail:

```python
@pytest.mark.parametrize("password", ["simple", "123456", "ABCDEF"])
def test_password_policy_accepts_simple_six_character_passwords(password: str) -> None:
    validate_password(password)

@pytest.mark.parametrize("password", ["", "a", "12345"])
def test_password_policy_rejects_passwords_shorter_than_six(password: str) -> None:
    with pytest.raises(PasswordPolicyError):
        validate_password(password)
```

Add an API test that changes an account password to a simple six-character
test value and logs in successfully.

**Step 2: Run the tests to verify RED**

Run:

```bash
cd leadtrace/backend
../../../leadtrace-platform/.venv/bin/python -m pytest \
  tests/auth/test_passwords.py tests/auth/test_auth_api.py -q
```

Expected: the six-character acceptance tests fail with the current 16-character error.

**Step 3: Implement the minimum policy**

Change `validate_password` to enforce only `len(password) >= 6`. Keep Argon2id parameters and verification behavior unchanged. Add `minlength="6"` to browser password creation/change/reset inputs.

**Step 4: Run focused tests to verify GREEN**

Run the command from Step 2 and expect all selected tests to pass.

**Step 5: Commit**

```bash
git add leadtrace/backend/app/security/passwords.py \
  leadtrace/backend/tests/auth/test_passwords.py \
  leadtrace/backend/tests/auth/test_auth_api.py \
  leadtrace/frontend/src/auth/ChangePasswordPage.vue \
  leadtrace/frontend/src/admin/UsersPage.vue
git commit -m "feat: allow simple local passwords"
```

### Task 2: Bind imported revisions to their batch and support corrected re-imports

**Files:**
- Modify: `leadtrace/backend/app/revisions/models.py`
- Modify: `leadtrace/backend/app/imports/service.py`
- Modify: `leadtrace/backend/app/releases/service.py`
- Modify: `leadtrace/backend/migrations/versions/0016_initial_baseline_release.py`
- Modify: `leadtrace/backend/tests/db/test_migrations.py`
- Modify: `leadtrace/backend/tests/imports/test_service.py`
- Modify: `leadtrace/backend/tests/releases/test_baseline_publish.py`

**Step 1: Write a failing rejected-candidate re-import test**

Create candidate A, reject it, import corrected fingerprint B with the same Paper/domain identities, and assert:

```python
assert second.batch_id != first.batch_id
assert paper_count_after == paper_count_before
assert all(revision.import_batch_id == second.batch_id for revision in second_revisions)
assert all(revision.revision_number == 2 for revision in second_revisions)
```

Approve and publish B, then assert the Release contains only B-linked revisions.

**Step 2: Run the test to verify RED**

Run:

```bash
cd leadtrace/backend
../../../leadtrace-platform/.venv/bin/python -m pytest \
  tests/imports/test_service.py tests/releases/test_baseline_publish.py -q
```

Expected: the second import fails on stable Paper/domain unique constraints or publication cannot isolate revisions by batch.

**Step 3: Add the explicit revision association**

Add nullable `ObjectRevision.import_batch_id` with a restrictive foreign key to `import_batches.id` and an index. In migration `0016`, add the column after its data-presence downgrade guards, backfill existing baseline revisions to their unique completed batch, then make imported-revision queries batch-scoped. Preserve `NULL` for Reviewer-created revisions.

**Step 4: Reuse stable object identities during re-import**

Resolve Papers, compounds, lineages, structures, evidence, activities, edges, and visual objects by their existing natural identities. Reuse existing rows, validate immutable ownership fields, and create the next monotonic revision linked to the new batch. Never mutate or repoint rejected candidate A.

**Step 5: Scope baseline publication to the selected batch**

Change `_baseline_release_items` and its validation callers to require `batch_id`; select only approved, non-tombstone revisions whose `import_batch_id` matches the candidate batch. Assert the selected count matches the immutable candidate manifest.

**Step 6: Verify migrations and re-import GREEN**

Run:

```bash
cd leadtrace/backend
../../../leadtrace-platform/.venv/bin/python -m pytest \
  tests/db/test_migrations.py tests/imports/test_service.py \
  tests/releases/test_baseline_publish.py -q
```

Expected: all selected tests pass, including `A -> reject -> B -> approve -> publish`.

**Step 7: Commit**

```bash
git add leadtrace/backend/app/revisions/models.py \
  leadtrace/backend/app/imports/service.py \
  leadtrace/backend/app/releases/service.py \
  leadtrace/backend/migrations/versions/0016_initial_baseline_release.py \
  leadtrace/backend/tests/db/test_migrations.py \
  leadtrace/backend/tests/imports/test_service.py \
  leadtrace/backend/tests/releases/test_baseline_publish.py
git commit -m "fix: isolate corrected baseline imports"
```

### Task 3: Classify Releases by evidence quality

**Files:**
- Modify: `leadtrace/backend/app/releases/service.py`
- Modify: `leadtrace/backend/app/releases/aggregate.py`
- Modify: `leadtrace/backend/app/api/overview.py`
- Modify: `leadtrace/backend/app/api/papers.py`
- Modify: `leadtrace/backend/tests/releases/test_baseline_publish.py`
- Modify: `leadtrace/backend/tests/api/test_overview.py`
- Modify: `leadtrace/backend/tests/api/test_published_papers.py`
- Modify: `leadtrace/frontend/src/api/schema.ts`
- Modify: `leadtrace/frontend/src/papers/OverviewPage.vue`
- Modify: `leadtrace/frontend/src/papers/PaperLibraryPage.vue`
- Modify: `leadtrace/frontend/src/papers/PaperDetailPage.vue`
- Modify: `leadtrace/frontend/tests/published-pages.spec.ts`
- Modify: `leadtrace/frontend/tests/approval-release.spec.ts`

**Step 1: Write failing release classification tests**

Assert that baseline publication defaults to:

```json
{"dataset_class":"ai_extracted_baseline","verification_status":"unverified","title":"AI 提取基线"}
```

Assert a normal approved Changeset publication defaults to:

```json
{"dataset_class":"human_verified_dataset","verification_status":"human_verified","title":"人工核验数据集"}
```

Require published overview, Paper list, and Paper detail responses to carry this immutable Release classification.

**Step 2: Run backend and frontend tests to verify RED**

Run focused release/API tests and:

```bash
cd leadtrace/frontend
npm test -- published-pages.spec.ts approval-release.spec.ts
```

Expected: dataset classification fields and labels are absent.

**Step 3: Store classification in Release metrics and expose it**

Set `metrics["dataset"]` at publication time. Preserve it during rollback and export/import. Use `source_candidate_id` only as a backward-compatible fallback for pre-existing fixtures, not as the primary display rule.

**Step 4: Render durable verification badges**

Show `AI 提取基线` plus a high-contrast `未验证` badge on every overview/library/detail view backed by that Release. Show `人工核验数据集` plus `已人工核验` for successor Releases. A custom Release title must not hide the dataset class.

**Step 5: Verify GREEN and commit**

Run the focused backend/frontend tests, then commit:

```bash
git commit -am "feat: classify AI and human verified releases"
```

### Task 4: Build the Admin Paper projection and candidate-safe APIs

**Files:**
- Create: `leadtrace/backend/app/admin/papers.py`
- Modify: `leadtrace/backend/app/admin/router.py`
- Modify: `leadtrace/backend/app/main.py`
- Create: `leadtrace/backend/tests/admin/test_admin_papers.py`
- Modify: `leadtrace/backend/tests/security/test_route_permission_matrix.py`

**Step 1: Write failing API tests**

Cover Admin-only list/detail, candidate isolation, pagination, title/DOI search, the five workflow filters, and independent publication status. Seed Papers representing each state and assert exact codes:

```text
initial
ai_baseline_unassigned
ai_baseline_in_review
human_review_pending_approval
admin_approved
```

Also assert an AI baseline Paper may have `publication_status=published` while retaining `verification_status=unverified`.

**Step 2: Run tests to verify RED**

Run:

```bash
cd leadtrace/backend
../../../leadtrace-platform/.venv/bin/python -m pytest \
  tests/admin/test_admin_papers.py \
  tests/security/test_route_permission_matrix.py -q
```

Expected: Admin Paper routes return 404.

**Step 3: Implement a read-only projection service**

Add candidate/current-Release source resolution and derive state in this precedence order:

```python
if approved_changeset:
    return "admin_approved"
if submitted_changeset:
    return "human_review_pending_approval"
if active_task:
    return "ai_baseline_in_review"
if ai_baseline_revision:
    return "ai_baseline_unassigned"
return "initial"
```

Use SQL subqueries/aggregates rather than one query per Paper. Return Paper summary, quality counts, assignee/task metadata, dataset class, verification status, and publication status without filesystem paths.

**Step 4: Add routes**

Expose:

```text
GET /api/v1/admin/papers
GET /api/v1/admin/papers/{paper_id}
```

Support optional `candidate_id`, page/page_size, search, DOI, workflow state, publication status, and assignee filters. Require Admin account-management permission.

**Step 5: Verify GREEN and commit**

Run focused tests and commit:

```bash
git add leadtrace/backend/app/admin/papers.py \
  leadtrace/backend/app/admin/router.py leadtrace/backend/app/main.py \
  leadtrace/backend/tests/admin/test_admin_papers.py \
  leadtrace/backend/tests/security/test_route_permission_matrix.py
git commit -m "feat: expose the Admin Paper catalog"
```

### Task 5: Build the Admin Paper library interface

**Files:**
- Create: `leadtrace/frontend/src/admin/PaperCatalogPage.vue`
- Create: `leadtrace/frontend/src/admin/PaperCatalogDetailPage.vue`
- Modify: `leadtrace/frontend/src/admin/api.ts`
- Modify: `leadtrace/frontend/src/app/router.ts`
- Modify: `leadtrace/frontend/src/app/AppShell.vue`
- Modify: `leadtrace/frontend/src/i18n/zh-CN.ts`
- Create: `leadtrace/frontend/tests/admin-paper-catalog.spec.ts`

**Step 1: Write failing component tests**

Test pagination, filters, state counts, all five Chinese status labels, independent `未发布/已发布` badges, the durable `未验证` badge, empty/error states, and Admin-only navigation.

**Step 2: Run tests to verify RED**

Run:

```bash
cd leadtrace/frontend
npm test -- admin-paper-catalog.spec.ts
```

Expected: the route/component/API functions do not exist.

**Step 3: Implement typed API schemas and routes**

Add Zod schemas and query builders. Register `/admin/papers` and `/admin/papers/:paperId`, and add an Admin navigation item named `文章目录`.

**Step 4: Implement the work-focused catalog**

Use a dense table, stable pagination, filter controls, assignee/workflow columns, quality summaries, and a detail drawer/page. Keep dataset quality badges visible without turning every section into a card. Provide links to candidate approval, current Release, and assignment actions.

**Step 5: Verify GREEN and commit**

Run the component test, `npm run typecheck`, and commit:

```bash
git add leadtrace/frontend/src/admin leadtrace/frontend/src/app \
  leadtrace/frontend/src/i18n/zh-CN.ts \
  leadtrace/frontend/tests/admin-paper-catalog.spec.ts
git commit -m "feat: add the Admin Paper catalog"
```

### Task 6: Complete browser account management

**Files:**
- Modify: `leadtrace/frontend/src/admin/UsersPage.vue`
- Modify: `leadtrace/frontend/src/admin/api.ts`
- Modify: `leadtrace/frontend/tests/admin.spec.ts`
- Modify: `leadtrace/backend/tests/auth/test_auth_api.py`

**Step 1: Write failing UI tests**

Require role selection during creation, role changes for existing users,
server-default password reset, enable/disable, revoke sessions,
recent-reauthentication errors, and protection feedback when attempting to
demote the final enabled Admin. Account creation no longer accepts a browser-
supplied password, and password changes are voluntary from the signed-in
account area. See
`2026-09-13-optional-password-change-default-accounts.md` for the approved
implementation and controlled non-Admin reset procedure.

**Step 2: Run the tests to verify RED**

Run:

```bash
cd leadtrace/frontend
npm test -- admin.spec.ts
```

Expected: role/update/reset controls or client methods are absent.

**Step 3: Add typed client methods and controls**

Call the existing `/api/v1/users/{id}/role` and `/password` endpoints. Add a role menu, reset-password dialog, and explicit confirmation around role/enable changes. Do not introduce custom teams.

**Step 4: Verify GREEN and commit**

Run the focused frontend and backend authentication tests, then commit:

```bash
git add leadtrace/frontend/src/admin/UsersPage.vue \
  leadtrace/frontend/src/admin/api.ts leadtrace/frontend/tests/admin.spec.ts \
  leadtrace/backend/tests/auth/test_auth_api.py
git commit -m "feat: complete Admin account controls"
```

### Task 7: Add browser task assignment and reassignment

**Files:**
- Create: `leadtrace/frontend/src/admin/AssignmentsPage.vue`
- Modify: `leadtrace/frontend/src/review/api.ts`
- Modify: `leadtrace/frontend/src/admin/api.ts`
- Modify: `leadtrace/frontend/src/app/router.ts`
- Modify: `leadtrace/frontend/src/app/AppShell.vue`
- Modify: `leadtrace/frontend/src/i18n/zh-CN.ts`
- Modify: `leadtrace/backend/app/reviews/router.py`
- Modify: `leadtrace/backend/tests/reviews/test_api.py`
- Create: `leadtrace/frontend/tests/assignments.spec.ts`

**Step 1: Write failing assignment tests**

Require enabled Reviewer workload counts, Paper multiselect, priority, per-Paper create results, open-task reassignment with `expected_version`, conflict display, and refusal to assign before an AI baseline Release is current.

**Step 2: Run backend/frontend tests to verify RED**

Run focused review API tests and:

```bash
cd leadtrace/frontend
npm test -- assignments.spec.ts
```

Expected: typed creation/reassignment methods and assignment page are absent.

**Step 3: Add workload data without duplicating mutation APIs**

Keep task creation/reassignment on `/api/v1/review/tasks`. Extend the Admin list response or add a read-only workload summary to return enabled Reviewers and active counts. Require a current Release before task creation so changesets always have a stable base.

**Step 4: Implement the assignment workspace**

Combine Admin Paper filtering with a Reviewer workload panel. Execute bulk assignment as individually audited requests, keep successful rows visible, and report failures per Paper. Permit reassignment only while the backend reports `open`.

**Step 5: Verify GREEN and commit**

Run focused tests and type checking, then commit:

```bash
git add leadtrace/frontend/src/admin/AssignmentsPage.vue \
  leadtrace/frontend/src/review/api.ts leadtrace/frontend/src/admin/api.ts \
  leadtrace/frontend/src/app/router.ts leadtrace/frontend/src/app/AppShell.vue \
  leadtrace/frontend/src/i18n/zh-CN.ts \
  leadtrace/frontend/tests/assignments.spec.ts \
  leadtrace/backend/app/reviews/router.py \
  leadtrace/backend/tests/reviews/test_api.py
git commit -m "feat: add Admin review assignment"
```

### Task 8: Verify the assembled workflow and prepare acceptance upgrade

**Files:**
- Modify: `docs/acceptance/leadtrace-release-1.md` only with development evidence
- Modify: `leadtrace/README.md`

**Step 1: Run all backend tests**

```bash
cd leadtrace/backend
../../../leadtrace-platform/.venv/bin/python -m pytest -q
```

Expected: all backend tests pass; only explicitly configured optional integration tests may skip.

**Step 2: Run all frontend gates**

```bash
cd leadtrace/frontend
npm test
npm run typecheck
npm run build
```

Expected: unit tests, type checking, and production build pass.

**Step 3: Run repository integrity gates**

```bash
git diff --check
PYTHONDONTWRITEBYTECODE=1 ../leadtrace-platform/.venv/bin/python \
  -m leadtrace.ops.baseline.verify_manifest \
  docs/baseline/2026-09-10-source-manifest.json
```

Expected: no whitespace errors and protected source manifest reports zero changed, missing, or unexpected files.

**Step 4: Document development evidence and commit**

Record only test/build evidence. Do not claim production TLS, load, backup restore, cutover, or UAT.

```bash
git add docs/acceptance/leadtrace-release-1.md leadtrace/README.md
git commit -m "docs: record Admin workflow development evidence"
```

**Step 5: Review before touching the acceptance database**

Review the complete branch diff. Only after review passes: stop FastAPI/Celery, upgrade the acceptance database to `0016`, restart services, and smoke test the real sequence. Do not recreate the database or re-import while upgrading.
