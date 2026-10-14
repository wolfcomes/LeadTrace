# Article modules and original evidence implementation plan

User approved 2026-10-14. Continue in retained codex/article-metadata worktree.

Goal: compact two-column Reviewer article dashboard and direct source quotations, with paired Admin comparisons, delivered on main site and three existing article examples.
Architecture: optional per-entry evidence list in article JSON metadata, backwards-compatible serialization. Shared evidence presentation receives authenticated paper/source context. Reviewer dashboard uses six bounded modules; Admin keeps before/after with paired scrolling, changed evidence visible and unchanged fields folded.
Tech stack: Vue/TypeScript, Pydantic/SQLAlchemy/PostgreSQL, isolated Codex scientific adapter.

## Approved design
Desktop rows: modalities/mechanisms (220px), targets/optimization goals (320px), diseases/PDB (320px). Headers/counts fixed; one body scroll per module, keyboard accessible. Mobile single column with relaxed heights. Abstract full width. Evidence folded by default; exact quotation, document/page locator, existing explanation, optional lazy original crop. Never present paraphrase as quotation. Admin avoids nested four columns, aligns paired groups and entries and shares bounded scroll for long pair groups.

## Tasks and verification
1. Add failing backend contract tests for optional evidence on SourceBackedLabel, ResearchTarget, PdbReference; old payloads unchanged, invalid page/bbox/URL rejected. Implement ArticleEvidence: source_kind main_pdf/supplement/external, quoted_text (optional only with explicit unavailable reason), page_number, locator, source_url for external (https/http only), bbox optional normalized coordinates, source_sha256 optional. Main PDF page required; supplement cannot silently link main PDF. Preserve absent evidence fields.
2. Add frontend tests for quotations versus source descriptions, fold defaults, evidence-only diff, editor roundtrip, no context no unsafe PDF locator. Implement shared evidence UI and dashboard, preserving Admin pairing. Add meaningful browser tests desktop/mobile and paired scroll.
3. Add operator-only evidence supplement with expected full baseline, version/hash guards, evidence-only additive changes preserving every existing metadata entry/field and prior evidence. Immutable pending replacement via existing supplement mechanism, no reviewer impersonation. Tests on article_metadata_test only and run backend DB suites serially.
4. Update current extraction/selfcheck/audit guidance and schema consumers. Original quotations must be verbatim, individually located and source separated; no invented quotes or coordinates.
5. Fresh source-identity baselines for 3 authorized production examples; freeze new scientific producer and fresh reviewer jobs, selected codex gpt-6-astra high, current guides. Supervisor does not read sources or reasoning logs. Each output binds baseline and source hash and lists item-level evidence or explicit gaps. Review all proposed passages against original source.
6. Independent specification then quality review; full relevant frontend/backend checks; safe production backup/rehearsal of exact evidence patch, immutable release, deploy approved scope, apply version-bound patches, verify real site on 3 examples, hashes/history and audit chain. No Preview science import, no approvals, retain worktrees. Record live state and limitations in ignored run HANDOFF.

Evidence contract details may be tightened during implementation without changing approved behavior. Scientific output must match finalized schema before delivery.
