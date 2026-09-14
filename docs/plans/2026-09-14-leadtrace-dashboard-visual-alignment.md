# Lead Trace Dashboard Visual Alignment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restyle the complete Lead Trace frontend to use the Dashboard editorial visual language while preserving all routes, permissions, API behavior, and scientific review workflows.

**Architecture:** Move reusable design decisions into four global stylesheets (`tokens.css`, `base.css`, `components.css`, and `layouts.css`) loaded from one entrypoint. Keep Vue scoped styles only for domain-specific geometry such as PDF overlays, molecular diagrams, and lineage layouts; migrate repeated page shells, controls, tables, panels, statuses, and feedback states to shared global classes. Implement in an isolated worktree because the main workspace contains unrelated uncommitted Lead Trace changes.

**Tech Stack:** Vue 3, TypeScript, Vite, Vitest, Vue Test Utils, Playwright, CSS custom properties.

---

## Preconditions

- Use `superpowers:using-git-worktrees` and create branch `codex/leadtrace-dashboard-styles` below `.worktrees/`.
- Verify `.worktrees/` is ignored before creating the worktree.
- Run `npm test`, `npm run typecheck`, and `npm run build` in `leadtrace/frontend` before editing.
- If baseline verification fails, stop and report it instead of attributing the failure to this work.
- Preserve the unrelated modifications currently present in the main workspace. Do not copy them blindly into the worktree; reconcile only changes that are committed on the selected base.
- Use `superpowers:test-driven-development` for every structural or behavioral change.
- Use `superpowers:verification-before-completion` before claiming completion.

### Task 1: Establish the centralized stylesheet contract

**Files:**
- Create: `leadtrace/frontend/src/styles/base.css`
- Create: `leadtrace/frontend/src/styles/components.css`
- Create: `leadtrace/frontend/src/styles/layouts.css`
- Modify: `leadtrace/frontend/src/styles/tokens.css`
- Modify: `leadtrace/frontend/src/main.ts`
- Create: `leadtrace/frontend/tests/style-architecture.spec.ts`

**Step 1: Write the failing architecture test**

Create a Vitest test that reads frontend source files and asserts:

```ts
expect(mainSource).toContain('import "./styles/tokens.css"');
expect(mainSource).toContain('import "./styles/base.css"');
expect(mainSource).toContain('import "./styles/components.css"');
expect(mainSource).toContain('import "./styles/layouts.css"');
expect(componentSources.filter((source) => source.includes(".button-primary"))).toHaveLength(0);
expect(componentSources.filter((source) => source.includes(".admin-panel"))).toHaveLength(0);
```

Also assert that the shared stylesheet contains the canonical classes for `.page-shell`, `.page-heading`, `.panel`, `.data-table`, `.button-primary`, `.button-secondary`, `.button-danger`, `.status-chip`, `.page-state`, and `.form-control`.

**Step 2: Run the test and verify RED**

Run:

```bash
cd leadtrace/frontend
npx vitest run tests/style-architecture.spec.ts
```

Expected: FAIL because the three new stylesheets and imports do not exist and repeated styles remain in Vue files.

**Step 3: Define the Dashboard-aligned tokens**

Replace the existing token set with centralized values derived from `dashboard/styles.css`, while retaining temporary aliases for current component compatibility:

```css
:root {
  --ink: #172b3c;
  --ink-soft: #2b4051;
  --ink-muted: #6b7780;
  --paper: #f3f0e9;
  --paper-deep: #e8e3d9;
  --surface: #fbfaf7;
  --line: #d9d6ce;
  --line-strong: #c7c5bd;
  --coral: #e26c55;
  --coral-deep: #b84738;
  --teal: #167d78;
  --teal-pale: #d9ece7;
  --amber: #d59a34;
  --amber-pale: #f3e6c8;
  --danger: #9e3f35;
  --danger-soft: #f4ddd6;
  --font-serif: "Noto Serif SC Variable", Newsreader, Georgia, serif;
  --font-sans: "Noto Sans SC Variable", Manrope, "PingFang SC", sans-serif;
  --font-mono: "DM Mono", "SFMono-Regular", Consolas, monospace;
  --radius-sm: 2px;
  --radius-md: 4px;
  --radius-lg: 8px;
  --shadow-panel: 0 16px 40px rgba(23, 43, 60, .08);
}
```

Map legacy variables such as `--ink-950`, `--forest-750`, `--gold-100`, and `--canvas` to the new canonical variables until all scoped styles have migrated.

**Step 4: Add the shared global layers**

- Put reset, root typography, selection, focus-visible, skip-link, reduced motion, and screen-reader utilities in `base.css`.
- Put buttons, form controls, chips, cards, panels, tables, pagination, toolbars, empty/loading/error states, and inline feedback in `components.css`.
- Put application shell, sidebar, topbar, page container, heading, metric grids, split panes, review grids, and responsive breakpoints in `layouts.css`.
- Import the four files explicitly and in that order from `main.ts`.
- Do not import remote Google Fonts. Continue using the locally installed Noto variable font packages, with Dashboard-compatible fallbacks.

**Step 5: Run focused tests**

Run `npx vitest run tests/style-architecture.spec.ts tests/App.spec.ts`.

Expected: the import/class-presence assertions pass; duplicate-class assertions may remain intentionally RED until their migration tasks and should be split into task-specific assertions rather than disabled.

**Step 6: Commit**

```bash
git add leadtrace/frontend/src/styles leadtrace/frontend/src/main.ts leadtrace/frontend/tests/style-architecture.spec.ts
git commit -m "style: establish centralized dashboard design system"
```

### Task 2: Move AppShell into the global layout system

**Files:**
- Modify: `leadtrace/frontend/src/app/AppShell.vue`
- Modify: `leadtrace/frontend/src/styles/layouts.css`
- Modify: `leadtrace/frontend/src/styles/components.css`
- Modify: `leadtrace/frontend/tests/navigation.spec.ts`
- Modify: `leadtrace/frontend/e2e/accessibility.spec.ts`

**Step 1: Write failing shell tests**

Extend `navigation.spec.ts` to assert that the shell exposes stable structural hooks:

```ts
expect(wrapper.get("[data-app-shell]").classes()).toContain("application-shell");
expect(wrapper.get("[data-app-sidebar]").attributes("aria-label")).toBeTruthy();
expect(wrapper.findAll("[data-navigation-index]")).toHaveLength(12);
expect(wrapper.get("[data-app-topbar]").exists()).toBe(true);
```

The visible navigation count must still vary by role; query only the admin-mounted wrapper when asserting all 12 indices.

Add a Playwright assertion that keyboard focus reveals the skip link and that the mobile viewport has no horizontal page overflow.

**Step 2: Verify RED**

Run `npx vitest run tests/navigation.spec.ts` and confirm failure due to missing data hooks/numbering.

**Step 3: Refactor the shell template without changing behavior**

- Add structural data hooks.
- Render Dashboard-style two-digit navigation indices while retaining accessible labels.
- Keep the existing role filtering, links, account data, password link, logout handler, and `RouterView` unchanged.
- Add the Dashboard brand mark accent and sidebar footer status using decorative elements with `aria-hidden="true"`.

**Step 4: Centralize shell CSS**

- Move every generic shell selector out of the component `<style scoped>` block into `layouts.css`.
- Remove the scoped style block from `AppShell.vue` once parity is reached.
- Use a 238px desktop sidebar, 82px topbar, ink background, coral active border, and paper content background.
- At the mobile breakpoint, change the fixed sidebar into a compact document-flow header/navigation without changing link availability.

**Step 5: Verify GREEN**

Run:

```bash
npx vitest run tests/navigation.spec.ts tests/auth.spec.ts
npx playwright test e2e/accessibility.spec.ts --project=chromium
```

Expected: role-aware navigation and accessibility tests pass.

**Step 6: Commit**

```bash
git add leadtrace/frontend/src/app/AppShell.vue leadtrace/frontend/src/styles leadtrace/frontend/tests/navigation.spec.ts leadtrace/frontend/e2e/accessibility.spec.ts
git commit -m "style: align leadtrace application shell with dashboard"
```

### Task 3: Consolidate shared page, form, feedback, and authentication styles

**Files:**
- Modify: `leadtrace/frontend/src/styles/components.css`
- Modify: `leadtrace/frontend/src/styles/layouts.css`
- Modify: `leadtrace/frontend/src/auth/LoginPage.vue`
- Modify: `leadtrace/frontend/src/auth/ChangePasswordPage.vue`
- Modify: `leadtrace/frontend/src/admin/AdminTableState.vue`
- Modify: `leadtrace/frontend/tests/auth.spec.ts`
- Modify: `leadtrace/frontend/tests/style-architecture.spec.ts`

**Step 1: Write failing shared-component tests**

Add assertions that login and change-password views use the same `.auth-shell`, `.auth-panel`, `.form-field`, and button classes. Assert that `AdminTableState` uses the centralized `.page-state` variants.

**Step 2: Verify RED**

Run `npx vitest run tests/auth.spec.ts tests/style-architecture.spec.ts`.

Expected: FAIL because the shared hooks are absent and scoped styles still define generic controls.

**Step 3: Implement shared primitives**

- Define consistent labels, inputs, search inputs, selects, textareas, disabled states, error states, helper text, button sizes, button variants, loading spinners, empty states, and request IDs in `components.css`.
- Define authentication centering and split-brand layout in `layouts.css`.
- Refactor the two auth templates to use shared classes while preserving validation, default account helpers, busy states, and redirects.
- Refactor `AdminTableState` to use the same global feedback component classes.
- Remove only generic scoped declarations; leave any truly page-specific illustration/placement rules local.

**Step 4: Verify GREEN**

Run `npx vitest run tests/auth.spec.ts tests/admin.spec.ts tests/style-architecture.spec.ts`.

**Step 5: Commit**

```bash
git add leadtrace/frontend/src/styles leadtrace/frontend/src/auth leadtrace/frontend/src/admin/AdminTableState.vue leadtrace/frontend/tests
git commit -m "style: centralize leadtrace forms and feedback states"
```

### Task 4: Restyle the complete published-data experience

**Files:**
- Modify: `leadtrace/frontend/src/papers/OverviewPage.vue`
- Modify: `leadtrace/frontend/src/papers/PaperLibraryPage.vue`
- Modify: `leadtrace/frontend/src/papers/PaperDetailPage.vue`
- Modify: `leadtrace/frontend/src/papers/QualitySummary.vue`
- Modify: `leadtrace/frontend/src/papers/ReleaseVerificationBadge.vue`
- Modify: `leadtrace/frontend/src/styles/components.css`
- Modify: `leadtrace/frontend/src/styles/layouts.css`
- Modify: `leadtrace/frontend/tests/published-pages.spec.ts`
- Modify: `leadtrace/frontend/e2e/visitor.spec.ts`

**Step 1: Write failing published-page tests**

Assert representative structures rather than pixel values:

```ts
expect(wrapper.get(".page-heading").classes()).toContain("page-heading--editorial");
expect(wrapper.findAll(".metric-card--dashboard")).toHaveLength(6);
expect(wrapper.get("[data-filter-form]").classes()).toContain("filter-toolbar");
expect(wrapper.get("[data-paper-detail]").classes()).toContain("detail-layout");
```

Add visitor E2E assertions that filtering and pagination still work after the markup/class migration.

**Step 2: Verify RED**

Run `npx vitest run tests/published-pages.spec.ts` and confirm the new structural assertions fail.

**Step 3: Restyle Overview**

- Use an editorial page heading with release context aside.
- Convert the six metrics to the Dashboard grid language: mono index, serif value, unit label, accent bar, fine borders, and low shadow.
- Preserve all API states and release verification behavior.

**Step 4: Restyle Paper Library**

- Convert the form into a shared filter toolbar that collapses predictably at smaller widths.
- Use global table/list, metadata, status, pagination, and action styles.
- Preserve query-string synchronization, reset behavior, sorting, and all filter fields.

**Step 5: Restyle Paper Detail and supporting paper components**

- Use a main/aside detail layout for publication identity, quality state, lineage, evidence, and structures.
- Centralize badges, metadata rows, definition lists, evidence panels, and quality summaries.
- Keep structure rendering and source links unchanged.

**Step 6: Remove duplicated generic page CSS**

Delete scoped definitions of `.page-heading`, `.page-state`, buttons, generic panels, badges, filters, and pagination. Retain only view-specific grid placement that is not reusable.

**Step 7: Verify GREEN**

Run:

```bash
npx vitest run tests/published-pages.spec.ts tests/molecule-objects.spec.ts
npx playwright test e2e/visitor.spec.ts --project=chromium
```

**Step 8: Commit**

```bash
git add leadtrace/frontend/src/papers leadtrace/frontend/src/styles leadtrace/frontend/tests/published-pages.spec.ts leadtrace/frontend/e2e/visitor.spec.ts
git commit -m "style: align published paper pages with dashboard"
```

### Task 5: Unify review tasks, changesets, approvals, and release controls

**Files:**
- Modify: `leadtrace/frontend/src/review/tasks/TaskListPage.vue`
- Modify: `leadtrace/frontend/src/review/changesets/ChangesetIndexPage.vue`
- Modify: `leadtrace/frontend/src/review/changesets/ChangesetPage.vue`
- Modify: `leadtrace/frontend/src/review/changesets/ChangesetDiff.vue`
- Modify: `leadtrace/frontend/src/review/changesets/SubmissionPage.vue`
- Modify: `leadtrace/frontend/src/review/changesets/ScientificEditors.vue`
- Modify: `leadtrace/frontend/src/review/conflicts/ConflictResolver.vue`
- Modify: `leadtrace/frontend/src/approvals/ApprovalCenterPage.vue`
- Modify: `leadtrace/frontend/src/approvals/ScientificApprovalReview.vue`
- Modify: `leadtrace/frontend/src/releases/ReleasePage.vue`
- Modify: `leadtrace/frontend/src/releases/RollbackPage.vue`
- Modify: `leadtrace/frontend/src/styles/components.css`
- Modify: `leadtrace/frontend/src/styles/layouts.css`
- Modify: `leadtrace/frontend/tests/review-workflow.spec.ts`
- Modify: `leadtrace/frontend/tests/scientific-editors.spec.ts`
- Modify: `leadtrace/frontend/tests/approval-release.spec.ts`
- Modify: `leadtrace/frontend/e2e/review-minimal.spec.ts`

**Step 1: Write failing workflow layout tests**

Add assertions that representative review pages use `.review-workspace`, `.workspace-toolbar`, `.panel`, `.data-table`, `.status-chip`, and shared action classes. Preserve existing behavioral assertions and avoid testing CSS property values in jsdom.

**Step 2: Verify RED**

Run the three focused Vitest suites and confirm failures are caused by missing shared structure.

**Step 3: Apply a common review workspace hierarchy**

- Standardize each page as heading, status/metric strip, toolbar, and one or more work panels.
- Use shared tabs, diff rows, decision panels, validation summaries, textareas, and action bars.
- Keep autosave, conflict resolution, submission, approval, release preview, publish, and rollback event handlers untouched.
- Keep destructive controls visually distinct and never downgrade confirmation requirements.

**Step 4: Remove repeated generic CSS**

Move shared table, panel, toolbar, tab, status, form, button, and page-state rules into global styles. Keep domain-specific diff alignment and editor pane geometry scoped where appropriate.

**Step 5: Verify GREEN**

Run:

```bash
npx vitest run tests/review-workflow.spec.ts tests/scientific-editors.spec.ts tests/approval-release.spec.ts
npx playwright test e2e/review-minimal.spec.ts --project=chromium
```

**Step 6: Commit**

```bash
git add leadtrace/frontend/src/review leadtrace/frontend/src/approvals leadtrace/frontend/src/releases leadtrace/frontend/src/styles leadtrace/frontend/tests leadtrace/frontend/e2e/review-minimal.spec.ts
git commit -m "style: unify review approval and release workspaces"
```

### Task 6: Consolidate all administration pages around one table/panel system

**Files:**
- Modify: `leadtrace/frontend/src/admin/AuditPage.vue`
- Modify: `leadtrace/frontend/src/admin/FilesPage.vue`
- Modify: `leadtrace/frontend/src/admin/ImportsPage.vue`
- Modify: `leadtrace/frontend/src/admin/JobsPage.vue`
- Modify: `leadtrace/frontend/src/admin/PaperCatalogPage.vue`
- Modify: `leadtrace/frontend/src/admin/PaperCatalogDetailPage.vue`
- Modify: `leadtrace/frontend/src/admin/SystemPage.vue`
- Modify: `leadtrace/frontend/src/admin/UsersPage.vue`
- Modify: `leadtrace/frontend/src/styles/components.css`
- Modify: `leadtrace/frontend/src/styles/layouts.css`
- Modify: `leadtrace/frontend/tests/admin.spec.ts`
- Modify: `leadtrace/frontend/tests/admin-paper-catalog.spec.ts`
- Modify: `leadtrace/frontend/tests/style-architecture.spec.ts`

**Step 1: Write failing admin consistency tests**

Mount the simple admin pages and assert they use `.admin-page`, `.page-heading`, `.admin-panel`, `.data-table`, `.table-actions`, and shared buttons. Add a source-level assertion that the one-line admin components no longer contain repeated table/control CSS.

**Step 2: Verify RED**

Run `npx vitest run tests/admin.spec.ts tests/admin-paper-catalog.spec.ts tests/style-architecture.spec.ts`.

**Step 3: Normalize admin templates**

- Expand minified one-line templates only where needed for maintainability.
- Apply one shared admin page shell and table system.
- Use semantic status chips for integrity, job, user, import, audit, and health states.
- Preserve every data request, retry, create, disable, revoke, inspect, import, and catalog workflow.

**Step 4: Delete repeated scoped table/control styles**

Remove local copies of page padding, white panel, table collapse, cell spacing, action buttons, input styling, empty states, and headings. Keep only page-unique grid layouts or visualization rules.

**Step 5: Verify GREEN**

Run the focused tests, then `npm run typecheck`.

**Step 6: Commit**

```bash
git add leadtrace/frontend/src/admin leadtrace/frontend/src/styles leadtrace/frontend/tests
git commit -m "style: consolidate leadtrace administration pages"
```

### Task 7: Align scientific components without breaking domain geometry

**Files:**
- Modify: `leadtrace/frontend/src/activities/ActivityEditor.vue`
- Modify: `leadtrace/frontend/src/compounds/CompoundEditor.vue`
- Modify: `leadtrace/frontend/src/evidence/EvidenceCard.vue`
- Modify: `leadtrace/frontend/src/evidence/EvidenceEditor.vue`
- Modify: `leadtrace/frontend/src/lineages/LineageEditor.vue`
- Modify: `leadtrace/frontend/src/lineages/LineageView.vue`
- Modify: `leadtrace/frontend/src/structures/MoleculePairCard.vue`
- Modify: `leadtrace/frontend/src/structures/StructureComparison.vue`
- Modify: `leadtrace/frontend/src/structures/StructureEditor.vue`
- Modify: `leadtrace/frontend/src/visual-objects/CompoundBindings.vue`
- Modify: `leadtrace/frontend/src/visual-objects/ImageBindings.vue`
- Modify: `leadtrace/frontend/src/visual-objects/ObjectInspector.vue`
- Modify: `leadtrace/frontend/src/pdf-viewer/PdfReviewCanvas.vue`
- Modify: `leadtrace/frontend/src/pdf-viewer/RegionOverlay.vue`
- Modify: `leadtrace/frontend/src/styles/components.css`
- Modify: `leadtrace/frontend/tests/molecule-objects.spec.ts`
- Modify: `leadtrace/frontend/tests/regions.spec.ts`
- Modify: `leadtrace/frontend/tests/structure-editor.spec.ts`

**Step 1: Add failing shared-style tests**

Assert editors use shared `.editor-form`, `.form-field`, `.panel`, `.status-chip`, and button classes. Assert PDF and molecule components retain their existing data hooks and ARIA labels.

**Step 2: Verify RED**

Run the three focused scientific component suites.

**Step 3: Migrate reusable visual rules**

- Move repeated editor field, card chrome, metadata, badge, and action rules into `components.css`.
- Adopt the Dashboard surface, border, typography, and semantic color tokens.
- Keep canvas sizing, overlays, bounding boxes, molecule image dimensions, structure comparison geometry, and lineage graph geometry scoped in their owning components.
- Do not change chemical data, SMILES handling, object binding, region coordinates, or emitted payloads.

**Step 4: Verify GREEN**

Run:

```bash
npx vitest run tests/molecule-objects.spec.ts tests/regions.spec.ts tests/structure-editor.spec.ts tests/scientific-editors.spec.ts
```

**Step 5: Commit**

```bash
git add leadtrace/frontend/src/activities leadtrace/frontend/src/compounds leadtrace/frontend/src/evidence leadtrace/frontend/src/lineages leadtrace/frontend/src/structures leadtrace/frontend/src/visual-objects leadtrace/frontend/src/pdf-viewer leadtrace/frontend/src/styles leadtrace/frontend/tests
git commit -m "style: align scientific review components with dashboard"
```

### Task 8: Responsive, accessibility, visual review, and final cleanup

**Files:**
- Modify: `leadtrace/frontend/src/styles/base.css`
- Modify: `leadtrace/frontend/src/styles/components.css`
- Modify: `leadtrace/frontend/src/styles/layouts.css`
- Modify: `leadtrace/frontend/tests/style-architecture.spec.ts`
- Modify: `leadtrace/frontend/e2e/accessibility.spec.ts`
- Modify: `leadtrace/frontend/e2e/visitor.spec.ts`
- Modify: `leadtrace/frontend/e2e/review-minimal.spec.ts`

**Step 1: Add failing responsive/accessibility assertions**

- Assert no horizontal document overflow at 1440px, 1024px, and 390px on overview, library, detail, task list, changeset, and one admin table page.
- Assert visible keyboard focus on navigation, form controls, table actions, and primary/danger actions.
- Assert key landmark and heading structure remains valid.
- Assert reduced-motion media rules cover transitions, animations, and smooth scrolling.

**Step 2: Verify RED where gaps exist**

Run the focused Playwright specs and capture the exact overflowing/focus-deficient components.

**Step 3: Fix responsive and accessibility gaps centrally**

- Prefer changes in `layouts.css` and `components.css` over page-local media queries.
- Allow wide scientific tables and PDF workspaces to scroll inside labeled containers rather than overflowing the document.
- Ensure text/status contrast meets WCAG AA for normal text.
- Keep focus indicators visible on dark sidebar and light content backgrounds.

**Step 4: Perform source-level style consolidation audit**

Run:

```bash
rg -n "\.button-primary|\.button-secondary|\.button-danger|\.admin-panel|\.page-heading|\.page-state|table\s*\{" leadtrace/frontend/src --glob '*.vue'
```

Expected: no repeated generic definitions remain. Any match must be documented as a component-specific exception in the test or migrated globally.

Also run a color-literal audit:

```bash
rg -n "#[0-9a-fA-F]{3,8}|rgba?\(" leadtrace/frontend/src --glob '*.vue'
```

Expected: remaining literals are limited to domain visuals that cannot meaningfully use semantic tokens.

**Step 5: Run complete verification**

Run:

```bash
cd leadtrace/frontend
npm test
npm run typecheck
npm run build
npx playwright test e2e/visitor.spec.ts e2e/review-minimal.spec.ts e2e/accessibility.spec.ts --project=chromium
```

Expected: all commands exit 0 with no new warnings.

**Step 6: Perform visual comparison**

Capture representative desktop and mobile screenshots for:

- Dashboard overview
- Lead Trace overview
- Paper library
- Paper detail
- Review task list
- Changeset workspace
- Approval center
- One administration table

Compare typography, sidebar, paper background, spacing, panel borders, metric hierarchy, action colors, status semantics, focus visibility, and overflow. Fix systemic issues in the centralized stylesheets.

**Step 7: Commit**

```bash
git add leadtrace/frontend/src/styles leadtrace/frontend/tests/style-architecture.spec.ts leadtrace/frontend/e2e
git commit -m "test: verify dashboard-aligned leadtrace presentation"
```

## Completion Criteria

- All Lead Trace routes use the Dashboard-aligned shell and visual tokens.
- Public, review, approval, release, administration, authentication, and scientific tooling pages are visually coherent.
- Shared styles live in the four centralized style files; scoped styles contain only genuinely component-specific geometry.
- Existing business behavior and role-based navigation remain unchanged.
- Vitest, TypeScript, production build, selected Playwright flows, responsive checks, and accessibility checks pass.
- Visual comparison shows one coherent product family without sacrificing complex-workspace usability.
