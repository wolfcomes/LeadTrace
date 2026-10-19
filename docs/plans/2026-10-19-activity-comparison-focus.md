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
