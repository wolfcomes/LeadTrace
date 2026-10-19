# Focused Activity Comparison Implementation Plan

**Goal:** Reduce reviewer scanning by showing relevant Compounds and focused measurement groups with similar measurement coverage adjacent.
**Architecture:** Keep the existing read-only API and navigation guards. Derive exact assay/metric/unit groups in the frontend, retain distinct context columns, choose the most widely recorded group and condition initially, and let reviewers add groups/conditions. Hide Compounds without selected measurements by default, with an explicit reveal control. Order rows by measurement-set similarity, never by inferred biological or structural similarity.
**Tech Stack:** Vue 3, TypeScript, Vitest, Playwright.

## Approved design and defaults

- Default to the group with the most distinct Compounds; within it default to its most widely recorded condition. Stable text ordering breaks ties. Counts refer to distinct Compounds, not observation counts.
- A group selector switches the focused group; a multiple-group picker adds/removes groups. A condition picker chooses exact context columns, preserving all repeated observations and qualifiers.
- Initially display only Compounds with an Activity in a selected column. Show how many rows are hidden and allow revealing them, including Compounds with no Activity anywhere.
- Default row order groups identical selected-measurement sets, then places the closest sets adjacent using Jaccard overlap. Stable natural Compound labels order each group and break ties. No numeric clustering, unit conversion, semantic assay merging, or data mutation.
- Compact headers show assay/metric/unit and collapsed full conditions; names remain available on demand. Keep search, label/original sorting, exact Activity navigation, saved-value refresh and state/scroll persistence.
- Empty/error/loading states remain explicit. New records refresh counts; deleted selections cannot expose stale values.

## Tasks

1. Add failing frontend tests in `leadtrace/frontend/tests/activity-comparison.spec.ts` and a helper suite for group counts, exact condition preservation, default relevant-only display, group/condition changes, optional hidden rows, deterministic similar-set ordering and refresh/navigation state. Run `npm --prefix leadtrace/frontend test -- --run tests/activity-comparison.spec.ts tests/activity-comparison-order.spec.ts` and verify failures.
2. Extend `src/review/paper/activityComparison.ts` with group derivation and deterministic row ordering; update `ActivityComparison.vue` controls and compact layout. Add bilingual strings. Run focused tests, adapt existing navigation tests only where the approved defaults changed.
3. Update synthetic Playwright flow for focused defaults, multiple groups/conditions, hidden counts, exact edit/return state and mobile scrolling. Update guide source and regenerate documents. Run full frontend tests, typecheck/build, guide check and diff check; inspect desktop/mobile screenshots.
4. Independent review, address findings, commit. Preserve unrelated root work when merging, push and deploy the tested frontend under existing delivery authorization. This frontend-only change needs no migration or backend restart. Verify live read-only behavior and preserve rollback artifacts.

## Verification outcome

- Baseline comparison/navigation suites: 12 passed. New defaults and grouping tests reproduced the previous behavior before implementation.
- Final frontend suite: 419 passed across 68 files; typecheck and production build passed.
- Synthetic Playwright: sparse 40-Compound/7-condition data defaults to 24 relevant Compounds and 1 condition. Explicit hidden-row reveal, multi-group/condition selection, exact Activity edit/return, selection persistence and mobile overflow checks passed.
- Independent review identified indistinguishable collapsed condition headers. Actual context now remains visible as a two-line preview; a regression reproduced the issue before the fix.
- Exact grouping, duplicate observations, precision, deterministic similarity ordering, empty-to-populated refresh and old workspace response protection verified. Guide generation and whitespace checks passed.
- Frontend-only release; no backend or database changes required.


## Live-data follow-up

Readonly production smoke exposed a group with 26 Compounds and 52 exclusive
conditions (each condition covered one Compound), so a single-condition default
still failed the comparison goal. For groups with more than one Compound where
all conditions are exclusive, select the group's conditions by default and render
one compact group column with every observation's own condition alongside its
value. Shared-condition groups retain separate columns. No values or records are
combined, no equivalence is inferred, and condition filters remain available.
A failing regression reproduces the one-row problem; synthetic browser coverage
also checks 30 Compounds / 60 exclusive observations, exact navigation and return.

Final follow-up validation: 421 frontend tests passed, typecheck/build passed,
2 synthetic browser scenarios passed (shared and exclusive conditions), guide
and whitespace checks passed. Independent review found no blocker in compact
per-observation conditions. Explicit regression preserves repeated Activity IDs,
precision and qualifiers plus exact click targets.
