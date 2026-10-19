# Activity Comparison Implementation Plan

**Goal:** Add the approved read-only Reviewer activity matrix and focused editor navigation.
**Architecture:** Authorized single-query workspace read plus a persistent Vue matrix; reuse Compound/Activity editors and existing permissions.
**Tech Stack:** FastAPI, SQLAlchemy/PostgreSQL, Vue 3/TypeScript, Vitest, Playwright.

1. Backend: add tests/science_v2/test_activity_comparison.py for empty/populated data,
   precision, duplicates, access policy, removed papers, and no scientific/view writes.
   Run failing tests using the separate disposable _test cluster. Add schemas, service
   and GET /api/v2/workspaces/{workspace_id}/activity-comparison to activities modules.
   Update the strict route permission matrix and run suites serially.
2. Frontend: add activity-comparison.spec.ts tests for column separation, all repeated
   observations, missing cells, search/measurement filter/sort, errors and navigation.
   Add typed API, ActivityComparison.vue and small matrix helper. Integrate tab and
   return link in PaperWorkspacePage; pass known owner to CompoundList to avoid
   requesting every Compound's Activities to resolve one measurement.
3. Verify returning after edits/undo, stale loads and pending-edit navigation protection.
   Keep the comparison component mounted across ordinary tab changes and history
   restoration, clear state on workspace change, preserve scroll on refresh.
4. Add synthetic Playwright scenario for matrix -> edit -> return and mobile layout.
   Run frontend suite, typecheck/build, targeted backend suites, guide generation/check
   and git diff --check. Review changes, commit tested implementation, retain worktrees.

## Verification outcome

- Backend comparison, permission matrix, Activity API and reviewer-workbench suites: 25 passed on an isolated disposable PostgreSQL cluster.
- Frontend: 413 tests passed; typecheck and production build passed.
- Synthetic browser flow passed at desktop and 390px mobile widths: exact Activity navigation, saved edit, return state, no comparison writes, and contained horizontal scrolling.
- Independent review found a stale-editor concurrency window. Reading comparisons no longer advances editor versions; entering details locks editing, refreshes Workspace and remounts editor children before unlocking. Regression reproduced the old failure and passes with the fix.
- Bilingual guide generation/check and git diff whitespace checks passed.
- No schema migration required.
