# PfPKG SAR and synthesis Lineage reorganization

**Goal:** implement explicit separate Lineage types, apply reviewed PfPKG separation,
and remove misleading historical scientific records from the active preview.

**Architecture:** `lineage_type = sar | synthesis | unspecified` on Lineage,
backward-compatible historical records/snapshots, independent shared Compound IDs.
UI groups by semantic type, retains point/structure modes and Edge navigation.
Experimental-route records are grounded in Methods plus Scheme evidence, while
SAR comparisons stay baseline comparisons. Cleanup is journaled and reversible
from a complete pre-change scientific snapshot.

**Stack:** SQLAlchemy/PostgreSQL/Alembic/FastAPI, Vue/TypeScript/Vitest/Playwright.

## Execution

1. Capture all seven scientific snapshots and baseline hashes before schema/data
   changes. Verify target instance identity and PfPKG version551. Preserve other
   six complete snapshots.
2. Backend worker: enum/model + migration0027; schemas/services/router; copy,
   snapshot/export/publish/AI-prefill contracts; backward-compatible unspecified
   handling. Write/run targeted regression tests. Do not operate live instance.
3. Frontend worker: API schemas/create-edit, typed grouping/default SAR, deep-link
   group selection, category badges; retain graph and contextual evidence.
   Write/run tests and build. No science writes.
4. Read-only scientific worker: review all existing53 Edges plus relevant structure
   identity and evidence conflicts against original PDF/Methods. Produce explicit
   keep/correct/delete plan; identify minimum reliable missing route intermediates.
5. Main agent: update prefill guidance and build reviewed, version-checked cleanup
   and organization plan, with exact old IDs, source evidence and rationales.
   Remove rejected/misleading active relations; preserve verified compounds and
   Activity. Correct reliable identity issues or withhold disputed structures with
   honest unresolved status. Do not bulk-delete unrelated data or invent routes.
6. Integrate tests, migrate only verified preview DB, restart owned backend through
   preview lifecycle, verify same instance/account access. Apply reviewed plan via
   version-checked editor APIs and record every mutation with before/after versions.
7. Verify category counts and corrected/deleted IDs, endpoint identities, Evidence,
   retained Activities and six untouched workspace hashes. Live browser checks of
   both groups/modes, edge details and shared compound navigation. Record full
   after-snapshot/report and update live HANDOFF.

The user has authorized implementing the previously discussed classification and
cleaning unreliable PfPKG data. Routine execution needs no additional permission.
Historical snapshot files remain audit artifacts, not active review data.

## Accepted scope refinement during execution

Main Compound catalog covers compounds appearing in main narrative/SAR, including
explicitly discussed intermediates such as 10g,11g,11a,58,61. Do not expand it with
experimental-only intermediates/forms. Record those within synthesis route/step
descriptions and precise Evidence for now. Multi-step condensed Edges must state
that they are route summaries, including hidden intermediates and chemical forms;
never label them as a direct reaction. Separate route-local intermediate entities
would be a later model extension if interactive intermediate nodes are required.
