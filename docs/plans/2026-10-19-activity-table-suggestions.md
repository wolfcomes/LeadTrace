# Suggested Activity Tables Design and Implementation Plan

**Goal:** Automatically create editable, browser-saved initial activity tables by shared Compound coverage, preserving manual table configurations.
**Architecture:** Reuse exact assay/metric/unit columns, existing local storage and read-only navigation. Deterministic coverage grouping uses pairwise Jaccard >= 0.8 (complete-link admission, no chain merging), at most six columns per table. Exact coverage sets are grouped first. All matching observations remain independently visible. No condition semantics, unit conversion, value-based clustering or new APIs.
**Tech Stack:** Vue 3, TypeScript, Zod, Vitest, Playwright.

## Approved design

- First successful comparison load with activities and no persisted settings generates and saves recommendations. Existing settings, including an intentionally empty saved list, suppress automatic generation. Preserve unsaved local work, editor state, account/workspace boundaries and storage failures. Use existing Web Locks and latest-storage checks.
- Manual Generate suggested tables appends only measurement identities absent from saved tables and current draft, including subset columns as represented. Repeated generation adds nothing; additions never overwrite existing tables. A clean draft may select the first new table; dirty drafts remain open. Deleted/removed measurement columns may be generated again by an explicit click, never by refresh.
- Neutral localized names with unique numbering. All-record columns preserve exact identities, contexts, precision, hints and repeats. Table rows are the union of relevant Compounds, natural labels. Default collapsed column settings for generated tables; existing editing remains accessible.
- Maximum six columns per suggested table, fifty total saved tables under existing schema. Retain singleton groups. Explicitly report any recommendations omitted because of storage/configuration limits; do not report full coverage if partial.
- Show table column/Compound counts on selected table. Grouping only helps layout and does not assert experimental equivalence or reproduce a source table.
- Browser-local per username/workspace persistence remains unchanged. No backend changes, scientific writes, migrations or source reading.

## Implementation steps

1. Run baseline helper/UI/navigation suites. Add failing grouping tests: exact/near coverage, strict small subsets, bridge chain, deterministic order, width cap, duplicates, unmatched singleton, exact unit identity.
2. Implement suggestion helper in activityTableBuilder.ts. Run helper tests. Add failing component tests for first-load save, persistence/edit preservation, explicit append/idempotence, empty/deleted settings, storage failure, asynchronous account/workspace switches.
3. Integrate ActivityComparison.vue generation with current local storage lock and conflict semantics. Adapt manual-builder tests to explicitly request empty tables; retain navigation/concurrency tests. Add bilingual copy and guide documentation.
4. Update synthetic browser fixtures to retain manual paths and add automatic-generation/save/edit/reload flow. Run all frontend tests, typecheck/build, guide and whitespace checks, independent review. Inspect real comparison outputs read-only for grouping density (no source documents).
5. Merge with root dirty files backed up and guide changes three-way merged; preserve unrelated work. Push and frontend-only deploy under standing authorization. Verify live readonly browser and asset hashes/readiness/audit. Record handoff; retain worktrees.
