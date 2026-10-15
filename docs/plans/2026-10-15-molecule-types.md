# Molecule types for pending articles — design and implementation plan

> Execute with superpowers:executing-plans; independent frontend/backend tasks use superpowers:dispatching-parallel-agents.

**Goal:** Apply the user-approved molecule-type classification to every currently pending production article, preserving original submissions and unrelated scientific/human content.

**Architecture:** Retain `research_profile.modalities` as the compatible storage array; replace ordinary heading with 分子类型 and present fixed main types plus supplementary features in one card. Each selected label remains a source-backed term with its own evidence. No schema migration. Explicitly authorized scoped replacement of modalities uses a fresh exact research-profile baseline; other profile groups remain byte-shape-equivalent. Existing snapshots remain immutable. Producer and fresh reviewer run through frozen Codex adapters; supervisor never reads PDF/source text/images/native reasoning. User authorized actual main-site updates, not copies.

**Vocabulary:** Main types: 小分子抑制剂、小分子激动剂、小分子拮抗剂、小分子反向激动剂、小分子激活剂、小分子调节剂（作用待细分）、PROTAC、分子胶、其他、待明确. Supplementary features: 变构调节、共价作用、大环类、肽／肽模拟物、前药. These are overlapping multi-select tags. Do not classify peptides automatically as conventional small molecules. With a peptide inhibitor use 其他 (explain peptide inhibitor) + 肽／肽模拟物, adding 大环类 only if supported. At least one main type; unknown/other requires explanation. Classify article's actual optimized series, not comparator/background compounds. No automatic conversion of broad old 直接靶点调节 to inhibitor. Source explanation names series where multiple series differ. Old labels preserved/displayed as legacy until explicitly reclassified.

**Tech Stack:** Vue/TypeScript, Python/Pydantic/SQLAlchemy, PostgreSQL, isolated Codex CLI scientific runtime, Playwright.

## Task1 — frontend vocabulary and display
Files: frontend/src/review/paper/articleMetadata.ts, ResearchProfile.vue, ResearchProfileEditor.vue, ArticleMetadata.vue as required; frontend/src/i18n messages; corresponding unit and e2e tests.
1. Add regression tests for two selectable groups, 15 total choices, inhibitor label not aliased to direct modulation, legacy broad label not silently converted, unchanged sources retained, single article card desktop/mobile.
2. Run targeted tests to demonstrate failure.
3. Implement grouped choices and compact grouped reading in same module; preserve aliases only where scientifically exact. Keep mechanisms and evidence folding unchanged.
4. Run frontend metadata tests, typecheck and focused Playwright. Parent runs final build/review.

## Task2 — restricted pending classification replacement
Files: backend/app/publications/metadata_supplement.py and backend/tests/test_publications.py; ops/runbooks/article_metadata_supplement.md.
1. Add tests for exact-baseline modalities replacement, unrelated profile fields/old snapshot preserved, pending/unconfirmed, stale baseline/version rejection, cannot mix modes/fields, missing primary type/unknown vocabulary/empty evidence rejected, idempotency.
2. Run these against disposable *_test database only, serial.
3. Add `expected_classification_baseline` exact full research_profile argument; updates exactly research_profile, other groups untouched; replace modalities only, meaningful nonempty fixed tags with source/evidence; no cleanup combined. Preserve shape with deepcopy after schema validation. Bind argument into request identity.
4. Run complete relevant publication supplement DB suite. Existing broad legacy records remain readable.

## Task3 — current guidance and scientific batch
Files: docs/ai-prefill/{extraction-guide,self-check-guide,quality-audit-protocol}.md; START_HERE entry if needed. Runtime only in ignored leadtrace-data/article-types-20261015/.
1. Replace current modality rules with approved taxonomy and series-only scope, peptide/unknown safeguards, evidence requirements; retain one current guide.
2. Capture fresh full pending queue, versions/hashes/source identities. Freeze current guidance and PDF per new producer job; no credentials or application access.
3. Selected runtime codex gpt-6-astra high reads actual PDF and existing metadata, proposes modalities-only source-backed replacement, self-checks. Fresh reviewer checks source and all labels/evidence, may repair in same review call and self-check; separate sessions recorded.
4. Validate identities/manifests/sessions/candidate hashes/vocabulary and unchanged other fields; record scope, SI gaps and no full inventory re-audit. Accept only for pending display. Handle provider failures as execution failures, never empty classification.

## Task4 — authorized main-site delivery
1. Independent code/ops review, meaningful tests/build, commit source and fast-forward main; retain worktrees. Archive completed plan outside tracked tree with hash when done.
2. New immutable release, preserved auth/Ketcher/CSP and current frontend fix; encrypted production backup hash/decryption/restore verification to separate staging DB, never test reset.
3. Rehearse exact guarded classification proposals against restored snapshot, ensure queue and old snapshots/unrelated science preserved.
4. Maintenance, no running jobs, switch source/frontend with verified rollback. Apply exact proposals once in transaction after fresh baseline check. Keep12/all-current pending, preserve old snapshots and audit.
5. Read back all fields, verify unchanged scientific tables, audit/readiness/CSP, browser all articles at desktop/mobile; new heading/two groups/quotations correct. Restore access; report per-article types and gaps. Update run/production handoffs; never replay historical supplements.
