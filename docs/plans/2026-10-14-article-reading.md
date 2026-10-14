# Article Information Reading Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Apply the approved compact reviewer/Admin metadata design and controlled modalities to the main site.

**Architecture:** Shared Vue metadata presentation/editor and vocabulary. Preserve frozen legacy fields and source provenance; retire molecular_forms from normal UI/new extraction. Main-site code delivery with no scientific data import or schema change.

**Tech Stack:** Vue3/TypeScript/Zod, Vitest/Playwright, Python/Pydantic AI prefill validation.

### Task1 — Controlled vocabulary and regressions
Files: frontend/src/review/paper/articleMetadata.ts; frontend/tests/article-research-metadata.spec.ts; frontend/e2e/article-metadata.spec.ts.
Add failing interaction tests for fixed selection, original legacy labels, optional retired fields, collapsed source visibility and review issue visibility. Run npm test -- tests/article-research-metadata.spec.ts, observe meaningful failures. Implement shared constants and compatibility handling, then rerun.

### Task2 — Reviewer and Admin presentation
Files: ArticleMetadata.vue, ResearchProfile.vue, ResearchProfileEditor.vue, BibliographyEditor.vue, approvals/ResearchProfileComparison.vue, SubmissionComparison.vue, i18n/en-article-metadata.ts.
Remove routine Abstract metadata from reading, show only actionable issues. Retire molecular forms, preserve hidden payload on ordinary unrelated saves. Compact target rows with primary first; fold details; controlled modalities selected with source editor. Long text areas for evidence. Changed provenance expanded on Admin side, unchanged evidence folded. Run frontend tests, typecheck, build and focused Playwright responsive/UI tests.

### Task3 — Future prefill consistency
Files: docs/ai-prefill/extraction-guide.md, relevant prompt/checklist and ops validation modules.
Read START_HERE and current run handoff. Update current guides only; frozen bundles unchanged. Fixed modalities and no molecular forms in new extraction. Validate unsupported new terms as review issues with legacy compatibility. Run targeted deterministic AI contract tests (no production DB) and document limits.

### Task4 — Verification and delivery
Independent code review; full frontend tests/typecheck/build plus scoped browser tests. Commit and fast-forward main preserving untracked work. Freeze release, stage with production CSP, preserve old hashed assets, graceful frontend reload. Update backend worker guide source only if necessary via authorized versioned release with ready/audit checks, otherwise document actual served guide version. Verify real main-site three pending pages read-only, API/snapshots unchanged, exact release hashes/CSP. Save runtime evidence and handoff. Archive completed operational plans with hashes before integration.
